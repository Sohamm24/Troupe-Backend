"""
schemas/discussion.py
---------------------
Discussion and message schemas.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


class MessageUserInfo(BaseModel):
    user_id: str
    name: Optional[str] = None

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message_id: str
    discussion_id: str
    user_id: str
    user: Optional[MessageUserInfo] = None
    content: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MessageCreateRequest(BaseModel):
    message: str


class MessageUpdateRequest(BaseModel):
    message: str


class DiscussionResponse(BaseModel):
    discussion_id: str
    trip_id: str
    messages: List[MessageResponse] = []
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    messages: List[MessageResponse]
    page: int
    total: int
