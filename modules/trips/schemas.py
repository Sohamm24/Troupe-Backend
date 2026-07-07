"""
schemas/trip.py
---------------
Trip CRUD schemas.
"""

from modules.trips.models import TripStatus
from typing import Optional, List, Any
from datetime import date, datetime
from pydantic import BaseModel
from enum import Enum


class ConfirmUploadRequest(BaseModel):
    trip_id: str
    file_path: str 

class ReplaceImageRequest(BaseModel):
    trip_id: str
    new_file_path: str     

class LocationModel(BaseModel):
    name: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class Inclusions(BaseModel):
    breakfast: Optional[bool] = False
    lunch: Optional[bool] = False
    dinner: Optional[bool] = False
    accommodation: Optional[bool] = False
    vehicle_charges: Optional[bool] = False
    guide: Optional[bool] = False
    toll_permit_entry_fees: Optional[bool]= False

class FAQItem(BaseModel):
    question: str
    answer: str


class ItineraryActivity(BaseModel):
    title: str
    location: LocationModel
    time: datetime
    media: str 

class TripCategory(str, Enum):
    BEACH = "Beach"
    HILL = "Hill"
    WEEKEND = "Weekend Trip"
    WILDLIFE = "Wildlife"
    HERITAGE = "Heritage"
    TREKKING = "Trekking"
    BIKERIDING = "Bike Riding"

# ────────────────────────────────────

class TripOrganizerInfo(BaseModel):
    organizer_id: str
    name: Optional[str] = None
    profile_pic: Optional[str] = None
    verification_status: bool = False
    ratings: Optional[float] = None
    trip_count: int = 0

    model_config = {"from_attributes": True}


# ── Trip CRUD ─────────────────────────────────────────────────────────────────

class Step1BasicInfo(BaseModel):
    title: str
    thumbnail: str


class Step2Itinerary(BaseModel):
    itinerary: List[ItineraryActivity]


class Step3Inclusions(BaseModel):
    inclusions: Inclusions


class Step4Pricing(BaseModel):
    max_travellers: Optional[int] = None
    budget: Optional[int] = None
    confirmation_amount: Optional[int] = None
    confirmation_deadline: datetime


class Step5TargetAudience(BaseModel):
    categories: List[TripCategory]


class Step6Description(BaseModel):
    description: str
    frequently_asked: Optional[List[FAQItem]] = []



class TripUpdateRequest(BaseModel):
    title: Optional[str] = None
    location: Optional[LocationModel] = None
    budget: Optional[int] = None
    confirmation_amount: Optional[int] = None
    max_travellers: Optional[int] = None
    description: Optional[str] = None


class TripResponse(BaseModel):
    trip_id: str
    title: str
    thumbnail: str
    itinerary: List[ItineraryActivity] = []
    budget: int
    confirmation_amount: int
    max_travellers: int
    confirmed_travellers: int
    interested_count: int 
    description: str
    frequently_asked: Optional[List[FAQItem]] = []
    organizer: TripOrganizerInfo
    status: TripStatus
    last_completed_step: int
    created_at: datetime
    model_config = {"from_attributes": True}


class TripDetailResponse(TripResponse):
    """Extended trip response including itinerary and discussion preview."""
    itinerary: Optional[List[Any]] = None
    is_confirmed: bool = False


class TripListResponse(BaseModel):
    trips: List[TripResponse]
    page: int
    total: int



"""
schemas/itinerary.py
--------------------
Itinerary schemas.
"""

from typing import Optional, List, Any
from pydantic import BaseModel


class ItineraryResponse(BaseModel):
    itinerary_id: Optional[str] = None
    trip_id: str
    itinerary: Optional[List[Any]] = []

    model_config = {"from_attributes": True}


class ItineraryUpdateRequest(BaseModel):
    itinerary: List[Any]
