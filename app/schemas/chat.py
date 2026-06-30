from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import List, Optional
from app.models.chats import ChatType
import uuid


class RoomCreate(BaseModel):
    name: Optional[str] = Field(None, max_length=150, description="Leave blank for 1-to-1 direct chats")
    type: ChatType
    initial_member_ids: List[UUID] = Field(default_factory=list, description="User UUIDs to inject immediately")


class MemberManage(BaseModel):
    user_ids: List[UUID]


class BroadcastCreate(BaseModel):
    title: Optional[str] = Field("System Announcement", max_length=150)
    message_text: str = Field(..., min_length=1)
    recipient_ids: Optional[List[UUID]] = Field(None, description="If empty/null, reaches all company accounts")


class MessageResponse(BaseModel):
    id: UUID
    room_id: UUID
    sender_id: UUID
    sender_name: str          
    content: str
    created_at: datetime
    is_read: Optional[bool] = False
    is_starred: Optional[bool] = False

    class Config:
        from_attributes = False  


class RoomResponse(BaseModel):
    id: UUID
    name: Optional[str]
    type: ChatType
    created_at: datetime
    created_by: Optional[UUID]
    latest_message: Optional[str] = None        
    latest_message_at: Optional[datetime] = None 
    latest_message_by: Optional[str] = None  

    class Config:
        from_attributes = False

class MessageReadResponse(BaseModel):
    message_id: UUID
    user_id: UUID
    read_at: datetime

    class Config:
        from_attributes = True


class StarredMessageResponse(BaseModel):
    message_id: UUID
    user_id: UUID
    starred_at: datetime

    class Config:
        from_attributes = True


# ── New response schemas for recent endpoints ─────────────────────────────────

class MarkReadResponse(BaseModel):
    message: str
    marked_count: int


class ToggleStarResponse(BaseModel):
    message: str
    starred: bool
    message_id: UUID


class ClearChatResponse(BaseModel):
    message: str
    cleared_at: datetime


class DeleteMessageResponse(BaseModel):
    message: str
    message_id: UUID


class DirectRoomRequest(BaseModel):
    target_user_id: UUID


class StarredMessageDetailResponse(BaseModel):
    id: UUID
    room_id: UUID
    sender_id: UUID
    content: str
    created_at: datetime
    starred_at: datetime

    class Config:
        from_attributes = True