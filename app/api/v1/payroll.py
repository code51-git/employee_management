from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, Form, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, extract
from sqlalchemy.orm import selectinload, joinedload
from uuid import UUID
from datetime import date, datetime
from decimal import Decimal
from botocore.config import Config
import os
import boto3
import uuid
import re
from typing import Optional

from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.user import (
    Payroll, User, UserProfile, Leave, LeaveStatus,
    PayrollStatus, AdvanceSalaryRequest, AdvanceStatus,
    UserRole, EmployeeOvertime
)
from app.schemas.payroll import (
    PayrollGenerateInput, PayrollResponse, SalaryUpdatePayload,
    PayrollListResponse, PayrollAdjustmentPayload,
    AdvanceSalaryCreate, AdvanceSalaryResponse,
    AdvanceSalaryReview, AdvanceSalarySummaryResponse
)

router = APIRouter(prefix="/payroll", tags=["Payroll Management"])



def parse_salary_month(month_str: str) -> date:
    try:
        parts = month_str.strip().split("-")
        if len(parts) != 2:
            raise ValueError
        year = int(parts[0])
        month = int(parts[1])
        if year < 2000 or year > 2100:
            raise ValueError
        if month < 1 or month > 12:
            raise ValueError
        result = date(year, month, 1)
        assert isinstance(result, date)
        return result
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid salary_month '{month_str}'. Use YYYY-MM format e.g. '2026-06'"
        )



def recalculate_totals(entry: Payroll) -> Payroll:
    gross = (
        float(entry.basic_salary) +
        float(entry.hra) +
        float(entry.travel_allowance) +
        float(entry.health_allowance) +
        float(entry.overtime_pay) +
        float(entry.allowances)
    )
    daily_rate = float(entry.basic_salary) / 30.0
    lop_deduction = round(float(entry.lop_days) * daily_rate, 2)
    total_deductions = float(entry.deductions) + lop_deduction + float(entry.advance_deduction)
    net = round(max(0.0, gross - total_deductions), 2)

    entry.gross_salary = round(gross, 2)
    entry.lop_deduction = lop_deduction
    entry.net_salary = net
    return entry


#  GENERATE PAYROLL

@router.post("/generate", response_model=PayrollResponse, dependencies=[Depends(hr_and_admin)])
async def generate_employee_payroll(
    payload: PayrollGenerateInput,
    db: AsyncSession = Depends(get_db)
):

    salary_month_date = parse_salary_month(payload.salary_month)
    month_num = salary_month_date.month
    year_num = salary_month_date.year

    #  Fetch employee 
    user_res = await db.execute(
        select(User).options(selectinload(User.profile)).where(User.id == payload.user_id)
    )
    user = user_res.scalars().first()
    if not user or not user.profile:
        raise HTTPException(status_code=404, detail="Employee profile not found.")

    #  Duplicate check
    existing = await db.execute(
        select(Payroll).where(
            Payroll.user_id == payload.user_id,
            Payroll.salary_month == salary_month_date
        )
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=400,
            detail=f"Payroll already exists for {payload.salary_month}. Use /adjust/{{payroll_id}} to edit."
        )

    #  Basic salary
    master_basic = float(user.profile.basic_salary)
    final_basic = payload.basic_salary_override if payload.basic_salary_override is not None else master_basic
    if final_basic <= 0:
        raise HTTPException(status_code=400, detail="Basic salary must be greater than 0.")

    #  Manual fields 
    final_hra = payload.hra_override if payload.hra_override is not None else 0.0
    final_travel = payload.travel_allowance_override if payload.travel_allowance_override is not None else 0.0
    final_health = payload.health_allowance_override if payload.health_allowance_override is not None else 0.0
    final_allowances = payload.allowances_override if payload.allowances_override is not None else 0.0
    final_deductions = payload.deductions_override if payload.deductions_override is not None else 0.0

    #  Auto-calculate overtime from EmployeeOvertime table 
    ot_res = await db.execute(
        select(func.sum(EmployeeOvertime.ot_final_amount)).where(
            EmployeeOvertime.user_profile_id == user.profile.id,
            extract('month', EmployeeOvertime.date_worked) == month_num,
            extract('year', EmployeeOvertime.date_worked) == year_num
        )
    )
    auto_overtime = float(ot_res.scalar() or 0.0)

    #  Auto-calculate leaves 
    total_leave_days = 0.0
    sick_leave_days = 0.0
    casual_leave_days = 0.0
    lop_days = 0.0

    if payload.lop_days_override is not None:
        lop_days = float(payload.lop_days_override)
    else:
        leave_res = await db.execute(
            select(Leave).where(
                Leave.user_id == payload.user_id,
                Leave.status == LeaveStatus.APPROVED,
                extract('month', Leave.start_date) == month_num,
                extract('year', Leave.start_date) == year_num
            )
        )
        approved_leaves = leave_res.scalars().all()

        for leave in approved_leaves:
            # Parse duration
            match = re.search(r'\d+(\.\d+)?', leave.duration_days)
            days = float(match.group()) if match else 0.0
            total_leave_days += days

            leave_type_lower = leave.leave_type.lower().strip()

            if "sick" in leave_type_lower:
                # 1 free sick leave per month, rest is LOP
                sick_leave_days += days
                free_sick = 1.0
                if sick_leave_days > free_sick:
                    lop_days += (sick_leave_days - free_sick)

            elif "casual" in leave_type_lower:
                # 0.5 free casual leave per month, rest is LOP
                casual_leave_days += days
                free_casual = 0.5
                if casual_leave_days > free_casual:
                    lop_days += (casual_leave_days - free_casual)

            elif any(x in leave_type_lower for x in ["unpaid", "loss of pay", "lop"]):
                lop_days += days

    #  Auto-calculate advance deduction 
    advance_res = await db.execute(
        select(AdvanceSalaryRequest).where(
            AdvanceSalaryRequest.user_id == payload.user_id,
            AdvanceSalaryRequest.status == AdvanceStatus.APPROVED,
            AdvanceSalaryRequest.target_repayment_month == salary_month_date
        )
    )
    approved_advances = advance_res.scalars().all()
    advance_deduction = sum(float(adv.amount_requested) for adv in approved_advances)

    #  Calculate gross, LOP deduction, net 
    daily_rate = final_basic / 30.0
    lop_deduction = round(lop_days * daily_rate, 2)

    gross = round(
        final_basic + final_hra + final_travel +
        final_health + final_allowances + auto_overtime,
        2
    ) 
    total_deductions = final_deductions + lop_deduction + advance_deduction
    net = round(max(0.0, gross - total_deductions), 2)

    # Create payroll record 
    new_payroll = Payroll(
        user_id=payload.user_id,
        salary_month=salary_month_date,
        basic_salary=final_basic,
        hra=final_hra,
        travel_allowance=final_travel,
        health_allowance=final_health,
        overtime_pay=auto_overtime,
        allowances=final_allowances,
        gross_salary=gross,
        total_leave_days=total_leave_days,
        sick_leave_days=sick_leave_days,
        casual_leave_days=casual_leave_days,
        lop_days=lop_days,
        lop_deduction=lop_deduction,
        deductions=final_deductions,
        advance_deduction=advance_deduction,
        net_salary=net,
        status=PayrollStatus.DRAFT
    )

    # Mark advances as deducted
    for adv in approved_advances:
        adv.status = AdvanceStatus.DEDUCTED

    db.add(new_payroll)
    await db.commit()

    # Reload with user relationship
    result = await db.execute(
        select(Payroll)
        .options(joinedload(Payroll.user).joinedload(User.profile))
        .where(Payroll.id == new_payroll.id)
    )
    return result.scalars().first()


#  ADJUST PAYROLL 

@router.patch("/adjust/{payroll_id}", response_model=PayrollResponse, dependencies=[Depends(hr_and_admin)])
async def adjust_payroll(
    payroll_id: UUID,
    payload: PayrollAdjustmentPayload,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Payroll).where(Payroll.id == payroll_id))
    entry = result.scalars().first()

    if not entry:
        raise HTTPException(status_code=404, detail="Payroll record not found.")
    if entry.status == PayrollStatus.PAID:
        raise HTTPException(status_code=400, detail="Cannot alter a PAID payroll record.")

    if payload.basic_salary is not None:       entry.basic_salary = payload.basic_salary
    if payload.hra is not None:                entry.hra = payload.hra
    if payload.travel_allowance is not None:   entry.travel_allowance = payload.travel_allowance
    if payload.health_allowance is not None:   entry.health_allowance = payload.health_allowance
    if payload.overtime_pay is not None:       entry.overtime_pay = payload.overtime_pay
    if payload.allowances is not None:         entry.allowances = payload.allowances
    if payload.deductions is not None:         entry.deductions = payload.deductions
    if payload.lop_days is not None:           entry.lop_days = payload.lop_days
    if payload.advance_deduction is not None:  entry.advance_deduction = payload.advance_deduction
    if payload.status is not None:             entry.status = payload.status

    # Recalculate gross and net after any field change
    entry = recalculate_totals(entry)
    entry.generated_at = datetime.utcnow()

    await db.commit()

    final = await db.execute(
        select(Payroll)
        .options(joinedload(Payroll.user).joinedload(User.profile))
        .where(Payroll.id == payroll_id)
    )
    return final.scalars().first()


#  GET PAYROLL BY EMPLOYEE + MONTH

@router.get("/employee/{user_id}", response_model=PayrollResponse)
async def get_employee_monthly_payroll(
    user_id: UUID,
    month: str = Query(..., description="Format: YYYY-MM e.g. 2026-06"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value] and str(user_id) != str(caller_id):
        raise HTTPException(status_code=403, detail="Access denied.")

    salary_month_date = parse_salary_month(month)

    result = await db.execute(
        select(Payroll)
        .options(joinedload(Payroll.user).joinedload(User.profile))
        .where(
            Payroll.user_id == user_id,
            Payroll.salary_month == salary_month_date
        )
    )
    payroll = result.scalars().first()

    if not payroll:
        raise HTTPException(
            status_code=404,
            detail=f"No payroll found for employee {user_id} in {month}."
        )

    return payroll


#  LIST PAYROLL HISTORY 

@router.get("/list", response_model=PayrollListResponse)
async def list_payroll_history(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    month: Optional[str] = Query(None, description="Filter by month YYYY-MM"),
    target_user_id: Optional[UUID] = Query(None, description="Admin: filter by employee"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    base_query = select(Payroll).options(
        joinedload(Payroll.user).joinedload(User.profile)
    )

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        base_query = base_query.where(Payroll.user_id == caller_id)
    elif target_user_id:
        base_query = base_query.where(Payroll.user_id == target_user_id)

    if month:
        salary_month_date = parse_salary_month(month)
        base_query = base_query.where(Payroll.salary_month == salary_month_date)

    count_res = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total_count = count_res.scalar() or 0

    fetch_res = await db.execute(
        base_query.order_by(Payroll.salary_month.desc())
        .offset((page - 1) * size).limit(size)
    )
    items = fetch_res.scalars().unique().all()

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": items
    }


#  GET PAYROLL BY ID 

@router.get("/{payroll_id}", response_model=PayrollResponse)
async def get_payslip_by_id(
    payroll_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    result = await db.execute(
        select(Payroll)
        .options(joinedload(Payroll.user).joinedload(User.profile))
        .where(Payroll.id == payroll_id)
    )
    entry = result.scalars().first()

    if not entry:
        raise HTTPException(status_code=404, detail="Payroll record not found.")

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value] and str(entry.user_id) != str(caller_id):
        raise HTTPException(status_code=403, detail="Access denied.")

    return entry


#  UPDATE BASIC SALARY 

@router.patch("/salary-setup/{user_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(hr_and_admin)])
async def update_master_salary(
    user_id: UUID,
    payload: SalaryUpdatePayload,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Employee profile not found.")

    profile.basic_salary = payload.basic_salary
    await db.commit()
    return {"message": f"Basic salary updated to {payload.basic_salary:.2f}", "user_id": user_id}


#  ADVANCE SALARY REQUEST 

@router.post("/advance-request", status_code=status.HTTP_201_CREATED)
async def request_salary_advance(
    amount_requested: float = Form(...),
    reason: str = Form(...),
    target_repayment_month: date = Form(...),
    document: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    attachment_url = None

    cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
    cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
    cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
    cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
    cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

    if document and document.filename:
        try:
            file_extension = document.filename.split(".")[-1].lower() if "." in document.filename else "dat"
            unique_filename = f"advances/{uuid.uuid4()}.{file_extension}"
            s3_client = boto3.client(
                "s3",
                endpoint_url=f"https://{cf_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=cf_access_key,
                aws_secret_access_key=cf_secret_key,
                config=Config(signature_version="s3v4")
            )
            file_content = await document.read()
            s3_client.put_object(
                Bucket=cf_bucket_name,
                Key=unique_filename,
                Body=file_content,
                ContentType=document.content_type
            )
            attachment_url = f"{cf_public_url.rstrip('/')}/{unique_filename}"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    new_request = AdvanceSalaryRequest(
        id=uuid.uuid4(),
        user_id=caller_id,
        amount_requested=Decimal(str(amount_requested)),
        reason=reason,
        target_repayment_month=target_repayment_month.replace(day=1),
        document_url=attachment_url,
        status=AdvanceStatus.PENDING
    )
    db.add(new_request)
    await db.commit()
    await db.refresh(new_request)

    return {
        "message": "Advance request submitted.",
        "request_id": new_request.id,
        "document_url": attachment_url
    }


#  ADVANCE SALARY LIST 

@router.get("/advance-salary/list")
async def list_advance_requests(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status_filter: Optional[AdvanceStatus] = Query(None),
    target_user_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    base_query = select(AdvanceSalaryRequest)

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        base_query = base_query.where(AdvanceSalaryRequest.user_id == caller_id)
    elif target_user_id:
        base_query = base_query.where(AdvanceSalaryRequest.user_id == target_user_id)

    if status_filter:
        base_query = base_query.where(AdvanceSalaryRequest.status == status_filter)

    count_res = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total_count = count_res.scalar() or 0

    fetch_res = await db.execute(
        base_query.order_by(AdvanceSalaryRequest.requested_at.desc())
        .offset((page - 1) * size).limit(size)
    )
    items = fetch_res.scalars().all()

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "amount_requested": float(r.amount_requested),
                "reason": r.reason,
                "target_repayment_month": r.target_repayment_month,
                "status": r.status,
                "document_url": r.document_url,
                "requested_at": r.requested_at
            }
            for r in items
        ]
    }


#  ADVANCE SALARY REVIEW 

@router.patch("/advance-review/{advance_id}", dependencies=[Depends(hr_and_admin)])
async def review_advance_request(
    advance_id: UUID,
    payload: AdvanceSalaryReview,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AdvanceSalaryRequest).where(AdvanceSalaryRequest.id == advance_id))
    advance = result.scalars().first()

    if not advance:
        raise HTTPException(status_code=404, detail="Advance request not found.")
    if advance.status != AdvanceStatus.PENDING:
        raise HTTPException(status_code=400, detail="Request already reviewed.")

    advance.status = payload.status
    await db.commit()
    return {"message": f"Advance status updated to {payload.status.value}"}


#  ADVANCE SALARY SUMMARY 

@router.get("/summary", response_model=AdvanceSalarySummaryResponse)
async def advance_salary_summary(
    target_user_id: Optional[uuid.UUID] = Query(None),
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
    counts = {row[0]: row[1] for row in result.all()}

    return {
        "total": sum(counts.values()),
        "pending": counts.get(AdvanceStatus.PENDING, 0),
        "approved": counts.get(AdvanceStatus.APPROVED, 0),
        "rejected": counts.get(AdvanceStatus.REJECTED, 0),
    }