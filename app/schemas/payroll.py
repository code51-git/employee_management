from pydantic import BaseModel, Field, model_validator
from uuid import UUID
from datetime import date, datetime
from typing import Any, Optional
from app.models.user import PayrollStatus, AdvanceStatus


class PayrollGenerateInput(BaseModel):
    user_id: UUID
    salary_month: str = Field(..., description="Format: YYYY-MM e.g. 2026-06")

    # Manual overrides — if not provided, auto-calculated
    basic_salary_override: Optional[float] = Field(None, ge=0)
    hra_override: Optional[float] = Field(None, ge=0)
    travel_allowance_override: Optional[float] = Field(None, ge=0)
    health_allowance_override: Optional[float] = Field(None, ge=0)
    allowances_override: Optional[float] = Field(None, ge=0)
    deductions_override: Optional[float] = Field(None, ge=0)
    lop_days_override: Optional[float] = Field(None, ge=0)


class PayrollResponse(BaseModel):
    id: UUID
    user_id: UUID
    employee_name: str
    salary_month: str  # returned as "2026-06"

    basic_salary: float
    hra: float
    travel_allowance: float
    health_allowance: float
    overtime_pay: float
    allowances: float
    gross_salary: float

    total_leave_days: float
    sick_leave_days: float
    casual_leave_days: float
    lop_days: float
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
    def assemble_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "employee_name" not in data:
                data["employee_name"] = "Team Member"
            if "salary_month" in data and isinstance(data["salary_month"], date):
                data["salary_month"] = data["salary_month"].strftime("%Y-%m")
            return data

        # Format salary_month date → "2026-06"
        raw_month = getattr(data, "salary_month", None)
        if isinstance(raw_month, date):
            setattr(data, "salary_month", raw_month.strftime("%Y-%m"))

        # Resolve employee name
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


class PayrollAdjustmentPayload(BaseModel):
    """All fields manual — admin can override anything on an existing payroll."""
    basic_salary: Optional[float] = Field(None, ge=0)
    hra: Optional[float] = Field(None, ge=0)
    travel_allowance: Optional[float] = Field(None, ge=0)
    health_allowance: Optional[float] = Field(None, ge=0)
    overtime_pay: Optional[float] = Field(None, ge=0)
    allowances: Optional[float] = Field(None, ge=0)
    deductions: Optional[float] = Field(None, ge=0)
    lop_days: Optional[float] = Field(None, ge=0)
    advance_deduction: Optional[float] = Field(None, ge=0)
    status: Optional[PayrollStatus] = None


class PayrollListResponse(BaseModel):
    total_count: int
    page: int
    size: int
    total_pages: int
    items: list[PayrollResponse]


class SalaryUpdatePayload(BaseModel):
    basic_salary: float = Field(..., ge=0)


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


class AdvanceSalarySummaryResponse(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int