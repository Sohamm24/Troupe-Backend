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
