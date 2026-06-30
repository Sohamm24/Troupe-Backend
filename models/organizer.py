"""
models/organizer.py
-------------------
Organizer profile — one-to-one with User, owns Trips.
"""

import uuid

from sqlalchemy import Column, String, Text, Boolean, Numeric, ForeignKey, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


class OrganizerProfile(Base):
    __tablename__ = "organizer_profiles"

    organizer_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    bio = Column(Text, nullable=True)
    verification_status = Column(Boolean, default=False, nullable=False)
    profile_pic = Column(String, nullable=True)
    region = Column(String, nullable=True)
    ratings = Column(Numeric(2, 1), default=0.0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # ── Relationships ─────────────────────────────────────────────────────
    user = relationship("User", back_populates="organizer_profile")
    trips = relationship(
        "Trip",
        back_populates="organizer",
        cascade="all, delete-orphan",
    )
