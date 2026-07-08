from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List

# Core shared properties
class ExperienceBase(BaseModel):
    company_name: str
    comapany_role:str
    experience_years: str
    reason_for_leaving: str
    hr_contact_number: Optional[str] = None

# Response validation payload
class ExperienceResponse(ExperienceBase):
    id: UUID
    user_profile_id: UUID
    company_document_urls: List[str] = []  # Returns array of R2 file paths

    class Config:
        from_attributes = True