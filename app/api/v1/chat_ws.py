from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid
import json
from datetime import datetime

from app.core.database import get_db
from app.core.security import verify_jwt_token
from app.services.chat_manager import manager
from app.models.chats import ChatMessage, room_members

router = APIRouter(prefix="/ws", tags=["Live WebSocket Engine"])

@router.websocket("/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT authentication token query parameter string"),
    db: AsyncSession = Depends(get_db)
):
    # 1. Accept the handshake immediately so we have an open communication channel
    await websocket.accept()
    
    # 2. Extract and decode the token payload metrics
    token_data = verify_jwt_token(token)
    
    if not token_data:
        # Send a clear message so the frontend knows exactly what went wrong
        await websocket.send_json({
            "event": "auth_error",
            "detail": "Authentication Failed: Token is either invalid or has expired."
        })
        await websocket.close(code=4001)
        return

    try:
        caller_id = uuid.UUID(token_data.get("sub"))
    except (ValueError, TypeError):
        await websocket.send_json({
            "event": "auth_error",
            "detail": "Authentication Failed: Invalid user signature format inside token."
        })
        await websocket.close(code=4001)
        return

    # 3. Register the connection into the active memory pool
    from app.services.chat_manager import manager
    if caller_id not in manager.active_connections:
        manager.active_connections[caller_id] = []
    manager.active_connections[caller_id].append(websocket)
    print(f"🔌 WebSocket session opened successfully for user: {caller_id}")

    try:
        while True:
            raw_data = await websocket.receive_text()
            payload = json.loads(raw_data)
            
            target_room_id = uuid.UUID(payload.get("room_id"))
            message_text = payload.get("content", "").strip()

            if not message_text:
                continue

            # Verify the user belongs to the target room context mapping
            membership_res = await db.execute(
                select(room_members.c.user_id).where(room_members.c.room_id == target_room_id)
            )
            room_member_ids = [row[0] for row in membership_res.all()]

            if caller_id not in room_member_ids:
                await websocket.send_json({"event": "error", "detail": "Forbidden: You are not a member of this room."})
                continue

            # Persist incoming message to PostgreSQL
            new_msg = ChatMessage(
                id=uuid.uuid4(),
                room_id=target_room_id,
                sender_id=caller_id,
                content=message_text,
                created_at=datetime.utcnow()
            )
            db.add(new_msg)
            await db.commit()

            # Broadcast update payload to all active listeners in the room
            await manager.broadcast_to_room(
                room_id=target_room_id,
                message={
                    "event": "message",
                    "id": str(new_msg.id),
                    "room_id": str(target_room_id),
                    "sender_id": str(caller_id),
                    "content": message_text,
                    "created_at": new_msg.created_at.isoformat()
                },
                member_ids=room_member_ids
            )

    except WebSocketDisconnect:
        manager.disconnect(caller_id, websocket)
    except Exception:
        manager.disconnect(caller_id, websocket)


@router.get("/test")
async def ws_test():
    return {"status": "ws router is mounted"}