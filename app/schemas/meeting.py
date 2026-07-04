from pydantic import BaseModel
from uuid import UUID
from datetime import date, time, datetime

class MeetingCreate(BaseModel):
    title: str
    description: str | None = None
    meeting_date: date
    start_time: time
    end_time: time
    meeting_link: str | None = None
    attendee_ids: list[UUID]

class MeetingResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    meeting_date: date
    start_time: time
    end_time: time
    meeting_link: str | None = None
    organizer_id: UUID
    attendee_ids: list[UUID]
    created_at: datetime

    class Config:
        from_attributes = True

class MeetingListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: list[MeetingResponse]
    
class MeetingUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    meeting_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    meeting_link: str | None = None
    attendee_ids: list[UUID] | None = None