"""
models/__init__.py
------------------
Re-exports all ORM models and the declarative Base for easy imports.
"""

from database import Base

from models.user import User
from models.organizer import OrganizerProfile
from models.trip import Trip
from models.itinerary import Itinerary
from models.interest import InterestedTrip
from models.discussion import Discussion, Message

__all__ = [
    "Base",
    "User",
    "OrganizerProfile",
    "Trip",
    "Itinerary",
    "InterestedTrip",
    "Discussion",
    "Message",
]
