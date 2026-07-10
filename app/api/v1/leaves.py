from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks,Form,UploadFile,File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from uuid import UUID
from datetime import date
from app.services.email import send_leave_status_email
from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.user import Leave, LeaveStatus, User, UserRole,EmployeeLeaveBalance,AdvanceSalaryRequest
from app.schemas.leave import LeaveRequestCreate, LeaveReviewPayload, LeaveResponse,LeaveListResponse,LeaveSummaryResponse
import re
from typing import Optional
import uuid
import os
import aioboto3


router = APIRouter(prefix="/leaves", tags=["Leave Management"])

# SUBMIT LEAVE REQUEST 
@router.post("/request", status_code=status.HTTP_201_CREATED)
async def submit_leave_request(
    leave_type: str = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    reason: str = Form(...),
    file: UploadFile = File(None), 
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="Start date cannot fall after end date.")
        
    calculated_days = (end_date - start_date).days + 1
    duration_str = f"{calculated_days} days" if calculated_days > 1 else f"{calculated_days} day"

    final_public_url = None

    if file:
        cf_account_id = os.getenv("CF_R2_ACCOUNT_ID")
        cf_access_key = os.getenv("CF_R2_ACCESS_KEY_ID")
        cf_secret_key = os.getenv("CF_R2_SECRET_ACCESS_KEY")
        cf_bucket_name = os.getenv("CF_R2_BUCKET_NAME")
        cf_public_url = os.getenv("CF_R2_PUBLIC_URL")

        if not all([cf_account_id, cf_access_key, cf_secret_key, cf_bucket_name, cf_public_url]):
            raise HTTPException(status_code=500, detail="Cloud storage configuration missing.")

        file_extension = os.path.splitext(file.filename)[1]
        leave_id = uuid.uuid4() 
        unique_key = f"leaves/{caller_id}/{leave_id}{file_extension}"
        r2_endpoint_url = f"https://{cf_account_id}.r2.cloudflarestorage.com"

        file_data = await file.read()
        session = aioboto3.Session()
        
        async with session.client(
            "s3",
            endpoint_url=r2_endpoint_url,
            aws_access_key_id=cf_access_key,
            aws_secret_access_key=cf_secret_key,
        ) as s3_client:
            try:
                await s3_client.put_object(
                    Bucket=cf_bucket_name,
                    Key=unique_key,
                    Body=file_data,
                    ContentType=file.content_type
                )
                final_public_url = f"{cf_public_url}/{unique_key}"
            except Exception as cloud_err:
                raise HTTPException(status_code=500, detail=f"Document upload failed: {str(cloud_err)}")
    else:
        leave_id = uuid.uuid4()

    new_leave = Leave(
        id=leave_id,
        user_id=caller_id,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        duration_days=duration_str,
        reason=reason,
        status=LeaveStatus.PENDING,
        leave_document_url=final_public_url
    )
    
    db.add(new_leave)
    await db.commit()
    await db.refresh(new_leave)
    
    return new_leave


#  PAGINATED LEAVE HISTORY  
@router.get("/list", response_model=LeaveListResponse)
async def list_leave_requests(
    status_filter: LeaveStatus | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    base_query = (
        select(Leave)
        .options(
            joinedload(Leave.user)
            .joinedload(User.profile)
        )
    )

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        base_query = base_query.where(Leave.user_id == caller_id)
        
    if status_filter:
        base_query = base_query.where(Leave.status == status_filter)

    base_query = base_query.order_by(Leave.start_date.desc())

    count_query = select(func.count(Leave.id)).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * size
    fetch_result = await db.execute(base_query.offset(offset).limit(size))
    leaves = fetch_result.scalars().all()


    formatted_items = []
    for leave in leaves:
        profile = leave.user.profile if leave.user and leave.user.profile else None
        formatted_items.append({
            "id": leave.id,
            "user_id": leave.user_id,
            "duration_days": leave.duration_days,
            "leave_type": leave.leave_type,
            "start_date": leave.start_date,
            "end_date": leave.end_date,
            "reason": leave.reason,
            "document":leave.leave_document_url,
            "status": leave.status,
            "user_details": {
                "id": leave.user.id,
                "email": leave.user.email,
                "first_name": profile.first_name if profile else None,
                "last_name": profile.last_name if profile else None,
                "employee_id": profile.employee_id if profile else None,
            } if leave.user else None
        })

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": formatted_items
    }


# LEAVE REVIEW PROCESS 
@router.patch("/review/{leave_id}", response_model=LeaveResponse, dependencies=[Depends(hr_and_admin)])
async def review_employee_leave(
    leave_id: UUID,
    payload: LeaveReviewPayload,
    background_tasks: BackgroundTasks, 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Leave)
        .options(joinedload(Leave.user).joinedload(User.profile))
        .where(Leave.id == leave_id)
    )
    leave_record = result.scalars().first()

    if not leave_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Target leave application instance not found."
        )

    if leave_record.status != LeaveStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This application has already been processed and is marked as: {leave_record.status.value}"
        )

    if payload.status == LeaveStatus.APPROVED:
        match = re.search(r'\d+(\.\d+)?', leave_record.duration_days)
        requested_days = float(match.group()) if match else 1.0

        balance_result = await db.execute(
            select(EmployeeLeaveBalance).where(EmployeeLeaveBalance.user_id == leave_record.user_id)
        )
        balances = balance_result.scalars().first()
        
        if not balances:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Leave balance ledger record missing for this user."
            )

        leave_type_lower = leave_record.leave_type.lower()

        if "casual" in leave_type_lower:
            cl_to_deduct = min(requested_days, 0.5)

            if float(balances.casual_leaves_remaining) < cl_to_deduct:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient Casual Leave balance. Available: {balances.casual_leaves_remaining} days."
                )
            
            balances.casual_leaves_remaining = float(balances.casual_leaves_remaining) - cl_to_deduct

        elif "sick" in leave_type_lower or "medical" in leave_type_lower:
            if float(balances.sick_leaves_remaining) < requested_days:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient Sick Leave balance. Available: {balances.sick_leaves_remaining} days."
                )
            balances.sick_leaves_remaining = float(balances.sick_leaves_remaining) - requested_days

    leave_record.status = payload.status
    await db.commit()
    await db.refresh(leave_record)

    # Email worker notifications code...
    user_obj = leave_record.user
    profile_obj = user_obj.profile if user_obj else None
    recipient_email = user_obj.email if user_obj else None
    first_name = profile_obj.first_name if profile_obj else "Employee"
    last_name = profile_obj.last_name if profile_obj else ""
    full_name = f"{first_name} {last_name}".strip()

    if recipient_email:
        background_tasks.add_task(
            send_leave_status_email,
            recipient_email=recipient_email,
            employee_name=full_name,
            leave_type=leave_record.leave_type,
            start_date=str(leave_record.start_date),
            end_date=str(leave_record.end_date),
            review_status=payload.status.value 
        )

    return leave_record


#leave summary
@router.get("/employee-summary")
async def get_employee_dashboard_summary(
    current_user: dict = Depends(everyone),
    db: AsyncSession = Depends(get_db)
):
    user_id = current_user.get("sub")

    balance_result = await db.execute(
        select(EmployeeLeaveBalance).where(EmployeeLeaveBalance.user_id == user_id)
    )
    balances = balance_result.scalars().first()

    advance_result = await db.execute(
        select(AdvanceSalaryRequest).where(AdvanceSalaryRequest.user_id == user_id)
    )
    advances = advance_result.scalars().all()

    return {
        "leave_balances": {
            "casual_leaves_remaining": float(balances.casual_leaves_remaining) if balances else 6.0,
            "sick_leaves_remaining": float(balances.sick_leaves_remaining) if balances else 12.0,
            "year": balances.year if balances else 2026
        },
        "advance_requests": [
            {
                "id": adv.id,
                "amount": float(adv.amount_requested),
                "target_month": adv.target_repayment_month,
                "status": adv.status
            }
            for adv in advances
        ]
    }


#leave summary
@router.get("/summary", response_model=LeaveSummaryResponse)
async def get_leave_summary_metrics(
    target_user_id: Optional[uuid.UUID] = Query(None, description="HR/Admin can pass a specific user UUID to filter metrics"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):

    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")

    query = select(Leave.status, func.count(Leave.id))

    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        query = query.where(Leave.user_id == caller_id)
    elif target_user_id:
        query = query.where(Leave.user_id == target_user_id)

    query = query.group_by(Leave.status)
    result = await db.execute(query)
    
    status_counts = {row[0]: row[1] for row in result.all()}

    pending_count = status_counts.get(LeaveStatus.PENDING, 0)
    approved_count = status_counts.get(LeaveStatus.APPROVED, 0)
    rejected_count = status_counts.get(LeaveStatus.REJECTED, 0)
    
    total_count = pending_count + approved_count + rejected_count

    return {
        "total": total_count,
        "pending": pending_count,
        "approved": approved_count,
        "rejected": rejected_count
    }