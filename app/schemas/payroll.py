# app/schemas/payroll.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import date, datetime
from app.models.user import PayrollStatus,AdvanceStatus

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