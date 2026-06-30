"""
models/user.py
--------------
User account table — matches the SRS Users schema with UUID primary keys.
"""

import uuid

from sqlalchemy import Column, String, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # ── Relationships ─────────────────────────────────────────────────────
    organizer_profile = relationship(
        "OrganizerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    interested_trips = relationship(
        "InterestedTrip",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "Message",
        back_populates="user",
        cascade="all, delete-orphan",
    )
