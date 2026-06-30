from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload, joinedload
from uuid import UUID
from datetime import date
import re

from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.user import (
    Payroll, 
    User, 
    UserProfile, 
    Leave, 
    LeaveStatus, 
    PayrollStatus, 
    AdvanceSalaryRequest, 
    AdvanceStatus, 
    UserRole
)
from app.schemas.payroll import (
    PayrollGenerateInput, 
    PayrollResponse, 
    SalaryUpdatePayload, 
    PayrollListResponse,
    PayrollAdjustmentPayload,
    AdvanceSalaryCreate,
    AdvanceSalaryResponse,
    AdvanceSalaryReview,
    AdvanceSalarySummaryResponse
)
from typing import Optional
import uuid
from datetime import datetime

router = APIRouter(prefix="/payroll", tags=["Payroll Management"])


#  PAYROLL GENERATION

@router.post("/generate", response_model=PayrollResponse, dependencies=[Depends(hr_and_admin)])
async def generate_accurate_employee_payroll(
    payload: PayrollGenerateInput,
    db: AsyncSession = Depends(get_db)
):

    user_result = await db.execute(
        select(User).options(selectinload(User.profile)).where(User.id == payload.user_id)
    )
    user = user_result.scalars().first()
    if not user or not user.profile:
        raise HTTPException(status_code=404, detail="Employee contract profile record not found.")

    existing_payroll_check = await db.execute(
        select(Payroll).where(
            Payroll.user_id == payload.user_id,
            Payroll.pay_period_start == payload.pay_period_start,
            Payroll.pay_period_end == payload.pay_period_end
        )
    )
    if existing_payroll_check.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Payroll record already exists for this employee from {payload.pay_period_start} "
                f"to {payload.pay_period_end}. Use the '/adjust/{{payroll_id}}' endpoint if you "
                f"need to make changes to this draft."
            )
        )

    master_basic = float(user.profile.basic_salary)
    final_basic = payload.basic_salary_override if payload.basic_salary_override is not None else master_basic
    
    if final_basic <= 0:
        raise HTTPException(status_code=400, detail="Calculated base basic salary must be greater than 0.")

    final_overtime = payload.overtime_pay_override if payload.overtime_pay_override is not None else 0.0
    final_allowances = payload.allowances_override if payload.allowances_override is not None else 0.0
    final_deductions = payload.deductions_override if payload.deductions_override is not None else 0.0

    total_leaves_taken = 0
    calculated_lop_days = 0

    if payload.lop_days_override is not None:
        calculated_lop_days = payload.lop_days_override
        total_leaves_taken = payload.lop_days_override
    else:
        leave_result = await db.execute(
            select(Leave).where(
                Leave.user_id == payload.user_id,
                Leave.status == LeaveStatus.APPROVED,
                Leave.start_date <= payload.pay_period_end,
                Leave.end_date >= payload.pay_period_start
            )
        )
        approved_leaves = leave_result.scalars().all()

        for leave in approved_leaves:
            match = re.search(r'\d+(\.\d+)?', leave.duration_days)
            days = float(match.group()) if match else 0.0
            
            total_leaves_taken += days
            leave_type_lower = leave.leave_type.lower()
            
            if "casual" in leave_type_lower:
                if days > 0.5:
                    calculated_lop_days += (days - 0.5)  
            elif leave_type_lower in ["unpaid leave", "loss of pay", "lop"]:
                calculated_lop_days += days

    target_month_normalized = payload.pay_period_start.replace(day=1)
    advance_result = await db.execute(
        select(AdvanceSalaryRequest).where(
            AdvanceSalaryRequest.user_id == payload.user_id,
            AdvanceSalaryRequest.status == AdvanceStatus.APPROVED,
            AdvanceSalaryRequest.target_repayment_month == target_month_normalized
        )
    )
    approved_advances = advance_result.scalars().all()
    auto_advance_deduction = sum(float(adv.amount_requested) for adv in approved_advances)

    daily_salary_rate = final_basic / 30.0
    computed_lop_deduction = calculated_lop_days * daily_salary_rate

    gross_earnings = final_basic + final_allowances + final_overtime
    total_all_deductions = final_deductions + computed_lop_deduction + auto_advance_deduction
    
    final_net_salary = max(0.0, gross_earnings - total_all_deductions)

    new_payroll = Payroll(
        user_id=payload.user_id,
        pay_period_start=payload.pay_period_start,
        pay_period_end=payload.pay_period_end,
        basic_salary=final_basic,
        overtime_pay=final_overtime,
        allowances=final_allowances,
        total_leave_days=total_leaves_taken,
        lop_days=calculated_lop_days,
        lop_deduction=round(computed_lop_deduction, 2),
        advance_deduction=round(auto_advance_deduction, 2),
        deductions=final_deductions,
        net_salary=round(final_net_salary, 2),
        status=PayrollStatus.DRAFT
    )

    for adv in approved_advances:
        adv.status = AdvanceStatus.DEDUCTED

    db.add(new_payroll)
    await db.commit()
    await db.refresh(new_payroll)
    return new_payroll

#list
@router.get("/advance-salary/list")
async def list_advance_salary_requests(
    page: int = Query(1, ge=1, description="Page number index"),
    size: int = Query(10, ge=1, le=100, description="Items per window page"),
    status_filter: Optional[AdvanceStatus] = Query(None, description="Filter requests by status"),
    target_user_id: Optional[uuid.UUID] = Query(None, description="HR/Admin only: filter results for a specific employee"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    base_query = select(AdvanceSalaryRequest).join(UserProfile, UserProfile.user_id == AdvanceSalaryRequest.user_id)

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        base_query = base_query.where(AdvanceSalaryRequest.user_id == caller_id)
    elif target_user_id:
        base_query = base_query.where(AdvanceSalaryRequest.user_id == target_user_id)

    if status_filter:
        base_query = base_query.where(AdvanceSalaryRequest.status == status_filter)

    count_query = select(func.count(AdvanceSalaryRequest.id)).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_query = (
        base_query
        .order_by(AdvanceSalaryRequest.requested_at.desc())
        .offset(offset)
        .limit(size)
    )
    fetch_result = await db.execute(fetch_query)
    requests_list = fetch_result.scalars().all()

    total_pages = (total_count + size - 1) // size if total_count > 0 else 0

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": total_pages,
        "items": [
            {
                "id": req.id,
                "user_id": req.user_id,
                "amount_requested": float(req.amount_requested),
                "reason": req.reason,
                "target_repayment_month": req.target_repayment_month,
                "status": req.status,
                "requested_at": req.requested_at
            }
            for req in requests_list
        ]
    }

#adv salary summary
@router.get("/summary", response_model=AdvanceSalarySummaryResponse)
async def get_advance_salary_requests_summary(
    target_user_id: Optional[uuid.UUID] = Query(None, description="HR/Admin can pass a specific user UUID to filter metrics"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    query = select(AdvanceSalaryRequest.status, func.count(AdvanceSalaryRequest.id))

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        query = query.where(AdvanceSalaryRequest.user_id == caller_id)
    elif target_user_id:
        query = query.where(AdvanceSalaryRequest.user_id == target_user_id)

    query = query.group_by(AdvanceSalaryRequest.status)
    result = await db.execute(query)
    
    status_counts = {row[0]: row[1] for row in result.all()}

    pending_count = status_counts.get(AdvanceStatus.PENDING, 0)
    approved_count = status_counts.get(AdvanceStatus.APPROVED, 0)
    rejected_count = status_counts.get(AdvanceStatus.REJECTED, 0)
    
    total_count = pending_count + approved_count + rejected_count

    return {
        "total": total_count,
        "pending": pending_count,
        "approved": approved_count,
        "rejected": rejected_count
    }


#update basic salary

@router.patch("/salary-setup/{user_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(hr_and_admin)])
async def update_employee_master_salary(
    user_id: UUID,
    payload: SalaryUpdatePayload,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalars().first()

    if not profile:
        raise HTTPException(status_code=404, detail="Employee target profile profile not localized.")

    profile.basic_salary = payload.basic_salary
    await db.commit()
    return {"message": f"Contractual basic salary configured to {payload.basic_salary:.2f}", "user_id": user_id}


#patch
@router.patch("/adjust/{payroll_id}", response_model=PayrollResponse, dependencies=[Depends(hr_and_admin)])
async def adjust_existing_payroll_record(
    payroll_id: UUID,
    payload: PayrollAdjustmentPayload,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Payroll).where(Payroll.id == payroll_id))
    entry = result.scalars().first()

    if not entry:
        raise HTTPException(status_code=404, detail="Payroll transactional record not found.")
    if entry.status == PayrollStatus.PAID:
        raise HTTPException(status_code=400, detail="Cannot alter records already locked and marked as PAID.")

    if payload.basic_salary is not None: entry.basic_salary = payload.basic_salary
    if payload.overtime_pay is not None: entry.overtime_pay = payload.overtime_pay
    if payload.allowances is not None: entry.allowances = payload.allowances
    if payload.deductions is not None: entry.deductions = payload.deductions
    if payload.lop_days is not None: entry.lop_days = payload.lop_days
    if payload.status is not None: entry.status = payload.status

    daily_rate = float(entry.basic_salary) / 30.0
    entry.lop_deduction = round(int(entry.lop_days) * daily_rate, 2)

    gross = float(entry.basic_salary) + float(entry.allowances) + float(entry.overtime_pay)
    deductions = float(entry.deductions) + float(entry.lop_deduction) + float(entry.advance_deduction)

    entry.net_salary = round(max(0.0, gross - deductions), 2)
    entry.generated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(entry)
    return entry


#list payroll
@router.get("/list", response_model=PayrollListResponse)
async def list_payroll_history(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    target_date: Optional[date] = Query(None, description="Filter payroll records containing this date (YYYY-MM-DD)"), 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):  
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    base_query = select(Payroll)
    
    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        base_query = base_query.where(Payroll.user_id == caller_id)

    if target_date:
        base_query = base_query.where(
            Payroll.pay_period_start <= target_date,
            Payroll.pay_period_end >= target_date
        )

    base_query = base_query.order_by(Payroll.pay_period_start.desc())

    subq = base_query.subquery()
    count_result = await db.execute(select(func.count()).select_from(subq))
    total_count = count_result.scalar() or 0

    fetch_result = await db.execute(base_query.offset((page - 1) * size).limit(size))
    
    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": fetch_result.scalars().all()
    }


#get payroll by id
@router.get("/{payroll_id}", response_model=PayrollResponse)
async def get_payslip_by_id(
    payroll_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    result = await db.execute(
        select(Payroll).options(joinedload(Payroll.user).joinedload(User.profile)).where(Payroll.id == payroll_id)
    )
    entry = result.scalars().first()

    if not entry:
        raise HTTPException(status_code=404, detail="Target payslip record not found.")
        
    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value] and str(entry.user_id) != str(caller_id):
        raise HTTPException(status_code=403, detail="Access denied. Authority constraint violation.")

    return entry


#advance req

@router.post("/advance-request", response_model=AdvanceSalaryResponse)
async def request_salary_advance(
    payload: AdvanceSalaryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    """Enables standalone employee profiles to enqueue salary advance buffer applications."""
    caller_id = current_user.get("sub")
    new_request = AdvanceSalaryRequest(
        user_id=caller_id,
        amount_requested=payload.amount_requested,
        reason=payload.reason,
        target_repayment_month=payload.target_repayment_month.replace(day=1),
        status=AdvanceStatus.PENDING
    )
    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)
    return new_request




@router.patch("/advance-review/{advance_id}", dependencies=[Depends(hr_and_admin)])
async def review_salary_advance(
    advance_id: UUID,
    payload: AdvanceSalaryReview,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AdvanceSalaryRequest).where(AdvanceSalaryRequest.id == advance_id))
    advance_req = result.scalars().first()
    
    if not advance_req:
        raise HTTPException(status_code=404, detail="Advance transaction allocation reference entry absent.")
    if advance_req.status != AdvanceStatus.PENDING:
        raise HTTPException(status_code=400, detail="Target item was already audited and closed.")
        
    advance_req.status = payload.status
    await db.commit()
    return {"message": f"Advance application modification settled to: {payload.status.value}"}


#pdf
