from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import insert, update, delete
from typing import List
import uuid
from datetime import datetime
from app.core.database import get_db
from app.core.permissions import everyone, hr_and_admin
from app.models.user import User, UserRole,UserProfile
from app.models.chats import ChatRoom, ChatMessage, ChatType, room_members, StarredMessage, MessageRead
from app.schemas.chat import (
    RoomCreate, MemberManage, BroadcastCreate,
    MessageResponse, RoomResponse,
    MarkReadResponse, ToggleStarResponse,
    StarredMessageDetailResponse, ClearChatResponse,
    DeleteMessageResponse
)
from app.services.chat_manager import manager
from sqlalchemy import func, or_
from typing import Optional
from sqlalchemy.orm import joinedload

router = APIRouter(prefix="/chat", tags=["Chat Administrative Controls"])



#basic user list
@router.get("/directory", status_code=status.HTTP_200_OK)
async def get_user_directory(
    search: Optional[str] = Query(None, description="Search by name"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    query = (
        select(User.id, UserProfile.first_name, UserProfile.last_name)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(User.id != caller_id) 
    )

    if search:
        search_term = f"%{search}%"
        query = query.where(
            (UserProfile.first_name.ilike(search_term)) |
            (UserProfile.last_name.ilike(search_term))
        )

    query = query.order_by(UserProfile.first_name.asc())
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "user_id": row.id,
            "full_name": f"{row.first_name} {row.last_name}",
        }
        for row in rows
    ]

# Create Room 
@router.post("/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
async def create_chat_room(
    payload: RoomCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))
    member_ids = list(set(payload.initial_member_ids))
    if caller_id not in member_ids:
        member_ids.append(caller_id)

    if payload.type == ChatType.DIRECT and len(member_ids) != 2:
        raise HTTPException(status_code=400, detail="Direct chats must contain exactly two participants.")

    # For direct chats, use the other person's name
    room_name = payload.name  # default for group
    if payload.type == ChatType.DIRECT:
        target_id = next(mid for mid in member_ids if mid != caller_id)
        profile_res = await db.execute(
            select(UserProfile).where(UserProfile.user_id == target_id)
        )
        profile = profile_res.scalars().first()
        if not profile:
            raise HTTPException(status_code=404, detail="Target user profile not found.")
        room_name = f"{profile.first_name} {profile.last_name}"

    new_room = ChatRoom(
        id=uuid.uuid4(),
        name=room_name,
        type=payload.type,
        created_by=caller_id
    )
    db.add(new_room)
    await db.flush()

    for m_id in member_ids:
        await db.execute(insert(room_members).values(
            room_id=new_room.id,
            user_id=m_id,
            is_admin=(m_id == caller_id and payload.type == ChatType.GROUP)
        ))

    await db.commit()
    return new_room

#get rooms
@router.get("/get/rooms", response_model=List[RoomResponse])
async def get_my_rooms(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    result = await db.execute(
        select(ChatRoom)
        .join(room_members, room_members.c.room_id == ChatRoom.id)
        .where(room_members.c.user_id == caller_id)
        .order_by(ChatRoom.created_at.desc())
    )
    rooms = result.scalars().all()

    if not rooms:
        return []

    room_ids = [r.id for r in rooms]
    direct_room_ids = [r.id for r in rooms if r.type == ChatType.DIRECT]

    other_members: dict = {}
    if direct_room_ids:
        other_res = await db.execute(
            select(room_members.c.room_id, room_members.c.user_id)
            .where(
                room_members.c.room_id.in_(direct_room_ids),
                room_members.c.user_id != caller_id
            )
        )
        other_rows = other_res.all()
        other_user_ids = [row.user_id for row in other_rows]

        if other_user_ids:
            profiles_res = await db.execute(
                select(UserProfile).where(UserProfile.user_id.in_(other_user_ids))
            )
            profiles = {
                p.user_id: f"{p.first_name} {p.last_name}"
                for p in profiles_res.scalars().all()
            }
            for row in other_rows:
                other_members[row.room_id] = profiles.get(row.user_id, "Unknown")

    
    from sqlalchemy import func
    latest_msg_subq = (
        select(
            ChatMessage.room_id,
            func.max(ChatMessage.created_at).label("max_created_at")
        )
        .where(ChatMessage.room_id.in_(room_ids))
        .group_by(ChatMessage.room_id)
        .subquery()
    )

    latest_msgs_res = await db.execute(
        select(ChatMessage)
        .join(
            latest_msg_subq,
            (ChatMessage.room_id == latest_msg_subq.c.room_id) &
            (ChatMessage.created_at == latest_msg_subq.c.max_created_at)
        )
    )
    latest_msgs = {msg.room_id: msg for msg in latest_msgs_res.scalars().all()}

    sender_ids = list(set(msg.sender_id for msg in latest_msgs.values()))
    sender_profiles: dict = {}
    if sender_ids:
        sender_res = await db.execute(
            select(UserProfile).where(UserProfile.user_id.in_(sender_ids))
        )
        sender_profiles = {
            p.user_id: f"{p.first_name} {p.last_name}"
            for p in sender_res.scalars().all()
        }

    return [
        {
            "id": room.id,
            "name": other_members.get(room.id) if room.type == ChatType.DIRECT else room.name,
            "type": room.type,
            "created_at": room.created_at,
            "created_by": room.created_by,
            "latest_message": latest_msgs[room.id].content if room.id in latest_msgs else None,
            "latest_message_at": latest_msgs[room.id].created_at if room.id in latest_msgs else None,
            "latest_message_by": sender_profiles.get(latest_msgs[room.id].sender_id) if room.id in latest_msgs else None,
        }
        for room in rooms
    ]

#Get or Create Direct Room 

@router.post("/rooms/direct", response_model=RoomResponse)
async def get_or_create_direct_room(
    target_user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    """Returns existing direct room between two users, or creates one."""
    caller_id = uuid.UUID(current_user.get("sub"))

    if caller_id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot create a direct chat with yourself.")

    # Fetch target user's name
    profile_res = await db.execute(
        select(UserProfile).where(UserProfile.user_id == target_user_id)
    )
    profile = profile_res.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Target user profile not found.")
    
    target_name = f"{profile.first_name} {profile.last_name}"

    existing = await db.execute(
        select(ChatRoom)
        .join(room_members, room_members.c.room_id == ChatRoom.id)
        .where(
            ChatRoom.type == ChatType.DIRECT,
            room_members.c.user_id == caller_id
        )
        .where(
            ChatRoom.id.in_(
                select(room_members.c.room_id)
                .where(room_members.c.user_id == target_user_id)
            )
        )
    )
    room = existing.scalars().first()
    if room:
        # Update name in case it changed
        room.name = target_name
        await db.commit()
        return room

    new_room = ChatRoom(
        id=uuid.uuid4(),
        type=ChatType.DIRECT,
        created_by=caller_id,
        name=target_name  # ← store target user's full name
    )
    db.add(new_room)
    await db.flush()

    for uid in [caller_id, target_user_id]:
        await db.execute(insert(room_members).values(
            room_id=new_room.id,
            user_id=uid,
            is_admin=False
        ))

    await db.commit()
    return new_room


# Add Members to Group 

@router.post("/rooms/{room_id}/members", status_code=status.HTTP_200_OK)
async def add_members_to_group(
    room_id: uuid.UUID,
    payload: MemberManage,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    room_res = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = room_res.scalars().first()
    if not room or room.type != ChatType.GROUP:
        raise HTTPException(status_code=404, detail="Target group chat room not found.")

    admin_check = await db.execute(
        select(room_members).where(
            room_members.c.room_id == room_id,
            room_members.c.user_id == caller_id,
            room_members.c.is_admin == True
        )
    )
    if not admin_check.first() and current_user.get("role") not in [UserRole.SUPER_ADMIN.value, UserRole.HR_ADMIN.value]:
        raise HTTPException(status_code=403, detail="Permission Denied: You do not manage this group channel.")

    for target_u_id in payload.user_ids:
        existing = await db.execute(
            select(room_members).where(
                room_members.c.room_id == room_id,
                room_members.c.user_id == target_u_id
            )
        )
        if not existing.first():
            await db.execute(insert(room_members).values(
                room_id=room_id,
                user_id=target_u_id,
                is_admin=False
            ))

    await db.commit()
    return {"message": "Selected members successfully added to the group."}


# Get Message History 
@router.get("/rooms/{room_id}/messages", response_model=List[MessageResponse])
async def get_room_message_history(
    room_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    membership = await db.execute(
        select(room_members).where(
            room_members.c.room_id == room_id,
            room_members.c.user_id == caller_id
        )
    )
    member_row = membership.first()
    if not member_row:
        raise HTTPException(status_code=403, detail="Access Denied: You are not a member of this room.")

    cleared_at = member_row.cleared_at

    query = select(ChatMessage).where(ChatMessage.room_id == room_id)
    if cleared_at:
        query = query.where(ChatMessage.created_at > cleared_at)

    query = query.order_by(ChatMessage.created_at.desc()).limit(limit)
    msg_res = await db.execute(query)
    messages = sorted(msg_res.scalars().all(), key=lambda x: x.created_at)

    if not messages:
        return []

    # Fetch all sender profiles in one query
    sender_ids = list(set(msg.sender_id for msg in messages))
    profiles_res = await db.execute(
        select(UserProfile).where(UserProfile.user_id.in_(sender_ids))
    )
    profiles = {p.user_id: f"{p.first_name} {p.last_name}" for p in profiles_res.scalars().all()}

    # Fetch read receipts for current user
    read_res = await db.execute(
        select(MessageRead.message_id).where(
            MessageRead.user_id == caller_id,
            MessageRead.message_id.in_([msg.id for msg in messages])
        )
    )
    read_ids = set(read_res.scalars().all())

    # Fetch starred messages for current user
    starred_res = await db.execute(
        select(StarredMessage.message_id).where(
            StarredMessage.user_id == caller_id,
            StarredMessage.message_id.in_([msg.id for msg in messages])
        )
    )
    starred_ids = set(starred_res.scalars().all())

    return [
        {
            "id": msg.id,
            "room_id": msg.room_id,
            "sender_id": msg.sender_id,
            "sender_name": profiles.get(msg.sender_id, "Unknown"),
            "content": msg.content,
            "created_at": msg.created_at,
            "is_read": msg.id in read_ids,
            "is_starred": msg.id in starred_ids,
        }
        for msg in messages
    ]


#  Admin Broadcast 

@router.post("/broadcast", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(hr_and_admin)])
async def execute_admin_broadcast(
    payload: BroadcastCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(hr_and_admin)
):
    caller_id = uuid.UUID(current_user.get("sub"))
    target_user_ids = (
        payload.recipient_ids if payload.recipient_ids
        else (await db.execute(select(User.id).where(User.id != caller_id))).scalars().all()
    )

    broadcast_room = ChatRoom(
        id=uuid.uuid4(),
        name=payload.title,
        type=ChatType.GROUP,
        created_by=caller_id
    )
    db.add(broadcast_room)
    await db.flush()

    await db.execute(insert(room_members).values(
        room_id=broadcast_room.id,
        user_id=caller_id,
        is_admin=True
    ))

    broadcast_msg = ChatMessage(
        id=uuid.uuid4(),
        room_id=broadcast_room.id,
        sender_id=caller_id,
        content=payload.message_text
    )
    db.add(broadcast_msg)

    for recipient_id in target_user_ids:
        await db.execute(insert(room_members).values(
            room_id=broadcast_room.id,
            user_id=recipient_id,
            is_admin=False
        ))

    await db.commit()

    await manager.broadcast_to_room(
        room_id=broadcast_room.id,
        message={
            "event": "broadcast_notice",
            "room_id": str(broadcast_room.id),
            "title": payload.title,
            "content": payload.message_text
        },
        member_ids=list(target_user_ids)
    )
    return {"message": "Broadcast sent.", "broadcast_room_id": broadcast_room.id}


#  Mark Messages as Read 

@router.post("/rooms/{room_id}/read", response_model=MarkReadResponse, status_code=status.HTTP_200_OK)
async def mark_room_messages_as_read(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    membership = await db.execute(
        select(room_members).where(
            room_members.c.room_id == room_id,
            room_members.c.user_id == caller_id
        )
    )
    if not membership.first():
        raise HTTPException(status_code=403, detail="Access Denied: You are not a member of this room.")

    already_read = select(MessageRead.message_id).where(MessageRead.user_id == caller_id)
    unread_msgs = await db.execute(
        select(ChatMessage.id).where(
            ChatMessage.room_id == room_id,
            ChatMessage.sender_id != caller_id,
            ChatMessage.id.not_in(already_read)
        )
    )
    unread_ids = unread_msgs.scalars().all()

    for msg_id in unread_ids:
        db.add(MessageRead(message_id=msg_id, user_id=caller_id))

    await db.commit()

    members_res = await db.execute(
        select(room_members.c.user_id).where(room_members.c.room_id == room_id)
    )
    all_member_ids = [mid for mid in members_res.scalars().all() if mid != caller_id]

    await manager.broadcast_to_room(
        room_id=room_id,
        message={
            "event": "read_receipt",
            "room_id": str(room_id),
            "read_by": str(caller_id),
            "message_ids": [str(i) for i in unread_ids]
        },
        member_ids=all_member_ids
    )

    return {"message": "Messages marked as read.", "marked_count": len(unread_ids)}


#  Star / Unstar Message 

@router.post("/messages/{message_id}/star", response_model=ToggleStarResponse, status_code=status.HTTP_200_OK)
async def toggle_star_message(
    message_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    msg_res = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    if not msg_res.scalars().first():
        raise HTTPException(status_code=404, detail="Message not found.")

    existing = await db.execute(
        select(StarredMessage).where(
            StarredMessage.message_id == message_id,
            StarredMessage.user_id == caller_id
        )
    )
    star = existing.scalars().first()

    if star:
        await db.delete(star)
        await db.commit()
        return {"message": "Message unstarred.", "starred": False, "message_id": message_id}

    db.add(StarredMessage(message_id=message_id, user_id=caller_id))
    await db.commit()
    return {"message": "Message starred.", "starred": True, "message_id": message_id}


# Get Starred Messages 

@router.get("/messages/starred", response_model=List[StarredMessageDetailResponse], status_code=status.HTTP_200_OK)
async def get_starred_messages(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    result = await db.execute(
        select(ChatMessage, StarredMessage.starred_at)
        .join(StarredMessage, StarredMessage.message_id == ChatMessage.id)
        .where(StarredMessage.user_id == caller_id)
        .order_by(StarredMessage.starred_at.desc())
    )
    rows = result.all()

    return [
        {
            "id": row.ChatMessage.id,
            "room_id": row.ChatMessage.room_id,
            "sender_id": row.ChatMessage.sender_id,
            "content": row.ChatMessage.content,
            "created_at": row.ChatMessage.created_at,
            "starred_at": row.starred_at,
        }
        for row in rows
    ]


# Clear Chat (per user only)

@router.post("/rooms/{room_id}/clear", response_model=ClearChatResponse, status_code=status.HTTP_200_OK)
async def clear_chat_for_user(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    membership = await db.execute(
        select(room_members).where(
            room_members.c.room_id == room_id,
            room_members.c.user_id == caller_id
        )
    )
    if not membership.first():
        raise HTTPException(status_code=403, detail="Access Denied: You are not a member of this room.")

    cleared_time = datetime.utcnow()

    await db.execute(
        update(room_members)
        .where(
            room_members.c.room_id == room_id,
            room_members.c.user_id == caller_id
        )
        .values(cleared_at=cleared_time)
    )
    await db.commit()
    return {"message": "Chat cleared successfully.", "cleared_at": cleared_time}


#  Delete Message (hard delete, sender only) 

@router.delete("/messages/{message_id}", response_model=DeleteMessageResponse, status_code=status.HTTP_200_OK)
async def delete_message(
    message_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(everyone)
):
    caller_id = uuid.UUID(current_user.get("sub"))

    msg_res = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    message = msg_res.scalars().first()

    if not message:
        raise HTTPException(status_code=404, detail="Message not found.")

    if message.sender_id != caller_id:
        raise HTTPException(status_code=403, detail="Permission Denied: You can only delete your own messages.")

    room_id = message.room_id

    members_res = await db.execute(
        select(room_members.c.user_id).where(room_members.c.room_id == room_id)
    )
    member_ids = members_res.scalars().all()

    await db.delete(message)
    await db.commit()

    await manager.broadcast_to_room(
        room_id=room_id,
        message={
            "event": "message_deleted",
            "room_id": str(room_id),
            "message_id": str(message_id)
        },
        member_ids=member_ids
    )

    return {"message": "Message permanently deleted.", "message_id": message_id}