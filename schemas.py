"""
schemas.py
----------
Pydantic v2 models for Travel Pinterest.
"""

import json
from typing import TypedDict, Optional, List
from pydantic import BaseModel, field_validator
from datetime import datetime


# ── Image features (used by visual-search service) ────────────────────────────

class ImageFeatures(TypedDict):
    hsv_histogram: List[float]
    dominant_colors: Optional[List[List[float]]]
    color_percentages: Optional[List[float]]
    avg_hsv: Optional[List[float]]


# ── Location ───────────────────────────────────────────────────────────────────

class LocationModel(BaseModel):
    lat: float
    lng: float
    name: Optional[str] = None


# ── User (minimal, embedded inside PostResponse) ───────────────────────────────

class UserBasic(BaseModel):
    """Minimal user info embedded inside PostResponse.owner."""
    id:              int
    username:        Optional[str] = None
    first_name:      Optional[str] = None
    last_name:       Optional[str] = None
    profile_pic_url: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Post schemas ───────────────────────────────────────────────────────────────

class PostResponse(BaseModel):
    """Full post representation returned to the client."""
    id:          int
    user_id:     int
    owner:       Optional[UserBasic] = None
    description: Optional[str]      = None
    location:    Optional[LocationModel] = None
    image_url:   str
    tags:        Optional[List[str]] = []
    likes:       int = 0
    saves:       int = 0
    trip_start:  Optional[str] = None   # YYYY-MM-DD
    trip_end:    Optional[str] = None   # YYYY-MM-DD
    created_at:  Optional[datetime] = None

    @field_validator("location", mode="before")
    @classmethod
    def parse_location_json(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v

    model_config = {"from_attributes": True}


class PostUpdateRequest(BaseModel):
    """Payload for PATCH /api/posts/{id} — all fields optional."""
    description: Optional[str]          = None
    location:    Optional[LocationModel] = None
    trip_start:  Optional[str]          = None   # YYYY-MM-DD
    trip_end:    Optional[str]          = None   # YYYY-MM-DD


# ── User schemas ───────────────────────────────────────────────────────────────

class User(BaseModel):
    id:              int
    external_id:     str
    username:        Optional[str] = None
    first_name:      Optional[str] = None
    last_name:       Optional[str] = None
    profile_pic_url: Optional[str] = None
    onboarded:       bool          = False
    created_at:      Optional[datetime] = None
    posts:           List[PostResponse] = []

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    """Payload for PATCH /api/user/me — all text fields optional."""
    username:   Optional[str] = None
    first_name: Optional[str] = None
    last_name:  Optional[str] = None


# ── Feed ───────────────────────────────────────────────────────────────────────

class FeedResponse(BaseModel):
    """Feed pagination response format."""
    total:    int
    returned: int
    offset:   int
    limit:    int
    posts:    List[PostResponse]
