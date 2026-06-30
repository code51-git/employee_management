from pydantic import BaseModel, Field
from uuid import UUID
from datetime import date
from typing import Optional

class OvertimeLogCreate(BaseModel):
    date_worked: date
    hours_worked: float = Field(..., gt=0, description="Hours worked as a decimal, e.g., 4.75")
    description: Optional[str] = None