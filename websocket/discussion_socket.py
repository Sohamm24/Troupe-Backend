"""
websocket/discussion_socket.py
------------------------------
WebSocket endpoint for real-time discussion forums.

Events:
  - message.sent
  - message.edited
  - message.deleted
  - user.joined
  - user.left
  - typing.started
  - typing.stopped
"""

import json
import logging
from typing import Dict, Set

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from core.database import SessionLocal
from models.discussion import Discussion, Message
from core.security import decode_token

logger = logging.getLogger("travel_platform")


class ConnectionManager:
    """Manages active WebSocket connections per discussion room."""

    def __init__(self):
        # discussion_id -> set of WebSocket connections
        self.rooms: Dict[str, Set[WebSocket]] = {}
        # websocket -> user info
        self.user_info: Dict[WebSocket, dict] = {}

    async def connect(self, websocket: WebSocket, discussion_id: str, user_info: dict):
        await websocket.accept()
        if discussion_id not in self.rooms:
            self.rooms[discussion_id] = set()
        self.rooms[discussion_id].add(websocket)
        self.user_info[websocket] = user_info

        # Broadcast user.joined event
        await self.broadcast(discussion_id, {
            "event": "user.joined",
            "data": {
                "user_id": user_info.get("user_id"),
                "name": user_info.get("name"),
            },
        }, exclude=websocket)

    async def disconnect(self, websocket: WebSocket, discussion_id: str):
        if discussion_id in self.rooms:
            self.rooms[discussion_id].discard(websocket)
            if not self.rooms[discussion_id]:
                del self.rooms[discussion_id]

        user_info = self.user_info.pop(websocket, {})

        # Broadcast user.left event
        await self.broadcast(discussion_id, {
            "event": "user.left",
            "data": {
                "user_id": user_info.get("user_id"),
                "name": user_info.get("name"),
            },
        })

    async def broadcast(self, discussion_id: str, message: dict, exclude: WebSocket = None):
        """Send a message to all connections in a discussion room."""
        if discussion_id not in self.rooms:
            return
        dead_connections = set()
        for ws in self.rooms[discussion_id]:
            if ws == exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.add(ws)
        # Clean up dead connections
        for ws in dead_connections:
            self.rooms[discussion_id].discard(ws)
            self.user_info.pop(ws, None)


# Global connection manager
manager = ConnectionManager()


async def discussion_websocket_endpoint(websocket: WebSocket, discussion_id: str):
    """
    WebSocket endpoint for a discussion room.

    Client must send an initial auth message:
    {"type": "auth", "token": "<jwt_token>"}

    After authentication, the client can send:
    {"type": "message.send", "content": "Hello!"}
    {"type": "typing.started"}
    {"type": "typing.stopped"}
    """

    # Wait for auth message
    try:
        auth_data = await websocket.receive_json()
    except Exception:
        await websocket.close(code=4001, reason="Invalid auth")
        return

    if auth_data.get("type") != "auth" or not auth_data.get("token"):
        await websocket.close(code=4001, reason="Missing auth token")
        return

    # Validate token
    payload = decode_token(auth_data["token"])
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")

    # Get user info from DB
    db: Session = SessionLocal()
    try:
        from models.user import User
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return

        # Verify discussion exists
        discussion = db.query(Discussion).filter(Discussion.discussion_id == discussion_id).first()
        if not discussion:
            await websocket.close(code=4004, reason="Discussion not found")
            return

        user_info = {"user_id": str(user.user_id), "name": user.name}
    finally:
        db.close()

    # Connect to room
    await manager.connect(websocket, discussion_id, user_info)

    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")

            if event_type == "message.send":
                content = data.get("content", "").strip()
                if not content:
                    continue

                # Save to DB
                db = SessionLocal()
                try:
                    message = Message(
                        discussion_id=discussion_id,
                        user_id=user_id,
                        content=content,
                    )
                    db.add(message)
                    db.commit()
                    db.refresh(message)

                    await manager.broadcast(discussion_id, {
                        "event": "message.sent",
                        "data": {
                            "message_id": str(message.message_id),
                            "user_id": str(user_id),
                            "name": user_info.get("name"),
                            "content": content,
                            "created_at": message.created_at.isoformat() if message.created_at else None,
                        },
                    })
                finally:
                    db.close()

            elif event_type == "typing.started":
                await manager.broadcast(discussion_id, {
                    "event": "typing.started",
                    "data": {
                        "user_id": user_info.get("user_id"),
                        "name": user_info.get("name"),
                    },
                }, exclude=websocket)

            elif event_type == "typing.stopped":
                await manager.broadcast(discussion_id, {
                    "event": "typing.stopped",
                    "data": {
                        "user_id": user_info.get("user_id"),
                        "name": user_info.get("name"),
                    },
                }, exclude=websocket)

    except WebSocketDisconnect:
        await manager.disconnect(websocket, discussion_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket, discussion_id)
