from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from app.core.config import settings
from app.core.rate_limiter import redis_client
from app.models.user import UserRole

security = HTTPBearer()

class SingleRoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = [role.value if isinstance(role, UserRole) else str(role) for role in allowed_roles]

    async def __call__(self, creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
        token = creds.credentials
        
        is_blacklisted = await redis_client.get(f"blacklist:{token}")
        if is_blacklisted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked. Please log in again."
            )

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            if payload.get("type") != "access":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type.")
                
            user_role = payload.get("role")
            
            if user_role not in self.allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied. You do not have permission to access this resource."
                )
                
            return payload
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token expired.")
        except jwt.PyJWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token.")

admin_only = SingleRoleChecker([UserRole.SUPER_ADMIN])
hr_and_admin = SingleRoleChecker([UserRole.SUPER_ADMIN, UserRole.HR_ADMIN])
user_only = SingleRoleChecker([UserRole.USER])  
everyone = SingleRoleChecker([UserRole.SUPER_ADMIN, UserRole.HR_ADMIN, UserRole.USER])