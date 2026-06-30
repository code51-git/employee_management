import logging
from uuid import UUID
from typing import Dict, List, Set
from fastapi import WebSocket

logger = logging.getLogger("chat_manager")

class ConnectionManager:
    def __init__(self):
        # Maps user_id -> List of active WebSockets
        self.active_connections: Dict[UUID, List[WebSocket]] = {}

    async def connect(self, user_id: UUID, websocket: WebSocket):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"⚡ Connection pool connected user: {user_id}")

    def disconnect(self, user_id: UUID, websocket: WebSocket):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"🔌 Connection pool disconnected user: {user_id}")

    async def send_personal_message(self, message: dict, user_id: UUID):
        """Dispatches an explicit payload directly to all sessions of a specific user."""
        connections = self.active_connections.get(user_id, [])
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                pass  # Handles stale connection dead drops gracefully

    async def broadcast_to_room(self, room_id: UUID, message: dict, member_ids: List[UUID]):
        """Multicasts updates instantly to all online room participants."""
        for member_id in member_ids:
            if member_id in self.active_connections:
                await self.send_personal_message(message, member_id)

manager = ConnectionManager()