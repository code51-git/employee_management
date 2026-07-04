from pydantic import BaseModel
from uuid import UUID
from typing import Optional

# Base properties shared across schemas
class QualificationBase(BaseModel):
    degree_name: str
    institution: str
    passing_year: int
    percentage_or_cgpa: str

# Schema for creating a record
class QualificationCreate(QualificationBase):
    user_profile_id: UUID

# Schema for updating a record (all fields optional)
class QualificationUpdate(BaseModel):
    degree_name: Optional[str] = None
    institution: Optional[str] = None
    passing_year: Optional[int] = None
    percentage_or_cgpa: Optional[str] = None

# Schema for response payloads
class QualificationResponse(QualificationBase):
    id: UUID
    user_profile_id: UUID

    class Config:
        from_attributes = True