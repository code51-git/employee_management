from pydantic import BaseModel
from uuid import UUID
from datetime import date

class HolidayCreate(BaseModel):
    holiday_date: date
    name: str
    is_mandatory: bool = True

class HolidayUpdate(BaseModel):
    holiday_date: date | None = None
    name: str | None = None
    is_mandatory: bool | None = None

class HolidayResponse(BaseModel):
    id: UUID
    holiday_date: date
    name: str
    is_mandatory: bool

    class Config:
        from_attributes = True