"""
models/interest.py
------------------
Junction table tracking which users are interested in which trips.
"""

from sqlalchemy import Column, Integer, ForeignKey, TIMESTAMP, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base


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
