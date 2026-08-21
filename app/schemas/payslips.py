import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

class PayslipResponse(BaseModel):
    id: uuid.UUID
    user_profile_id: uuid.UUID
    title: Optional[str] = None
    old_payslip_url: Optional[str] = None
    new_payslip_url: Optional[str] = None
    uploaded_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class BulkPayslipUploadResponse(BaseModel):
    message: str
    total_uploaded: int
    payslips: List[PayslipResponse]