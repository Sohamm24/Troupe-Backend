"""
schemas/user.py
---------------
User profile schemas.
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class UserResponse(BaseModel):
    user_id: str
    name: str
    email: str
    phone: Optional[str] = None
    is_organizer: bool = False
    organizer_id: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
