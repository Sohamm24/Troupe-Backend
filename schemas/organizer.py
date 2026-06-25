"""
schemas/organizer.py
--------------------
Organizer profile schemas.
"""

from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class OrganizerResponse(BaseModel):
    organizer_id: str
    user_id: str
    name: Optional[str] = None
    bio: Optional[str] = None
    verification_status: bool = False
    profile_pic: Optional[str] = None
    region: Optional[str] = None
    ratings: Optional[Decimal] = None
    trip_count: int = 0
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class OrganizerUpdateRequest(BaseModel):
    bio: Optional[str] = None
    region: Optional[str] = None
    profile_pic: Optional[str] = None


class OrganizerListResponse(BaseModel):
    organizers: List[OrganizerResponse]
    page: int
    total: int
