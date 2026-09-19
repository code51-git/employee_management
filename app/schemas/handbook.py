from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class HandbookResponse(BaseModel):
    id: UUID
    title: str
    file_url: str
    is_active: bool
    uploaded_at: datetime

    class Config:
        from_attributes = True


class HandbookListResponse(BaseModel):
    items: list[HandbookResponse]

class HandbookUpdate(BaseModel):
    title: str | None = None
    is_active: bool | None = None