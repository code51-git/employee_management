from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime
from typing import Optional
from app.models.user import AttendanceStatus

class AttendanceMarkRequest(BaseModel):
    user_id: UUID
    work_date: Optional[date] = None       
    clock_in: datetime
    clock_out: Optional[datetime] = None


class AttendanceCheckoutRequest(BaseModel):
    clock_out: datetime


class AttendanceResponse(BaseModel):
    id: UUID
    user_id: UUID
    work_date: date
    clock_in: datetime
    clock_out: Optional[datetime] = None
    total_hours: Optional[float] = None
    status: str

    class Config:
        from_attributes = True


class AttendanceListResponse(BaseModel):
    items: list[AttendanceResponse]


class AttendanceSummaryResponse(BaseModel):
    date: date
    total_employees: int
    present_today: int
    absent_today: int
    late_arrivals: int   
    absent_user_ids: list[UUID]


class AttendanceUpdateRequest(BaseModel):
    work_date: date | None = None
    clock_in: datetime | None = None
    clock_out: datetime | None = None