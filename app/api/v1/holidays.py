from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, extract
from uuid import UUID
from datetime import date

from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.user import Holiday
from app.schemas.holiday import HolidayCreate, HolidayUpdate, HolidayResponse

router = APIRouter(prefix="/holidays", tags=["Holiday Calendar"])

# CREATE HOLIDAY (HR & ADMIN)
@router.post("/create", response_model=HolidayResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(hr_and_admin)])
async def add_new_holiday(payload: HolidayCreate, db: AsyncSession = Depends(get_db)):

    conflict_check = await db.execute(select(Holiday).where(Holiday.holiday_date == payload.holiday_date))
    if conflict_check.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A holiday registration entry already exists for the date: {payload.holiday_date}"
        )

    new_holiday = Holiday(
        holiday_date=payload.holiday_date,
        name=payload.name,
        is_mandatory=payload.is_mandatory
    )
    db.add(new_holiday)
    await db.commit()
    await db.refresh(new_holiday)
    return new_holiday


# list 
@router.get("/list", response_model=dict)
async def get_holiday_calendar(
    year: int | None = Query(None, description="Filter holidays by a specific year (e.g., 2026)"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
 
    base_query = select(Holiday)

    if year:
        base_query = base_query.where(extract('year', Holiday.holiday_date) == year)

    base_query = base_query.order_by(Holiday.holiday_date.asc())

    count_query = select(func.count(Holiday.id)).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_result = await db.execute(base_query.offset(offset).limit(size))
    holidays = fetch_result.scalars().all()

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": holidays
    }


#  UPDATE HOLIDAY (HR & ADMIN) 
@router.patch("/update/{holiday_id}", response_model=HolidayResponse, dependencies=[Depends(hr_and_admin)])
async def modify_holiday_record(holiday_id: UUID, payload: HolidayUpdate, db: AsyncSession = Depends(get_db)):

    result = await db.execute(select(Holiday).where(Holiday.id == holiday_id))
    holiday = result.scalars().first()

    if not holiday:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target holiday record not found.")

    update_dict = payload.model_dump(exclude_unset=True)
    
    if "holiday_date" in update_dict and update_dict["holiday_date"] != holiday.holiday_date:
        conflict_check = await db.execute(select(Holiday).where(Holiday.holiday_date == update_dict["holiday_date"]))
        if conflict_check.scalars().first():
            raise HTTPException(status_code=400, detail="Another holiday event is already locked into that target date.")

    for key, value in update_dict.items():
        setattr(holiday, key, value)

    await db.commit()
    await db.refresh(holiday)
    return holiday


#  DELETE HOLIDAY (HR & ADMIN)
@router.delete("/delete/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(hr_and_admin)])
async def remove_holiday_record(holiday_id: UUID, db: AsyncSession = Depends(get_db)):

    result = await db.execute(select(Holiday).where(Holiday.id == holiday_id))
    holiday = result.scalars().first()

    if not holiday:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target holiday record not found.")

    await db.delete(holiday)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)