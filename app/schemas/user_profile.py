from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import date
from typing import List, Optional
from app.models.user import UserRole, UserStatus

class UserProfileRegister(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: str | None = None
    whatsapp_number: str | None = None
    company_email: EmailStr | None = None
    address: str | None = None
    
    employee_id: str             
    employee_type: str           
    department: str
    designation: str
    date_of_joining: date
    basic_salary: float = Field(0.00, ge=0, description="The master contractual basic monthly salary rate")
    total_industry_experience: float | None = 0.0


class BankDetailsResponse(BaseModel):
    account_holder_name: str
    account_number: str
    bank_name: str
    ifsc_code: str
    branch_name: Optional[str] = None

    class Config:
        from_attributes = True


class EmployeeDocumentResponse(BaseModel):
    document_type: str
    file_url: str
    uploaded_at: date

    class Config:
        from_attributes = True


class ProfileResponse(BaseModel):
    employee_id: str
    employee_type: str
    first_name: str
    last_name: str
    company_email: str | None = None
    phone_number: str | None = None
    whatsapp_number: str | None = None
    address: str | None = None
    department: str | None = None
    designation: str | None = None
    date_of_joining: date | None = None
    document_url: str | None = None
    profile_image_url: Optional[str] = None
    total_industry_experience: float | None = 0.0
    company_experience_years: str
    
    bank_details: Optional[BankDetailsResponse] = None
    documents: List[EmployeeDocumentResponse] = []

    class Config:
        from_attributes = True


class UserProfileResponse(BaseModel):
    id: UUID
    email: EmailStr
    role: UserRole
    status: UserStatus
    profile: ProfileResponse | None = None

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: list[UserProfileResponse]


class UserProfileUpdate(BaseModel):
    role: str | None = None
    status: str | None = None
    
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    whatsapp_number: str | None = None
    company_email: EmailStr | None = None
    address: str | None = None
    employee_type: str | None = None
    department: str | None = None
    designation: str | None = None
    date_of_joining: date | None = None
    total_industry_experience: float | None = None