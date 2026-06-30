from pydantic import BaseModel, EmailStr,Field
from uuid import UUID
from app.models.user import UserRole, UserStatus

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    user_id : UUID
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: UserRole


class UserRegister(BaseModel):
    email: EmailStr
    password: str
    first_name: str
    last_name: str

class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    role: UserRole
    status: UserStatus

    class Config:
        from_attributes = True

class TokenRefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordOTPRequest(BaseModel):
    email: EmailStr

class VerifyOTPAndResetSubmit(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6, description="The 6-digit OTP code")
    new_password: str = Field(..., min_length=8, description="Minimum 8 characters require")
    
