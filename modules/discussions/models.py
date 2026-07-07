"""
models/discussion.py
--------------------
Discussion forum (one per trip) and Messages within discussions.
"""

import uuid
from enum import Enum

from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, JSON, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base
from modules.discussions.schemas import MessageStatus, MessageType


class Discussion(Base):
    __tablename__ = "discussions"

    discussion_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    trip_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trips.trip_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # ── Relationships ──────────────────────────────────────────────────────
    trip = relationship("Trip", back_populates="discussions")
    messages = relationship(
        "Message",
        back_populates="discussion",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    participants = relationship(
        "UserDiscussion",
        back_populates="discussion",
        cascade="all, delete-orphan",
    )


class Message(Base):
    __tablename__ = "messages"

    message_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    discussion_id = Column(
        UUID(as_uuid=True),
        ForeignKey("discussions.discussion_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type = Column(
        # Store as VARCHAR so the value is the enum string (TEXT, MEDIA, …)
        String(20),
        nullable=False,
        default=MessageType.TEXT,
    )

    # Content fields
    text = Column(Text, nullable=True)
    media_url = Column(Text, nullable=True)
    mime_type = Column(String(255), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(BigInteger, nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    location = Column(JSON, nullable=True)

    reply_to_message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.message_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status = Column(String(20), nullable=False, default=MessageStatus.SENT)

    client_timestamp = Column(BigInteger, nullable=True)
    server_timestamp = Column(BigInteger, nullable=True)

    is_edited = Column(Boolean, default=False, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    edited_at = Column(TIMESTAMP(timezone=True), nullable=True)
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── Relationships ──────────────────────────────────────────────────────
    discussion = relationship("Discussion", back_populates="messages")
    user = relationship("User", back_populates="messages")
    reply_to = relationship(
        "Message",
        remote_side=[message_id],
        foreign_keys=[reply_to_message_id],
    )


class UserDiscussion(Base):
    __tablename__ = "user_discussions"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    discussion_id = Column(
        UUID(as_uuid=True),
        ForeignKey("discussions.discussion_id", ondelete="CASCADE"),
        primary_key=True,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    user = relationship("User")
    discussion = relationship("Discussion", back_populates="participants")