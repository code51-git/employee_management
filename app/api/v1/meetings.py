from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks,Query,Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.core.database import get_db
from app.core.permissions import hr_and_admin, everyone
from app.models.user import Meeting, User,UserRole
from app.schemas.meeting import MeetingCreate, MeetingResponse,MeetingUpdate,MeetingListResponse
from app.services.notification import send_multicast_meeting_notification
from datetime import date
from uuid import UUID

router = APIRouter(prefix="/meetings", tags=["Meeting Management"])

#create
@router.post("/schedule", response_model=MeetingResponse, dependencies=[Depends(hr_and_admin)])
async def schedule_new_meeting(
    payload: MeetingCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(hr_and_admin)
):

    organizer_id = current_user.get("sub")

    new_meeting = Meeting(
        title=payload.title,
        description=payload.description,
        meeting_date=payload.meeting_date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        meeting_link=payload.meeting_link,
        organizer_id=organizer_id,
        attendee_ids=payload.attendee_ids
    )
    db.add(new_meeting)
    await db.commit()
    await db.refresh(new_meeting)


    result = await db.execute(
        select(User.id).where(User.id.in_(payload.attendee_ids)) 
    )

    dummy_mock_tokens = ["fcm_token_sample_1", "fcm_token_sample_2"] 

    notification_details = f"Scheduled for {payload.meeting_date} at {payload.start_time.strftime('%I:%M %p')}"
    background_tasks.add_task(
        send_multicast_meeting_notification,
        tokens=dummy_mock_tokens,
        title=payload.title,
        details=notification_details
    )

    return new_meeting

#list
@router.get("/list", response_model=MeetingListResponse)
async def get_meetings_directory(
    filter_type: str = Query("upcoming", regex="^(upcoming|past)$"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
 
    caller_id = current_user.get("sub")
    caller_role = current_user.get("role")
    today = date.today()

    # Base query assembly
    base_query = select(Meeting)

    # Context A: Scope down queries for regular employees
    if caller_role not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        # Checks if caller_id is contained within the attendee_ids array column
        base_query = base_query.where(Meeting.attendee_ids.any(caller_id))

    # Context B: Apply chronological timeline filter checks
    if filter_type == "upcoming":
        base_query = base_query.where(Meeting.meeting_date >= today).order_by(Meeting.meeting_date.asc(), Meeting.start_time.asc())
    else:
        base_query = base_query.where(Meeting.meeting_date < today).order_by(Meeting.meeting_date.desc(), Meeting.start_time.desc())

    # Calculate count matrix
    count_query = select(func.count(Meeting.id)).select_from(base_query.subquery())
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0

    # Fetch targeted chunk offset
    offset = (page - 1) * size
    fetch_result = await db.execute(base_query.offset(offset).limit(size))
    meetings = fetch_result.scalars().all()

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": meetings
    }


# UPDATE MEETING DETAILS 
@router.patch("/update/{meeting_id}", response_model=MeetingResponse, dependencies=[Depends(hr_and_admin)])
async def update_scheduled_meeting(
    meeting_id: UUID,
    payload: MeetingUpdate,
    db: AsyncSession = Depends(get_db)
):

    result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    meeting = result.scalars().first()

    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting target record not found.")

    update_dict = payload.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(meeting, key, value)

    await db.commit()
    await db.refresh(meeting)
    return meeting


#DELETE/CANCEL MEETING 
@router.delete("/cancel/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(hr_and_admin)])
async def cancel_and_delete_meeting(
    meeting_id: UUID,
    db: AsyncSession = Depends(get_db)
):
  
    result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    meeting = result.scalars().first()

    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting target record not found.")

    await db.delete(meeting)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)