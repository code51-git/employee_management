from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List

class QualificationBase(BaseModel):
    degree_name: str
    institution: str
    passing_year: int

class QualificationCreate(QualificationBase):
    user_profile_id: UUID

class QualificationUpdate(BaseModel):
    degree_name: Optional[str] = None
    institution: Optional[str] = None
    passing_year: Optional[int] = None
    mark_list_urls: Optional[List[str]] = None  
    grade_card_url: Optional[str] = None

class QualificationResponse(QualificationBase):
    id: UUID
    user_profile_id: UUID
    
    mark_list_urls: List[str] = []
    grade_card_url: Optional[str] = None

    class Config:
        from_attributes = True