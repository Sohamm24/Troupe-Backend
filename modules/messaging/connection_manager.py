"""
modules/messaging/connection_manager.py
-----------------------------------------
In-memory WebSocket connection registry.

Tracks active WebSocket connections keyed by user_id.
Used for real-time delivery when the recipient is online in the same server process.
For a multi-process/multi-pod setup, Redis presence is the cross-process signal.
"""

import logging
from typing import Dict
from fastapi import WebSocket

logger = logging.getLogger("travel_platform")


class ConnectionManager:
    """Thread-safe (single-process) registry of active WebSocket connections."""

    def __init__(self):
        # Maps user_id (str) → active WebSocket
        self._connections: Dict[str, WebSocket] = {}

    # ── Connection lifecycle ──────────────────────────────────────────────

    def connect(self, user_id: str, websocket: WebSocket) -> None:
        """Register a new WebSocket for *user_id*.
        If the user already has an open connection it is replaced.
        """
        self._connections[user_id] = websocket
        logger.info(f"WS connected: user_id={user_id}  total={len(self._connections)}")

    def disconnect(self, user_id: str) -> None:
        """Remove the WebSocket for *user_id*."""
        self._connections.pop(user_id, None)
        logger.info(f"WS disconnected: user_id={user_id}  total={len(self._connections)}")

    # ── Presence helpers ─────────────────────────────────────────────────

    def is_online(self, user_id: str) -> bool:
        """Return True when the user has an active WebSocket in *this* process."""
        return user_id in self._connections

    # ── Sending ──────────────────────────────────────────────────────────

    async def send_to_user(self, user_id: str, payload: dict) -> bool:
        """Send *payload* as JSON to *user_id*.
        Returns True on success, False when the user is not connected.
        """
        ws = self._connections.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_json(payload)
            return True
        except Exception as exc:
            logger.warning(f"Failed to send to user_id={user_id}: {exc}")
            self.disconnect(user_id)
            return False


# Global singleton — imported by router + service + qstash handler
manager = ConnectionManager()
