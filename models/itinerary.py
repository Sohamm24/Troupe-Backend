"""
models/itinerary.py
-------------------
Itinerary for a trip — one-to-one with Trip, day-wise activities stored as JSONB.
"""

import uuid

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from database import Base


class Itinerary(Base):
    __tablename__ = "itineraries"

    itinerary_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    trip_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trips.trip_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    itinerary = Column(JSONB, nullable=True, default=[])

    # ── Relationships ─────────────────────────────────────────────────────
    trip = relationship("Trip", back_populates="itinerary")
