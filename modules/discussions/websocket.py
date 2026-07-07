from typing import Dict, List, Tuple
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[Tuple[WebSocket, str]] = []
        # Maps user_id -> last message sent (useful for resumption / read-receipts)
        self.last_sent_messages: Dict[str, str] = {}

    async def connect(self, websocket: WebSocket, room_id: str) -> None:
        await websocket.accept()
        self.active_connections.append((websocket, room_id))

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections = [
            (ws, rid) for ws, rid in self.active_connections if ws != websocket
        ]

    def record_last_sent(self, user_id: str, message: str) -> None:
        """Store the last message a user sent (call before disconnect if needed)."""
        self.last_sent_messages[user_id] = message

    async def broadcast(self, message: str, room_id: str) -> None:
        """Send *message* to every websocket currently in *room_id*."""
        for ws, rid in self.active_connections:
            if rid == room_id:
                try:
                    await ws.send_text(message)
                except Exception:
                    pass


manager = ConnectionManager()