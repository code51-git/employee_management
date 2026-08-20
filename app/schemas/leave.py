# app/schemas/leave.py
from pydantic import BaseModel, field_validator
from uuid import UUID
from datetime import date
from app.models.user import LeaveStatus
from typing import Optional
class LeaveRequestCreate(BaseModel):
    leave_type: str  
    start_date: date
    end_date: date
    reason: str

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, end_date: date, info) -> date:
        start_date = info.data.get("start_date")
        if start_date and end_date < start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return end_date

class LeaveReviewPayload(BaseModel):
    status: LeaveStatus  

class LeaveUserSummary(BaseModel):
    id: UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None
    employee_id: str | None = None

    class Config:
        from_attributes = True

class LeaveResponse(BaseModel):
    id: UUID
    user_id: UUID
    duration_days: str
    leave_type: str
    start_date: date
    end_date: date
    document:Optional[str] = None
    reason: str
    status: LeaveStatus
    
    user_details: LeaveUserSummary | None = None

    class Config:
        from_attributes = True

class LeaveListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: list[LeaveResponse]


class LeaveSummaryResponse(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int

class LeaveUserDetails(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    employee_id: Optional[str] = None

class LeaveDetailResponse(BaseModel):
    id: UUID
    user_id: UUID
    duration_days: str
    leave_type: str
    start_date: date
    end_date: date
    reason: str
    document: Optional[str] = None
    status: LeaveStatus
    user_details: Optional[LeaveUserDetails] = None

    class Config:
        from_attributes = True