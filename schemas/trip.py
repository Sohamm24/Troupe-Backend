"""
schemas/trip.py
---------------
Trip CRUD schemas.
"""

from typing import Optional, List, Any
from datetime import date, datetime
from pydantic import BaseModel


class LocationModel(BaseModel):
    name: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class FAQItem(BaseModel):
    question: str
    answer: str


class ItineraryActivity(BaseModel):
    sequence: int
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class ItineraryDay(BaseModel):
    day_number: int
    activities: List[ItineraryActivity] = []


# ── Organizer info embedded in trip response ──────────────────────────────────

class TripOrganizerInfo(BaseModel):
    organizer_id: str
    name: Optional[str] = None
    profile_pic: Optional[str] = None
    verification_status: bool = False
    ratings: Optional[float] = None
    trip_count: int = 0

    model_config = {"from_attributes": True}


# ── Trip CRUD ─────────────────────────────────────────────────────────────────

class TripCreateRequest(BaseModel):
    title: str
    location: Optional[LocationModel] = None
    start_date: date
    end_date: Optional[date] = None
    is_one_day_trip: bool = False
    budget: Optional[int] = None
    confirmation_amount: Optional[int] = None
    max_travellers: Optional[int] = None
    description: Optional[str] = None
    frequently_asked: Optional[List[FAQItem]] = []
    itinerary: Optional[List[ItineraryDay]] = []


class TripUpdateRequest(BaseModel):
    title: Optional[str] = None
    location: Optional[LocationModel] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_one_day_trip: Optional[bool] = None
    budget: Optional[int] = None
    confirmation_amount: Optional[int] = None
    max_travellers: Optional[int] = None
    description: Optional[str] = None


class TripResponse(BaseModel):
    trip_id: str
    organizer_id: str
    title: str
    location: Optional[Any] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_one_day_trip: bool = False
    budget: Optional[int] = None
    confirmation_amount: Optional[int] = None
    max_travellers: Optional[int] = None
    confirmed_travellers: int = 0
    interested_count: int = 0
    description: Optional[str] = None
    frequently_asked: Optional[List[Any]] = []
    organizer: Optional[TripOrganizerInfo] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TripDetailResponse(TripResponse):
    """Extended trip response including itinerary and discussion preview."""
    itinerary: Optional[List[Any]] = None
    discussion_id: Optional[str] = None
    is_interested: bool = False


class TripListResponse(BaseModel):
    trips: List[TripResponse]
    page: int
    total: int
