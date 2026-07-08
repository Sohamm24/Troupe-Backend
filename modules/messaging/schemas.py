"""
modules/messaging/schemas.py
-----------------------------
Pydantic schemas for the messaging module.

All outbound schemas match the client types.ts exactly so the
frontend can consume the WebSocket events and REST responses without
any transformation.
"""

from __future__ import annotations

from typing import List, Optional
from datetime import datetime
from enum import Enum
from pydantic import BaseModel


# ── Mirror of client MessageStatus enum ─────────────────────────────────────

class MessageStatusSchema(str, Enum):
    SENDING = "SENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"


# ── Outbound DTOs (match types.ts) ───────────────────────────────────────────

class UserOut(BaseModel):
    """Matches client types.ts → User"""
    user_id: str
    name: str
    profile_pic: Optional[str] = None
    organizer_id: Optional[str] = None
    is_verified: Optional[bool] = None

    model_config = {"from_attributes": True}


class ReplyMessageOut(BaseModel):
    """Matches client types.ts → ReplyMessage"""
    message_id: int
    sender_id: str
    text: str
    is_deleted: bool

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    """Matches client types.ts → Message"""
    message_id: int
    chat_id: str
    sender_id: str
    text: str
    is_edited: bool
    is_deleted: bool
    reply_to_message: Optional[ReplyMessageOut] = None
    status: MessageStatusSchema
    created_at: str        # ISO-8601 string — keeps it wire-compatible with TS

    model_config = {"from_attributes": True}


class UserChatOut(BaseModel):
    """Matches client types.ts → UserChat"""
    user_chat_id: str
    chat_id: str
    last_read_timestamp: str   # ISO-8601
    last_message: Optional[MessageOut] = None
    unread_count: int
    user: UserOut

    model_config = {"from_attributes": True}


# ── WebSocket: inbound event payloads ────────────────────────────────────────

class JoinUserChatPayload(BaseModel):
    """Client emits 'joinUserChat' when opening a conversation.

    organizer_user_id: the user_id of the OTHER participant (the organizer).
    last_received_sequence: the message_id of the last message the client
        already has (race-condition guard). Send 0 or omit if no messages known yet.
    """
    organizer_user_id: str
    last_received_sequence: int = 0


class SendMessagePayload(BaseModel):
    """Client emits 'sendMessage'."""
    text: str
    reply_to_message_id: Optional[int] = None


# ── WebSocket: outbound event envelopes ──────────────────────────────────────

class WsEvent(BaseModel):
    """All WS events share this envelope: { event, data }"""
    event: str
    data: dict


# ── REST ────────────────────────────────────────────────────────────────────

class GetUserChatsResponse(BaseModel):
    data: List[UserChatOut]


# ── QStash webhook ──────────────────────────────────────────────────────────

class QStashMessagePayload(BaseModel):
    """Payload published to QStash → delivered back via webhook."""
    message_id: int
    chat_id: str
    sender_id: str
    recipient_user_id: str


# ── FCM token registration ────────────────────────────────────────────────────

class RegisterFCMTokenRequest(BaseModel):
    fcm_token: str
