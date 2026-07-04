from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from uuid import UUID
from typing import Optional
from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.user import BillRequest, BillStatus, User, UserRole
from app.schemas.bill import BillRequestCreate, BillReviewPayload, BillListResponse,BillSummaryResponse
import uuid


router = APIRouter(prefix="/bills", tags=["Bill Reimbursements"])

# SUBMIT BILL REQUEST (EVERYONE / USERS) 
@router.post("/request", status_code=status.HTTP_201_CREATED)
async def submit_bill_reimbursement(
    payload: BillRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    
    new_bill = BillRequest(
        user_id=caller_id,
        title=payload.title,
        amount=payload.amount,
        description=payload.description,
        attachment_url=payload.attachment_url,
        spent_date=payload.spent_date,
        status=BillStatus.PENDING
    )
    db.add(new_bill)
    await db.commit()
    return {"message": "Bill reimbursement request submitted successfully", "bill_id": new_bill.id}


#  PAGINATED BILL LIST (UNIFIED FOR USERS & ADMINS) 
@router.get("/list", response_model=BillListResponse)
async def list_bill_requests(
    status_filter: BillStatus | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    base_query = select(BillRequest).options(joinedload(BillRequest.user).joinedload(User.profile))

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        base_query = base_query.where(BillRequest.user_id == caller_id)

    if status_filter:
        base_query = base_query.where(BillRequest.status == status_filter)

    base_query = base_query.order_by(BillRequest.created_at.desc())

    subq = base_query.subquery()
    count_query = select(func.count()).select_from(subq)
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_result = await db.execute(base_query.offset(offset).limit(size))
    bills = fetch_result.scalars().all()

    formatted_items = []
    for bill in bills:
        profile = bill.user.profile if bill.user and bill.user.profile else None
        formatted_items.append({
            "id": bill.id,
            "user_id": bill.user_id,
            "title": bill.title,
            "amount": float(bill.amount),
            "description": bill.description,
            "attachment_url": bill.attachment_url,
            "status": bill.status,
            "created_at": bill.created_at,
            "user_details": {
                "id": bill.user.id,
                "email": bill.user.email,
                "first_name": profile.first_name if profile else None,
                "last_name": profile.last_name if profile else None,
            } if bill.user else None
        })

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": formatted_items
    }


# REVIEW BILL REQUEST (HR & ADMIN ONLY)
@router.patch("/review/{bill_id}", dependencies=[Depends(hr_and_admin)])
async def review_bill_request(
    bill_id: UUID,
    payload: BillReviewPayload,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(BillRequest).where(BillRequest.id == bill_id))
    bill = result.scalars().first()

    if not bill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target bill application record not found.")

    if bill.status != BillStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This bill has already been processed.")

    bill.status = payload.status
    await db.commit()
    return {"message": f"Bill status successfully updated to {payload.status.value}"}

#biil summary
@router.get("/summary", response_model=BillSummaryResponse)
async def get_bill_reimbursement_summary(
    target_user_id: Optional[uuid.UUID] = Query(None, description="HR/Admin can pass a specific user UUID to filter metrics"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
 
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    query = select(BillRequest.status, func.count(BillRequest.id))

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        query = query.where(BillRequest.user_id == caller_id)
    elif target_user_id:
        query = query.where(BillRequest.user_id == target_user_id)

    query = query.group_by(BillRequest.status)
    result = await db.execute(query)
    
    status_counts = {row[0]: row[1] for row in result.all()}

    pending_count = status_counts.get(BillStatus.PENDING, 0)
    approved_count = status_counts.get(BillStatus.APPROVED, 0)
    rejected_count = status_counts.get(BillStatus.REJECTED, 0)
    
    total_count = pending_count + approved_count + rejected_count

    return {
        "total": total_count,
        "pending": pending_count,
        "approved": approved_count,
        "rejected": rejected_count
    }