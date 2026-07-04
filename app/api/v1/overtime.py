from fastapi import APIRouter, Depends, HTTPException, status,Query,Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid
from sqlalchemy import func,extract
from app.core.database import get_db
from app.core.permissions import hr_and_admin,everyone
from app.models.user import UserProfile, EmployeeOvertime,UserRole
from app.schemas.overtime import OvertimeLogCreate
from typing import Optional
from sqlalchemy.orm import joinedload
from decimal import Decimal
from datetime import date


router = APIRouter(prefix="/overtime", tags=["Employee Overtime Management"])


def format_duration(hours_float: float) -> str:
    hours = int(hours_float)
    minutes = round((hours_float - hours) * 60)
    duration_string = f"{hours} hr"
    if minutes > 0:
        duration_string += f" {minutes} min"
    return duration_string



@router.post("/log", status_code=status.HTTP_201_CREATED)
async def log_employee_overtime(
    payload: OvertimeLogCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone) 
):
    caller_id = current_user.get("sub")  

    prof_res = await db.execute(select(UserProfile).where(UserProfile.user_id == caller_id))
    profile = prof_res.scalars().first()
    
    if not profile:
        raise HTTPException(status_code=404, detail="Employee profile not found.")

    basic_salary = Decimal(str(profile.basic_salary or "0.00"))
    hours_worked = Decimal(str(payload.hours_worked))
    
    ot_multiplier = Decimal(str(getattr(payload, "ot_rate", "2.00")))

    daily_rate = basic_salary / Decimal("30")
    hourly_base_rate = daily_rate / Decimal("8")
    final_calculated_amount = hourly_base_rate * ot_multiplier * hours_worked

    new_ot = EmployeeOvertime(
        id=uuid.uuid4(),
        user_profile_id=profile.id,
        date_worked=payload.date_worked,
        hours_worked=payload.hours_worked,
        description=payload.description,
        ot_rate=ot_multiplier,                       
        ot_final_amount=round(final_calculated_amount, 2) 
    )
    
    db.add(new_ot)
    await db.commit()
    
    total_hours_float = float(payload.hours_worked)
    hours = int(total_hours_float)
    minutes = round((total_hours_float - hours) * 60)
    
    duration_string = f"{hours} hr"
    if minutes > 0:
        duration_string += f" {minutes} min"
    
    return {
        "message": "Overtime logged successfully.",
        "date_worked": payload.date_worked,
        "hours_worked": duration_string,
        "ot_rate": float(ot_multiplier),
        "ot_final_amount": float(round(final_calculated_amount, 2))
    }

#summary

@router.get("/summary-list", dependencies=[Depends(hr_and_admin)])
async def list_employees_overtime_summary(
    month: Optional[int] = Query(None, ge=1, le=12, description="Month number (1-12)"),
    year: Optional[int] = Query(None, description="Year (e.g., 2026)"),
    db: AsyncSession = Depends(get_db)
):
    today = date.today()
    target_month = month or today.month
    target_year = year or today.year

    summary_query = (
        select(
            UserProfile.id.label("profile_id"),
            UserProfile.user_id.label("user_id"),
            UserProfile.first_name,
            UserProfile.last_name,
            UserProfile.designation,
            func.sum(EmployeeOvertime.hours_worked).label("total_hours"),
            func.sum(EmployeeOvertime.ot_final_amount).label("total_amount")
        )
        .join(EmployeeOvertime, UserProfile.id == EmployeeOvertime.user_profile_id)
        .where(
            extract("month", EmployeeOvertime.date_worked) == target_month,
            extract("year", EmployeeOvertime.date_worked) == target_year
        )
        .group_by(
            UserProfile.id, 
            UserProfile.user_id,
            UserProfile.first_name, 
            UserProfile.last_name, 
            UserProfile.designation
        )
        .order_by(UserProfile.first_name.asc())
    )

    result = await db.execute(summary_query)
    rows = result.all()

    formatted_summary = []
    
    STANDARD_MONTHLY_HOURS = Decimal("160.00")

    for row in rows:
        total_hours_dec = Decimal(str(row.total_hours or "0.00"))
        
        hours_int = int(total_hours_dec)
        minutes_int = round((total_hours_dec - hours_int) * 60)
        
        duration_string = f"{hours_int} hr"
        if minutes_int > 0:
            duration_string += f" {minutes_int} min"

        ot_percentage = (total_hours_dec / STANDARD_MONTHLY_HOURS) * Decimal("100") if total_hours_dec > 0 else Decimal("0.00")

        formatted_summary.append({
            "user_id": row.user_id,
            "user_profile_id": row.profile_id,
            "employee_name": f"{row.first_name or ''} {row.last_name or ''}".strip() or "Team Member",
            "designation": row.designation or "Not Assigned",
            "total_raw_hours": float(total_hours_dec),
            "total_duration_worked": duration_string,
            "total_payout_amount": float(round(Decimal(str(row.total_amount or "0.00")), 2)),
            "ot_percentage_of_month": float(round(ot_percentage, 1))
        })

    return {
        "filter_period": f"{target_year}-{target_month:02d}",
        "total_active_overtime_users": len(formatted_summary),
        "items": formatted_summary
    }

# LIST OVERTIME 
@router.get("/list")
async def list_overtime_records(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month number (1-12)"),
    year: Optional[int] = Query(None, description="Year (e.g., 2026)"),
    target_user_id: Optional[uuid.UUID] = Query(None, description="HR/Admin can pass a specific user UUID to filter"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    
    today = date.today()
    target_month = month or today.month
    target_year = year or today.year

    base_query = (
        select(EmployeeOvertime)
        .join(UserProfile)
        .where(
            extract("month", EmployeeOvertime.date_worked) == target_month,
            extract("year", EmployeeOvertime.date_worked) == target_year
        )
        .options(
            joinedload(EmployeeOvertime.profile)
            .joinedload(UserProfile.user)
        )
    )

    is_admin = caller_role in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]

    if not is_admin:
        base_query = base_query.where(UserProfile.user_id == caller_id)
    elif target_user_id:
        base_query = base_query.where(UserProfile.user_id == target_user_id)

    count_query = select(func.count(EmployeeOvertime.id)).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_query = base_query.order_by(EmployeeOvertime.date_worked.desc()).offset(offset).limit(size)
    fetch_result = await db.execute(fetch_query)
    records = fetch_result.scalars().unique().all()

    formatted_items = []
    total_expected_ot_accumulated = Decimal("0.00")

    for r in records:
        profile = r.profile
        hours_worked_dec = Decimal(str(r.hours_worked))
        ot_multiplier = Decimal(str(r.ot_rate))
        
        first = profile.first_name or "" if profile else ""
        last = profile.last_name or "" if profile else ""
        employee_name = f"{first} {last}".strip() or "Team Member"
        
        basic_salary = Decimal(str(profile.basic_salary or "0.00")) if profile else Decimal("0.00")
        daily_rate = basic_salary / Decimal("30")
        hourly_base_rate = daily_rate / Decimal("8")
        calculated_amount = hourly_base_rate * ot_multiplier * hours_worked_dec

        total_expected_ot_accumulated += calculated_amount

        item = {
            "id": r.id,
            "user_profile_id": r.user_profile_id,
            "employee_name": employee_name,
            "date_worked": r.date_worked,
            "raw_hours": float(r.hours_worked),
            "hours_worked": format_duration(float(r.hours_worked)),
            "ot_rate": float(r.ot_rate),
            "basic_salary": float(round(basic_salary, 2)),
            "hourly_rate": float(round(hourly_base_rate, 2)),
            "calculated_ot_amount": float(round(calculated_amount, 2)),
            "ot_final_amount": float(r.ot_final_amount),
            "description": r.description
        }

        formatted_items.append(item)

    return {
        "filter_period": f"{target_year}-{target_month:02d}",
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_expected_ot_amount": float(round(total_expected_ot_accumulated, 2)), # 🌟 Added metric
        "items": formatted_items
    }

#get by id
@router.get("/user/{target_user_id}")
async def get_overtime_records_by_user(
    target_user_id: uuid.UUID,
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month number (1-12)"),
    year: Optional[int] = Query(None, description="Year (e.g., 2026)"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    
    is_admin = caller_role in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]
    if not is_admin and str(target_user_id) != str(caller_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only view your own overtime records."
        )

    today = date.today()
    target_month = month or today.month
    target_year = year or today.year

    base_query = (
        select(EmployeeOvertime)
        .join(UserProfile)
        .where(
            UserProfile.user_id == target_user_id,
            extract("month", EmployeeOvertime.date_worked) == target_month,
            extract("year", EmployeeOvertime.date_worked) == target_year
        )
        .options(
            joinedload(EmployeeOvertime.profile)
            .joinedload(UserProfile.user)
        )
    )

    count_query = select(func.count(EmployeeOvertime.id)).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_query = base_query.order_by(EmployeeOvertime.date_worked.desc()).offset(offset).limit(size)
    fetch_result = await db.execute(fetch_query)
    records = fetch_result.scalars().unique().all()

    formatted_items = []
    for r in records:
        profile = r.profile
        hours_worked_dec = Decimal(str(r.hours_worked))
        ot_multiplier = Decimal(str(r.ot_rate))
        
        first = profile.first_name or "" if profile else ""
        last = profile.last_name or "" if profile else ""
        employee_name = f"{first} {last}".strip() or "Team Member"
        
        basic_salary = Decimal(str(profile.basic_salary or "0.00")) if profile else Decimal("0.00")
        daily_rate = basic_salary / Decimal("30")
        hourly_base_rate = daily_rate / Decimal("8")
        calculated_amount = hourly_base_rate * ot_multiplier * hours_worked_dec

        item = {
            "id": r.id,
            "user_profile_id": r.user_profile_id,
            "employee_name": employee_name,
            "date_worked": r.date_worked,
            "raw_hours": float(r.hours_worked),
            "hours_worked": format_duration(float(r.hours_worked)),
            "ot_rate": float(r.ot_rate),
            "basic_salary": float(round(basic_salary, 2)),
            "hourly_rate": float(round(hourly_base_rate, 2)),
            "calculated_ot_amount": float(round(calculated_amount, 2)),
            "ot_final_amount": float(r.ot_final_amount),
            "description": r.description
        }

        formatted_items.append(item)

    return {
        "filter_period": f"{target_year}-{target_month:02d}",
        "total_count": total_count,
        "page": page,
        "size": size,
        "items": formatted_items
    }


#finalize ot at the month end
@router.post("/process-monthly-ot", dependencies=[Depends(hr_and_admin)])
async def process_monthly_overtime(
    target_user_id: uuid.UUID = Query(..., description="The user UUID whose overtime needs to be finalized"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month number (1-12) to finalize"),
    year: Optional[int] = Query(None, description="Year (e.g., 2026)"),
    db: AsyncSession = Depends(get_db)
):
    today = date.today()
    target_month = month or today.month
    target_year = year or today.year

    prof_res = await db.execute(
        select(UserProfile).where(UserProfile.user_id == target_user_id)
    )
    profile = prof_res.scalars().first()
    
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Employee profile not found."
        )

    ot_res = await db.execute(
        select(EmployeeOvertime)
        .where(
            EmployeeOvertime.user_profile_id == profile.id,
            extract("month", EmployeeOvertime.date_worked) == target_month,
            extract("year", EmployeeOvertime.date_worked) == target_year
        )
    )
    records = ot_res.scalars().all()

    if not records:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No overtime records found to process for this employee in {target_year}-{target_month:02d}."
        )

    basic_salary = Decimal(str(profile.basic_salary or "0.00"))
    daily_rate = basic_salary / Decimal("30")
    hourly_base_rate = daily_rate / Decimal("8")

    total_approved_amount = Decimal("0.00")
    total_hours_processed = Decimal("0.00")

    for record in records:
        hours = Decimal(str(record.hours_worked))
        multiplier = Decimal(str(record.ot_rate))
        
        calculated_payout = hourly_base_rate * multiplier * hours
        rounded_payout = round(calculated_payout, 2)

        record.ot_final_amount = rounded_payout
        
        total_hours_processed += hours
        total_approved_amount += rounded_payout

    await db.commit()

    hours_int = int(total_hours_processed)
    minutes_int = round((total_hours_processed - hours_int) * 60)
    duration_string = f"{hours_int} hr"
    if minutes_int > 0:
        duration_string += f" {minutes_int} min"

    return {
        "message": f"Successfully processed and finalized overtime for {profile.first_name or 'Employee'}.",
        "target_period": f"{target_year}-{target_month:02d}",
        "employee_name": f"{profile.first_name or ''} {profile.last_name or ''}".strip(),
        "total_records_locked": len(records),
        "total_overtime_hours": duration_string,
        "final_payout_pushed_to_payroll": float(round(total_approved_amount, 2))
    }

# UPDATE OVERTIME LOG 
@router.patch("/update/{overtime_id}", dependencies=[Depends(hr_and_admin)])
async def update_overtime_record(
    overtime_id: uuid.UUID,
    hours_worked: Optional[float] = Query(None, gt=0, description="Updated decimal hours"),
    ot_rate: Optional[float] = Query(None, gt=0, description="Updated overtime multiplier (e.g., 1.5, 2.0)"),
    description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(EmployeeOvertime)
        .where(EmployeeOvertime.id == overtime_id)
        .options(joinedload(EmployeeOvertime.profile))
    )
    record = result.scalars().first()

    if not record:
        raise HTTPException(status_code=404, detail="Overtime record not found.")

    if description is not None:
        record.description = description
    if hours_worked is not None:
        record.hours_worked = hours_worked
    if ot_rate is not None:
        record.ot_rate = ot_rate

    profile = record.profile
    if profile:
        basic_salary = Decimal(str(profile.basic_salary or "0.00"))
        current_hours = Decimal(str(record.hours_worked))
        current_multiplier = Decimal(str(record.ot_rate))

        daily_rate = basic_salary / Decimal("30")
        hourly_base_rate = daily_rate / Decimal("8")
        new_calculated_amount = hourly_base_rate * current_multiplier * current_hours

        record.ot_final_amount = round(new_calculated_amount, 2)

    await db.commit()
    await db.refresh(record)

    return {
        "message": "Overtime record updated successfully.",
        "id": record.id,
        "date_worked": record.date_worked,
        "hours_worked": format_duration(float(record.hours_worked)),
        "ot_rate": float(record.ot_rate),
        "ot_final_amount": float(record.ot_final_amount),
        "description": record.description
    }

# DELETE OVERTIME LOG 
@router.delete("/delete/{overtime_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(hr_and_admin)])
async def delete_overtime_record(overtime_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(EmployeeOvertime).where(EmployeeOvertime.id == overtime_id))
    record = result.scalars().first()

    if not record:
        raise HTTPException(status_code=404, detail="Overtime record not found.")

    await db.delete(record)
    await db.commit()
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


#employee update
@router.patch("/my-update/{overtime_id}")
async def employee_update_overtime_record(
    overtime_id: uuid.UUID,
    hours_worked: Optional[float] = Query(None, gt=0, description="Updated decimal hours"),
    description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")

    result = await db.execute(
        select(EmployeeOvertime)
        .where(EmployeeOvertime.id == overtime_id)
        .options(
            joinedload(EmployeeOvertime.profile)
            .joinedload(UserProfile.user)
        )
    )
    record = result.scalars().first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Overtime record not found."
        )

    if not record.profile or str(record.profile.user_id) != str(caller_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access denied. You can only modify your own overtime logs."
        )

    if description is not None:
        record.description = description
        
    if hours_worked is not None:
        record.hours_worked = hours_worked
        
        profile = record.profile
        basic_salary = Decimal(str(profile.basic_salary or "0.00"))
        updated_hours = Decimal(str(record.hours_worked))
        existing_multiplier = Decimal(str(record.ot_rate))  

        daily_rate = basic_salary / Decimal("30")
        hourly_base_rate = daily_rate / Decimal("8")
        new_amount = hourly_base_rate * existing_multiplier * updated_hours
        
        record.ot_final_amount = round(new_amount, 2)

    await db.commit()
    await db.refresh(record)

    return {
        "message": "Your overtime record has been updated successfully.",
        "id": record.id,
        "date_worked": record.date_worked,
        "hours_worked": format_duration(float(record.hours_worked)),
        "ot_final_amount": float(record.ot_final_amount),
        "description": record.description
    }