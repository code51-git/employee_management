from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List
from app.models.announcement import AnnouncementPriority, AnnouncementStatus


class AnnouncementCreate(BaseModel):
    title: str = Field(..., max_length=255)
    content: str = Field(..., min_length=1)
    priority: AnnouncementPriority = AnnouncementPriority.MEDIUM
    expires_at: Optional[datetime] = None


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = None
    priority: Optional[AnnouncementPriority] = None
    expires_at: Optional[datetime] = None


class AnnouncementResponse(BaseModel):
    id: UUID
    title: str
    content: str
    priority: AnnouncementPriority
    status: AnnouncementStatus
    expires_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    is_read: Optional[bool] = False
    read_count: Optional[int] = 0

    class Config:
        from_attributes = False


class AnnouncementListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: List[AnnouncementResponse]