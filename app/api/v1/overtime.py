from fastapi import APIRouter, Depends, HTTPException, status,Query,Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid
from sqlalchemy import func
from app.core.database import get_db
from app.core.permissions import hr_and_admin,everyone
from app.models.user import UserProfile, EmployeeOvertime,UserRole
from app.schemas.overtime import OvertimeLogCreate
from typing import Optional


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

    new_ot = EmployeeOvertime(
        id=uuid.uuid4(),
        user_profile_id=profile.id,
        date_worked=payload.date_worked,
        hours_worked=payload.hours_worked,
        description=payload.description
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
        "hours_worked": duration_string
    }


# LIST OVERTIME 
@router.get("/list")
async def list_overtime_records(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    target_user_id: Optional[uuid.UUID] = Query(None, description="HR/Admin can pass a specific user UUID to filter"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    
    # Base query joining user profiles
    base_query = select(EmployeeOvertime).join(UserProfile)

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        base_query = base_query.where(UserProfile.user_id == caller_id)
    elif target_user_id:
        base_query = base_query.where(UserProfile.user_id == target_user_id)

    count_query = select(func.count(EmployeeOvertime.id)).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_query = base_query.order_by(EmployeeOvertime.date_worked.desc()).offset(offset).limit(size)
    fetch_result = await db.execute(fetch_query)
    records = fetch_result.scalars().all()

    formatted_items = [
        {
            "id": r.id,
            "user_profile_id": r.user_profile_id,
            "date_worked": r.date_worked,
            "raw_hours": float(r.hours_worked),
            "hours_worked": format_duration(float(r.hours_worked)),
            "description": r.description
        }
        for r in records
    ]

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "items": formatted_items
    }


# UPDATE OVERTIME LOG 
@router.patch("/update/{overtime_id}", dependencies=[Depends(hr_and_admin)])
async def update_overtime_record(
    overtime_id: uuid.UUID,
    hours_worked: Optional[float] = Query(None, gt=0, description="Updated decimal hours"),
    description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(EmployeeOvertime).where(EmployeeOvertime.id == overtime_id))
    record = result.scalars().first()

    if not record:
        raise HTTPException(status_code=404, detail="Overtime record not found.")

    if hours_worked is not None:
        record.hours_worked = hours_worked
    if description is not None:
        record.description = description

    await db.commit()
    await db.refresh(record)

    return {
        "message": "Overtime record updated successfully.",
        "id": record.id,
        "date_worked": record.date_worked,
        "hours_worked": format_duration(float(record.hours_worked))
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