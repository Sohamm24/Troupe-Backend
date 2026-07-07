"""
schemas/discussion.py
---------------------
Discussion and message schemas.
"""

from typing import Any
from typing import Dict
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel
from enum import Enum

class MessageType(str, Enum):
    TEXT = "TEXT"
    MEDIA = "MEDIA"
    LOCATION = "LOCATION"
    UPDATE = "UPDATE"
    

class MessageUserInfo(BaseModel):
    user_id: str
    name: Optional[str] = None

    model_config = {"from_attributes": True}


class MessageReplyInfo(BaseModel):
    message_id: str
    user_id: str
    text: Optional[str] = None
    type: MessageType

    model_config = {"from_attributes": True}

class MessageStatus(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"

class MessageResponse(BaseModel):
    message_id: str
    discussion_id: str

    user_id: str
    user: Optional[MessageUserInfo] = None

    type: MessageType
    status: MessageStatus

    # Content
    text: Optional[str] = None
    media_url: Optional[str] = None
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    thumbnail_url: Optional[str] = None
    location: Optional[Dict[str, Any]] = None

    # Reply
    reply_to_message_id: Optional[str] = None
    reply_to: Optional[MessageReplyInfo] = None

    # Metadata
    client_timestamp: Optional[int] = None
    server_timestamp: Optional[int] = None

    is_edited: bool
    is_deleted: bool

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MessageCreateRequest(BaseModel):
    type: MessageType = MessageType.TEXT

    text: Optional[str] = None
    media_url: Optional[str] = None
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    thumbnail_url: Optional[str] = None
    location: Optional[Dict[str, Any]] = None

    reply_to_message_id: Optional[str] = None
    client_timestamp: Optional[int] = None


class MessageUpdateRequest(BaseModel):
    text: str


class MessageListResponse(BaseModel):
    messages: List[MessageResponse]
    page: int
    total: int

class DiscussionResponse(BaseModel):
    discussion_id: str
    trip_id: str
    messages: List[MessageResponse] = []
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}    
