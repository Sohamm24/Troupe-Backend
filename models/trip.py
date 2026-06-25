"""
models/trip.py
--------------
Trip entity — owned by an organizer, with JSONB fields for location and FAQs.
"""

import uuid

from sqlalchemy import (
    Column, String, Text, Integer, Boolean, Date, ForeignKey, TIMESTAMP,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


class Trip(Base):
    __tablename__ = "trips"

    trip_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    organizer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizer_profiles.organizer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String, nullable=False)
    location = Column(JSONB, nullable=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=True)
    is_one_day_trip = Column(Boolean, default=False)
    budget = Column(Integer, nullable=True)
    confirmation_amount = Column(Integer, nullable=True)
    max_travellers = Column(Integer, nullable=True)
    confirmed_travellers = Column(Integer, default=0, nullable=False)
    interested_count = Column(Integer, default=0, nullable=False, index=True)
    description = Column(Text, nullable=True)
    frequently_asked = Column(JSONB, nullable=True, default=[])
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # ── Relationships ─────────────────────────────────────────────────────
    organizer = relationship("OrganizerProfile", back_populates="trips")
    itinerary = relationship(
        "Itinerary",
        back_populates="trip",
        uselist=False,
        cascade="all, delete-orphan",
    )
    interested_users = relationship(
        "InterestedTrip",
        back_populates="trip",
        cascade="all, delete-orphan",
    )
    discussions = relationship(
        "Discussion",
        back_populates="trip",
        cascade="all, delete-orphan",
    )
