# app/schemas/bill.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from app.models.user import BillStatus
from datetime import date

class BillRequestCreate(BaseModel):
    title: str = Field(..., max_length=150)
    amount: float = Field(..., gt=0)
    description: str | None = None
    attachment_url: str | None = None
    spent_date: date = Field(..., description="Date layout format: YYYY-MM-DD")

class BillReviewPayload(BaseModel):
    status: BillStatus

class BillUserSummary(BaseModel):
    id: UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None

class BillResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    amount: float
    description: str | None = None
    attachment_url: str | None = None
    status: BillStatus
    created_at: datetime
    user_details: BillUserSummary | None = None

    class Config:
        from_attributes = True

class BillListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: list[BillResponse]

class BillSummaryResponse(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int