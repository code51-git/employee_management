from fastapi import APIRouter, Depends, HTTPException, status, Request,BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import jwt
from datetime import datetime, timezone
from app.core.database import get_db
from app.core.config import settings
from app.core.security import verify_password, create_access_token, create_refresh_token
from app.core.rate_limiter import rate_limiter, redis_client
from app.models.user import User
from app.schemas.user import UserLogin, TokenResponse,TokenRefreshRequest
from app.schemas.user import *
from datetime import datetime, timedelta, timezone
import secrets
from app.core.security import hash_password
from app.services.email import send_password_reset_otp_email
from app.core.permissions import  everyone
import uuid
from sqlalchemy import update


router = APIRouter(prefix="/auth", tags=["Authentication"])

async def login_rate_limiter(request: Request):
    await rate_limiter(request, limit=5, window=60)

#login
@router.post("/login", response_model=TokenResponse)
async def login(
    payload: UserLogin, 
    request: Request,
    db: AsyncSession = Depends(get_db),
    _ = Depends(login_rate_limiter) 
):

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalars().first()
    
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password."
        )
        
    token_data = {"sub": str(user.id), "role": user.role.value}
    
    return {
        "user_id": user.id,
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "role": user.role.value        
    }

#logout
@router.post("/logout")
async def logout(request: Request):

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token header.")
        
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        exp_time = payload["exp"]
        remaining_time = exp_time - int(datetime.utcnow().timestamp())
        
        if remaining_time > 0:
            await redis_client.setex(f"blacklist:{token}", remaining_time, "true")
            
        return {"detail": "Successfully logged out and session blacklisted."}
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token already expired or corrupted.")
    
#refresh
async def refresh_rate_limiter(request: Request):
    await rate_limiter(request, limit=10, window=60)

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    payload: TokenRefreshRequest,
    db: AsyncSession = Depends(get_db),
    _ = Depends(refresh_rate_limiter)
):

    try:
        decoded_payload = jwt.decode(payload.refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        if decoded_payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")
            
        user_id = decoded_payload.get("sub")
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has expired. Please log in again.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token structure.")

    is_blacklisted = await redis_client.get(f"blacklist:{payload.refresh_token}")
    if is_blacklisted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked. Security breach suspected.")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if not user or user.status.value != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is inactive or suspended.")

    exp_time = decoded_payload["exp"]
    remaining_time = exp_time - int(datetime.utcnow().timestamp())
    if remaining_time > 0:
        await redis_client.setex(f"blacklist:{payload.refresh_token}", remaining_time, "true")

    token_data = {"sub": str(user.id), "role": user.role.value}
    new_access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)

    return {
        "user_id": user.id,
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "role": user.role.value        

    }


#reset pwd
@router.post("/reset-password/request-otp")
async def request_password_reset_otp(
    payload: ForgotPasswordOTPRequest, 
    background_tasks: BackgroundTasks, 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalars().first()

    if not user:
        return {"message": "If the account exists, a verification OTP has been sent successfully."}

    secure_otp = "".join(secrets.choice("0123456789") for _ in range(6))
    user.password_reset_otp = secure_otp
    user.otp_expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    
    await db.commit()

    background_tasks.add_task(send_password_reset_otp_email, email_to=user.email, otp=secure_otp)
    
    return {"message": "If the account exists, a verification OTP has been sent successfully."}


# VERIFY OTP AND RESET PASSWORD 
@router.post("/reset-password/verify-otp")
async def verify_otp_and_reset_password(payload: VerifyOTPAndResetSubmit, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(
            User.email == payload.email,
            User.password_reset_otp == payload.otp,
            User.otp_expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
        )
    )
    user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="The verification OTP code provided is invalid or has already expired."
        )

    user.hashed_password = hash_password(payload.new_password)
    user.password_reset_otp = None
    user.otp_expires_at = None
    
    await db.commit()
    return {"message": "Password updated successfully. You can now log in using your fresh credentials."}


@router.post("/fcm-token", status_code=status.HTTP_200_OK)
async def update_fcm_token(
    payload: FCMTokenUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    await db.execute(
        update(User)
        .where(User.id == caller_id)
        .values(fcm_token=payload.fcm_token)
    )
    await db.commit()
    return {"message": "FCM token updated successfully."}


@router.delete("/fcm-token", status_code=status.HTTP_200_OK)
async def clear_fcm_token(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    await db.execute(
        update(User)
        .where(User.id == caller_id)
        .values(fcm_token=None)
    )
    await db.commit()
    return {"message": "FCM token cleared."}