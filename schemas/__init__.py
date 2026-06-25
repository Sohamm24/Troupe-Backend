"""
schemas/__init__.py
-------------------
Re-exports all Pydantic schemas.
"""

from schemas.common import SuccessResponse, ErrorResponse
from schemas.auth import RegisterRequest, LoginRequest, AuthResponse
from schemas.user import UserResponse, UserUpdateRequest
from schemas.organizer import (
    OrganizerResponse,
    OrganizerUpdateRequest,
    OrganizerListResponse,
)
from schemas.trip import (
    TripCreateRequest,
    TripUpdateRequest,
    TripResponse,
    TripListResponse,
    TripDetailResponse,
)
from schemas.itinerary import ItineraryResponse, ItineraryUpdateRequest
from schemas.discussion import (
    DiscussionResponse,
    MessageCreateRequest,
    MessageUpdateRequest,
    MessageResponse,
    MessageListResponse,
)
