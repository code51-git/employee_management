from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, update, delete
from typing import List, Optional
import uuid
from datetime import datetime

from app.core.database import get_db
from app.core.permissions import everyone, hr_and_admin
from app.models.user import User, UserProfile
from app.models.announcement import Announcement, AnnouncementRead, AnnouncementStatus, AnnouncementPriority
from app.schemas.announcement import (
    AnnouncementCreate, AnnouncementUpdate,
    AnnouncementResponse, AnnouncementListResponse
)
from app.core.notifications import send_multicast_push
from app.services.chat_manager import manager

router = APIRouter(prefix="/announcements", tags=["Announcements"])


#  Create Draft 

@router.post("", response_model=AnnouncementResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(hr_and_admin)])
async def create_announcement(
    payload: AnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(hr_and_admin)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    announcement = Announcement(
        id=uuid.uuid4(),
        title=payload.title,
        content=payload.content,
        priority=payload.priority,
        expires_at=payload.expires_at,
        status=AnnouncementStatus.DRAFT,
        created_by=caller_id
    )
    db.add(announcement)
    await db.commit()

    return {**announcement.__dict__, "is_read": False, "read_count": 0}


#  Publish Announcement 

@router.post("/{announcement_id}/publish", response_model=AnnouncementResponse, dependencies=[Depends(hr_and_admin)])
async def publish_announcement(
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(hr_and_admin)
):
    res = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    announcement = res.scalars().first()

    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")
    if announcement.status == AnnouncementStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Announcement is already published.")

    announcement.status = AnnouncementStatus.PUBLISHED
    announcement.published_at = datetime.utcnow()
    await db.commit()

    users_res = await db.execute(
        select(User.id, User.fcm_token).where(User.is_active == True)
    )
    all_users = users_res.all()
    all_user_ids = [row.id for row in all_users]
    fcm_tokens = [row.fcm_token for row in all_users if row.fcm_token]

    ws_payload = {
        "event": "new_announcement",
        "id": str(announcement.id),
        "title": announcement.title,
        "content": announcement.content,
        "priority": announcement.priority.value,
        "published_at": announcement.published_at.isoformat(),
        "expires_at": announcement.expires_at.isoformat() if announcement.expires_at else None,
    }
    for uid in all_user_ids:
        if uid in manager.active_connections:
            await manager.send_personal_message(ws_payload, uid)

    offline_tokens = [
        row.fcm_token for row in all_users
        if row.fcm_token and row.id not in manager.active_connections
    ]
    if offline_tokens:
        await send_multicast_push(
            tokens=offline_tokens,
            title=f"📢 {announcement.title}",
            body=announcement.content[:100],
            data={
                "event": "new_announcement",
                "announcement_id": str(announcement.id),
                "priority": announcement.priority.value,
            }
        )

    return {**announcement.__dict__, "is_read": False, "read_count": 0}


#  Update Announcement 

@router.patch("/{announcement_id}", response_model=AnnouncementResponse, dependencies=[Depends(hr_and_admin)])
async def update_announcement(
    announcement_id: uuid.UUID,
    payload: AnnouncementUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(hr_and_admin)
):
    res = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    announcement = res.scalars().first()

    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")

    if payload.title is not None:
        announcement.title = payload.title
    if payload.content is not None:
        announcement.content = payload.content
    if payload.priority is not None:
        announcement.priority = payload.priority
    if payload.expires_at is not None:
        announcement.expires_at = payload.expires_at

    announcement.updated_at = datetime.utcnow()
    await db.commit()

    if announcement.status == AnnouncementStatus.PUBLISHED:
        users_res = await db.execute(select(User.id).where(User.is_active == True))
        all_user_ids = users_res.scalars().all()
        for uid in all_user_ids:
            if uid in manager.active_connections:
                await manager.send_personal_message(
                    {
                        "event": "announcement_updated",
                        "id": str(announcement.id),
                        "title": announcement.title,
                        "content": announcement.content,
                        "priority": announcement.priority.value,
                    },
                    uid
                )

    read_count_res = await db.execute(
        select(func.count(AnnouncementRead.id)).where(AnnouncementRead.announcement_id == announcement_id)
    )
    read_count = read_count_res.scalar() or 0

    return {**announcement.__dict__, "is_read": False, "read_count": read_count}


#  Delete Announcement

@router.delete("/{announcement_id}", status_code=status.HTTP_200_OK, dependencies=[Depends(hr_and_admin)])
async def delete_announcement(
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(hr_and_admin)
):
    res = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    announcement = res.scalars().first()

    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")

    if announcement.status == AnnouncementStatus.PUBLISHED:
        users_res = await db.execute(select(User.id).where(User.is_active == True))
        all_user_ids = users_res.scalars().all()
        for uid in all_user_ids:
            if uid in manager.active_connections:
                await manager.send_personal_message(
                    {
                        "event": "announcement_deleted",
                        "id": str(announcement_id),
                    },
                    uid
                )

    await db.delete(announcement)
    await db.commit()
    return {"message": "Announcement deleted.", "announcement_id": announcement_id}


#  List Announcements (Admin) 

@router.get("/admin/all", response_model=AnnouncementListResponse, dependencies=[Depends(hr_and_admin)])
async def list_all_announcements(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    status: Optional[AnnouncementStatus] = Query(None),
    priority: Optional[AnnouncementPriority] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    query = select(Announcement)

    if status:
        query = query.where(Announcement.status == status)
    if priority:
        query = query.where(Announcement.priority == priority)

    count_res = await db.execute(select(func.count(Announcement.id)))
    total_count = count_res.scalar() or 0

    query = query.order_by(Announcement.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    announcements = result.scalars().all()

    announcement_ids = [a.id for a in announcements]
    read_counts_res = await db.execute(
        select(AnnouncementRead.announcement_id, func.count(AnnouncementRead.id).label("cnt"))
        .where(AnnouncementRead.announcement_id.in_(announcement_ids))
        .group_by(AnnouncementRead.announcement_id)
    )
    read_counts = {row.announcement_id: row.cnt for row in read_counts_res.all()}

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": [
            {**a.__dict__, "is_read": False, "read_count": read_counts.get(a.id, 0)}
            for a in announcements
        ]
    }


#  List Announcements (Employee) 

@router.get("", response_model=AnnouncementListResponse)
async def list_my_announcements(
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    priority: Optional[AnnouncementPriority] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))
    now = datetime.utcnow()

    query = select(Announcement).where(
        Announcement.status == AnnouncementStatus.PUBLISHED,
        (Announcement.expires_at.is_(None)) | (Announcement.expires_at > now)
    )

    if priority:
        query = query.where(Announcement.priority == priority)

    count_res = await db.execute(
        select(func.count(Announcement.id)).where(
            Announcement.status == AnnouncementStatus.PUBLISHED,
            (Announcement.expires_at.is_(None)) | (Announcement.expires_at > now)
        )
    )
    total_count = count_res.scalar() or 0

    query = query.order_by(Announcement.published_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    announcements = result.scalars().all()

    announcement_ids = [a.id for a in announcements]
    read_res = await db.execute(
        select(AnnouncementRead.announcement_id).where(
            AnnouncementRead.user_id == caller_id,
            AnnouncementRead.announcement_id.in_(announcement_ids)
        )
    )
    read_ids = set(read_res.scalars().all())

    read_counts_res = await db.execute(
        select(AnnouncementRead.announcement_id, func.count(AnnouncementRead.id).label("cnt"))
        .where(AnnouncementRead.announcement_id.in_(announcement_ids))
        .group_by(AnnouncementRead.announcement_id)
    )
    read_counts = {row.announcement_id: row.cnt for row in read_counts_res.all()}

    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "total_pages": (total_count + size - 1) // size if total_count > 0 else 0,
        "items": [
            {
                **a.__dict__,
                "is_read": a.id in read_ids,
                "read_count": read_counts.get(a.id, 0)
            }
            for a in announcements
        ]
    }


#  Mark as Read 

@router.post("/{announcement_id}/read", status_code=status.HTTP_200_OK)
async def mark_announcement_read(
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    res = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    if not res.scalars().first():
        raise HTTPException(status_code=404, detail="Announcement not found.")

    existing = await db.execute(
        select(AnnouncementRead).where(
            AnnouncementRead.announcement_id == announcement_id,
            AnnouncementRead.user_id == caller_id
        )
    )
    if not existing.scalars().first():
        db.add(AnnouncementRead(
            announcement_id=announcement_id,
            user_id=caller_id
        ))
        await db.commit()

    return {"message": "Marked as read.", "announcement_id": announcement_id}


#  Get Single Announcement 

@router.get("/{announcement_id}", response_model=AnnouncementResponse)
async def get_announcement(
    announcement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    res = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    announcement = res.scalars().first()

    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found.")

    read_res = await db.execute(
        select(AnnouncementRead).where(
            AnnouncementRead.announcement_id == announcement_id,
            AnnouncementRead.user_id == caller_id
        )
    )
    is_read = read_res.scalars().first() is not None

    read_count_res = await db.execute(
        select(func.count(AnnouncementRead.id))
        .where(AnnouncementRead.announcement_id == announcement_id)
    )
    read_count = read_count_res.scalar() or 0

    return {**announcement.__dict__, "is_read": is_read, "read_count": read_count}