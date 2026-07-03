from core.database import Base
import enum
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid


class TripStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


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

    status = Column(Enum(TripStatus), nullable=False, default=TripStatus.DRAFT, index=True)
    last_completed_step = Column(Integer, nullable=False, default=1)

 
    title = Column(String, nullable=True)
    thumbnail = Column(Text, nullable=True)


    itinerary = Column(JSONB, nullable=False, default=list)


    inclusions = Column(JSONB, nullable=False, default=dict)

 
    max_travellers = Column(Integer, nullable=True)
    budget = Column(Integer, nullable=True)
    confirmation_amount = Column(Integer, nullable=True)
    confirmation_deadline = Column(TIMESTAMP(timezone=True), nullable=True)


    categories = Column(ARRAY(String), nullable=False, default=list)


    description = Column(Text, nullable=True)
    frequently_asked = Column(JSONB, nullable=True, default=list)

    interested_count = Column(Integer, default=0, nullable=False)
    confirmed_travellers = Column(Integer, default=0, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    organizer = relationship("OrganizerProfile", back_populates="trips")
    interested_users = relationship(
        "InterestedTrip", back_populates="trip", cascade="all, delete-orphan"
    )
    discussions = relationship(
        "Discussion", back_populates="trip", cascade="all, delete-orphan"
    )

"""
models/interest.py
------------------
Junction table tracking which users are interested in which trips.
"""

from sqlalchemy import Column, Integer, ForeignKey, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


class InterestedTrip(Base):
    __tablename__ = "interested_trips"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    trip_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trips.trip_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "trip_id", name="uq_interested_user_trip"),
    )

    # ── Relationships ─────────────────────────────────────────────────────
    user = relationship("User", back_populates="interested_trips")
    trip = relationship("Trip", back_populates="interested_users")
