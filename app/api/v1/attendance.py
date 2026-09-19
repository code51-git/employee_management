import uuid
from datetime import date, datetime, time
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.user import Attendance, AttendanceStatus
from app.models.user import User
from app.schemas.attendance import (
    AttendanceMarkRequest, AttendanceCheckoutRequest,
    AttendanceResponse, AttendanceListResponse, AttendanceSummaryResponse,AttendanceUpdateRequest
)
from app.models.user import UserRole

router = APIRouter(prefix="/attendance", tags=["Attendance"])

OFFICE_START = time(9, 0)
LATE_CUTOFF = time(9, 20)   # after this → half day




def determine_status(clock_in: datetime) -> AttendanceStatus:
    return AttendanceStatus.PRESENT if clock_in.time() <= LATE_CUTOFF else AttendanceStatus.HALF_DAY

BREAK_HOURS = 1.0

def compute_hours(clock_in: datetime, clock_out: datetime | None) -> float | None:
    if not clock_out:
        return None
    raw_hours = (clock_out - clock_in).total_seconds() / 3600
    worked_hours = max(raw_hours - BREAK_HOURS, 0)
    return round(worked_hours, 2)


# MARK ATTENDANCE MANUALLY (HR/Admin)
@router.post("/mark", response_model=AttendanceResponse, dependencies=[Depends(hr_and_admin)])
async def mark_attendance(
    payload: AttendanceMarkRequest,
    db: AsyncSession = Depends(get_db),
):
    work_date = payload.work_date or payload.clock_in.date()

    existing = await db.execute(
        select(Attendance).where(
            Attendance.user_id == payload.user_id,
            Attendance.work_date == work_date,
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Attendance already marked for this employee on this date.")

    status = determine_status(payload.clock_in)
    total_hours = compute_hours(payload.clock_in, payload.clock_out)

    record = Attendance(
        id=uuid.uuid4(),
        user_id=payload.user_id,
        work_date=work_date,
        clock_in=payload.clock_in,
        clock_out=payload.clock_out,
        total_hours=total_hours,
        status=status,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


# CHECK OUT — update clock_out for an existing record
@router.patch("/{attendance_id}/checkout", response_model=AttendanceResponse, dependencies=[Depends(hr_and_admin)])
async def checkout_attendance(
    attendance_id: uuid.UUID,
    payload: AttendanceCheckoutRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    record = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found.")

    record.clock_out = payload.clock_out
    record.total_hours = compute_hours(record.clock_in, payload.clock_out)

    await db.commit()
    await db.refresh(record)
    return record


# LIST — filter by date and/or user
@router.get("/list", response_model=AttendanceListResponse, dependencies=[Depends(hr_and_admin)])
async def list_attendance(
    work_date: date | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Attendance)
    if work_date:
        query = query.where(Attendance.work_date == work_date)
    if user_id:
        query = query.where(Attendance.user_id == user_id)
    query = query.order_by(Attendance.work_date.desc(), Attendance.clock_in.desc())

    result = await db.execute(query)
    return {"items": result.scalars().all()}


# SUMMARY — present / absent / late for a given day (default today)
@router.get("/summary", response_model=AttendanceSummaryResponse, dependencies=[Depends(hr_and_admin)])
async def attendance_summary(
    work_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    target_date = work_date or date.today()

   
    total_result = await db.execute(
        select(User.id).where(
            User.status == "active",
            User.role == UserRole.USER,
        )
    )
    all_user_ids = {row[0] for row in total_result.all()}
    total_employees = len(all_user_ids)

    records_result = await db.execute(
        select(Attendance).where(Attendance.work_date == target_date)
    )
    records = records_result.scalars().all()

    present_ids = {r.user_id for r in records if r.status == AttendanceStatus.PRESENT and r.user_id in all_user_ids}
    half_day_ids = {r.user_id for r in records if r.status == AttendanceStatus.HALF_DAY and r.user_id in all_user_ids}
    marked_ids = present_ids | half_day_ids

    absent_ids = all_user_ids - marked_ids

    return {
        "date": target_date,
        "total_employees": total_employees,
        "present_today": len(present_ids),
        "absent_today": len(absent_ids),
        "late_arrivals": len(half_day_ids),
        "absent_user_ids": list(absent_ids),
    }

#update
@router.patch("/{attendance_id}", response_model=AttendanceResponse, dependencies=[Depends(hr_and_admin)])
async def update_attendance(
    attendance_id: uuid.UUID,
    payload: AttendanceUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Attendance).where(Attendance.id == attendance_id))
    record = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found.")

    update_data = payload.model_dump(exclude_unset=True)

    if "work_date" in update_data:
        record.work_date = update_data["work_date"]
    if "clock_in" in update_data:
        record.clock_in = update_data["clock_in"]
        record.status = determine_status(record.clock_in)   
    if "clock_out" in update_data:
        record.clock_out = update_data["clock_out"]

    if "clock_in" in update_data or "clock_out" in update_data:
        record.total_hours = compute_hours(record.clock_in, record.clock_out)

    await db.commit()
    await db.refresh(record)
    return record