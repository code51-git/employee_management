# app/schemas/payroll.py
from pydantic import BaseModel, Field,model_validator
from uuid import UUID
from datetime import date, datetime
from app.models.user import PayrollStatus,AdvanceStatus
from typing import Any
from pydantic.utils import GetterDict

class PayrollGetter(GetterDict):
    def get(self, key: str, default: Any = None) -> Any:
        if key == "employee_name":
            user = getattr(self._obj, "user", None)
            profile = getattr(user, "profile", None) if user else None
            if profile:
                first = getattr(profile, "first_name", "") or ""
                last = getattr(profile, "last_name", "") or ""
                full_name = f"{first} {last}".strip()
                return full_name if full_name else "Team Member"
            return "Team Member"
        
        return getattr(self._obj, key, default)

class PayrollGenerateInput(BaseModel):
    user_id: UUID
    pay_period_start: date
    pay_period_end: date
    
    basic_salary_override: float | None = Field(None, ge=0, description="Override master profile basic salary")
    overtime_pay_override: float | None = Field(None, ge=0, description="Override or force overtime pay")
    allowances_override: float | None = Field(None, ge=0, description="Override or force allowance pay")
    deductions_override: float | None = Field(None, ge=0, description="Override or force standard deductions")
    lop_days_override: int | None = Field(None, ge=0, description="Override or force total LOP days")


class PayrollResponse(BaseModel):
    id: UUID
    user_id: UUID
    employee_name: str
    pay_period_start: date
    pay_period_end: date
    basic_salary: float
    overtime_pay: float
    allowances: float
    total_leave_days: int
    lop_days: int
    lop_deduction: float
    deductions: float
    advance_deduction: float
    net_salary: float
    status: PayrollStatus
    generated_at: datetime

    class Config:
        from_attributes = True
    @model_validator(mode="before")
    @classmethod
    def assemble_employee_name(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "employee_name" not in data:
                data["employee_name"] = "Team Member"
            return data

        user = getattr(data, "user", None)
        profile = getattr(user, "profile", None) if user else None
        
        full_name = "Team Member"
        if profile:
            first = getattr(profile, "first_name", "") or ""
            last = getattr(profile, "last_name", "") or ""
            combined = f"{first} {last}".strip()
            if combined:
                full_name = combined

        setattr(data, "employee_name", full_name)
        
        return data

class PayrollListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: list[PayrollResponse]

class PayrollListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: list[PayrollResponse]

class PayrollAdjustmentPayload(BaseModel):
    basic_salary: float | None = Field(None, ge=0)
    overtime_pay: float | None = Field(None, ge=0)
    allowances: float | None = Field(None, ge=0)
    deductions: float | None = Field(None, ge=0)
    lop_days: int | None = Field(None, ge=0)
    status: PayrollStatus | None = None


class AdvanceSalaryCreate(BaseModel):
    amount_requested: float = Field(..., gt=0)
    reason: str
    target_repayment_month: date 

class AdvanceSalaryReview(BaseModel):
    status: AdvanceStatus 

class AdvanceSalaryResponse(BaseModel):
    id: UUID
    user_id: UUID
    amount_requested: float
    reason: str
    target_repayment_month: date
    status: AdvanceStatus
    requested_at: datetime

    class Config:
        from_attributes = True


class SalaryUpdatePayload(BaseModel):
    basic_salary: float = Field(..., ge=0, description="The master contractual basic monthly salary")


class AdvanceSalarySummaryResponse(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int