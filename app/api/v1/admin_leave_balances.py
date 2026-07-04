from fastapi import APIRouter, Depends, HTTPException, status, Query,Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from uuid import UUID, uuid4
from typing import List, Optional

from app.core.database import get_db
from app.core.permissions import hr_and_admin
from app.models.user import EmployeeLeaveBalance, User

router = APIRouter(prefix="/admin/leave-balances", tags=["Admin Leave Balance Control"], dependencies=[Depends(hr_and_admin)])


# ADD / INITIALIZE BALANCE FOR AN EMPLOYEE
@router.post("/create", status_code=status.HTTP_201_CREATED)
async def admin_create_leave_balance(
    user_id: UUID,
    year: int = 2026,
    casual_leaves: float = 6.0,
    sick_leaves: float = 12.0,
    db: AsyncSession = Depends(get_db)
):
    user_exists = await db.execute(select(User).where(User.id == user_id))
    if not user_exists.scalars().first():
        raise HTTPException(status_code=404, detail="Employee not found.")

    existing = await db.execute(
        select(EmployeeLeaveBalance).where(
            EmployeeLeaveBalance.user_id == user_id, 
            EmployeeLeaveBalance.year == year
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail=f"Leave balance record already exists for this employee for the year {year}.")

    new_balance = EmployeeLeaveBalance(
        id=uuid4(),
        user_id=user_id,
        year=year,
        casual_leaves_remaining=casual_leaves,
        sick_leaves_remaining=sick_leaves
    )
    db.add(new_balance)
    await db.commit()
    
    return {"message": "Employee leave balance record initialized successfully.", "balance_id": new_balance.id}


# LIST ALL EMPLOYEE LEAVE BALANCES
@router.get("/list")
async def admin_list_leave_balances(
    year: Optional[int] = 2026,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(EmployeeLeaveBalance)
        .options(joinedload(EmployeeLeaveBalance.user).joinedload(User.profile))
        .where(EmployeeLeaveBalance.year == year)
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(query)
    balances = result.scalars().all()

    return [
        {
            "balance_id": b.id,
            "user_id": b.user_id,
            "employee_id": b.user.profile.employee_id if b.user and b.user.profile else "N/A",
            "employee_name": f"{b.user.profile.first_name} {b.user.profile.last_name}" if b.user and b.user.profile else "Unknown",
            "year": b.year,
            "casual_leaves_remaining": float(b.casual_leaves_remaining),
            "sick_leaves_remaining": float(b.sick_leaves_remaining)
        }
        for b in balances
    ]

#  UPDATE / ADJUST A SPECIFIC BALANCE RECORD
@router.patch("/update/{balance_id}")
async def admin_update_leave_balance(
    balance_id: UUID,
    casual_leaves_remaining: Optional[float] = Body(None),  
    sick_leaves_remaining: Optional[float] = Body(None),   
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(EmployeeLeaveBalance).where(EmployeeLeaveBalance.id == balance_id))
    balance_record = result.scalars().first()

    if not balance_record:
        raise HTTPException(status_code=404, detail="Leave balance ledger record not found.")

    if casual_leaves_remaining is not None:
        if casual_leaves_remaining < 0:
            raise HTTPException(status_code=400, detail="Casual leaves balance cannot be negative.")
        balance_record.casual_leaves_remaining = casual_leaves_remaining

    if sick_leaves_remaining is not None:
        if sick_leaves_remaining < 0:
            raise HTTPException(status_code=400, detail="Sick leaves balance cannot be negative.")
        balance_record.sick_leaves_remaining = sick_leaves_remaining

    await db.commit()
    await db.refresh(balance_record)

    return {
        "message": "Employee leave balance record updated successfully.",
        "balance_id": balance_record.id,
        "casual_leaves_remaining": float(balance_record.casual_leaves_remaining),
        "sick_leaves_remaining": float(balance_record.sick_leaves_remaining)
    }

#delete
@router.delete("/delete/{balance_id}", status_code=status.HTTP_200_OK)
async def admin_delete_leave_balance(
    balance_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(EmployeeLeaveBalance).where(EmployeeLeaveBalance.id == balance_id))
    balance_record = result.scalars().first()

    if not balance_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Target leave balance ledger record not found."
        )

    await db.delete(balance_record)
    await db.commit()

    return {"message": "Employee leave balance record has been permanently removed from the ledger."}