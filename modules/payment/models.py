import enum
import uuid

from sqlalchemy import Column, Integer, String, TIMESTAMP, ForeignKey, Enum, DECIMAL
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.database import Base


class TripConfirmationStatus(str, enum.Enum):
    PENDING_PAYMENT = "pending_payment"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    stripe_payment_intent_id = Column(String(255), nullable=True, unique=True, index=True)
    razorpay_order_id = Column(String(255), nullable=True, unique=True, index=True)
    razorpay_payment_id = Column(String(255), nullable=True, unique=True, index=True)
    razorpay_signature = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    confirmations = relationship("TripConfirmation", back_populates="payment")


class TripConfirmation(Base):
    __tablename__ = "trip_confirmations"

    trip_confirmation_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    trip_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trips.trip_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payments.payment_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    seats_count = Column(Integer, nullable=False)
    price_locked = Column(DECIMAL(12, 2), nullable=False)
    status = Column(
        Enum(TripConfirmationStatus, name="trip_confirmation_status"),
        nullable=False,
        default=TripConfirmationStatus.PENDING_PAYMENT,
        index=True,
    )
    hold_expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    idempotency_key = Column(String(255), nullable=False, unique=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ── Relationships ──────────────────────────────────────────────────────
    trip = relationship("Trip", back_populates="confirmations")
    user = relationship("User", back_populates="confirmations")
    payment = relationship("Payment", back_populates="confirmations")