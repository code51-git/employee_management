from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid
import json
from datetime import datetime

from app.core.database import get_db
from app.core.security import verify_jwt_token
from app.core.notifications import send_multicast_push
from app.services.chat_manager import manager
from app.models.chats import ChatMessage, room_members
from app.models.user import User, UserProfile

router = APIRouter(prefix="/ws", tags=["Live WebSocket Engine"])


@router.websocket("/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    # Validate token BEFORE accepting
    token_data = verify_jwt_token(token)
    if not token_data:
        await websocket.close(code=4001)
        return

    try:
        caller_id = uuid.UUID(token_data.get("sub"))
    except (ValueError, TypeError):
        await websocket.close(code=4001)
        return

    # Accept + register — only ONE accept here
    await manager.connect(caller_id, websocket)

    # Fetch sender profile once on connect
    profile_res = await db.execute(
        select(UserProfile).where(UserProfile.user_id == caller_id)
    )
    profile = profile_res.scalars().first()
    sender_name = f"{profile.first_name} {profile.last_name}" if profile else "Someone"

    try:
        while True:
            raw_data = await websocket.receive_text()
            payload = json.loads(raw_data)

            target_room_id = uuid.UUID(payload.get("room_id"))
            message_text = payload.get("content", "").strip()

            if not message_text:
                continue

            # Verify membership
            membership_res = await db.execute(
                select(room_members.c.user_id)
                .where(room_members.c.room_id == target_room_id)
            )
            room_member_ids = [row[0] for row in membership_res.all()]

            if caller_id not in room_member_ids:
                await websocket.send_json({
                    "event": "error",
                    "detail": "Forbidden: You are not a member of this room."
                })
                continue

            # Persist message
            new_msg = ChatMessage(
                id=uuid.uuid4(),
                room_id=target_room_id,
                sender_id=caller_id,
                content=message_text,
                created_at=datetime.utcnow()
            )
            db.add(new_msg)
            await db.commit()

            # Broadcast to online members
            await manager.broadcast_to_room(
                room_id=target_room_id,
                message={
                    "event": "message",
                    "id": str(new_msg.id),
                    "room_id": str(target_room_id),
                    "sender_id": str(caller_id),
                    "sender_name": sender_name,
                    "content": message_text,
                    "created_at": new_msg.created_at.isoformat()
                },
                member_ids=room_member_ids
            )

            # Push to offline members
            offline_ids = [
                mid for mid in room_member_ids
                if mid != caller_id and mid not in manager.active_connections
            ]
            if offline_ids:
                tokens_res = await db.execute(
                    select(User.fcm_token).where(
                        User.id.in_(offline_ids),
                        User.fcm_token.isnot(None)
                    )
                )
                fcm_tokens = [t for t in tokens_res.scalars().all() if t]
                if fcm_tokens:
                    await send_multicast_push(
                        tokens=fcm_tokens,
                        title=sender_name,
                        body=message_text[:100],
                        data={
                            "event": "new_message",
                            "room_id": str(target_room_id),
                            "sender_id": str(caller_id),
                            "message_id": str(new_msg.id),
                        }
                    )

    except WebSocketDisconnect:
        manager.disconnect(caller_id, websocket)
    except Exception as e:
        manager.disconnect(caller_id, websocket)