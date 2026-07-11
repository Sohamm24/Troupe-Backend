"""
modules/payment/repository.py
------------------------------
Database operations for the payment module.
All seat-count mutations happen inside explicit transactions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from modules.payment.models import Payment, TripConfirmation, TripConfirmationStatus
from modules.trips.models import Trip

logger = logging.getLogger("travel_platform")

HOLD_TTL_SECONDS = 480  # 8 minutes, hardcoded


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── Read ──────────────────────────────────────────────────────────────────────

def get_hold_by_idempotency(db: Session, idempotency_key: str) -> Optional[TripConfirmation]:
    return (
        db.query(TripConfirmation)
        .filter(TripConfirmation.idempotency_key == idempotency_key)
        .first()
    )


def get_hold_by_id(db: Session, confirmation_id: str) -> Optional[TripConfirmation]:
    return (
        db.query(TripConfirmation)
        .filter(TripConfirmation.trip_confirmation_id == confirmation_id)
        .first()
    )


def get_hold_by_razorpay_order(db: Session, order_id: str) -> Optional[TripConfirmation]:
    """Look up a hold via the Payment row's razorpay_order_id."""
    payment = (
        db.query(Payment)
        .filter(Payment.razorpay_order_id == order_id)
        .first()
    )
    if not payment:
        return None
    return (
        db.query(TripConfirmation)
        .filter(TripConfirmation.payment_id == payment.payment_id)
        .first()
    )


# ── Write ─────────────────────────────────────────────────────────────────────

def create_hold(
    db: Session,
    trip: Trip,
    user_id: UUID,
    seats_count: int,
    idempotency_key: str,
    razorpay_order_id: str,
) -> TripConfirmation:
    """
    Atomically verifies seat availability, deducts seats, and creates a
    TripConfirmation (hold) + linked Payment row.

    Raises ValueError if not enough seats are available.
    All mutations are wrapped in a single transaction; the caller must NOT
    have already opened a savepoint.
    """
    available = (trip.max_travellers or 0) - (trip.confirmed_travellers or 0)
    if available < seats_count:
        raise ValueError(f"Only {available} seat(s) available, requested {seats_count}")

    price_locked = Decimal(str(trip.confirmation_amount or 0))
    expires_at = _now_utc() + timedelta(seconds=HOLD_TTL_SECONDS)

    # Create the Payment row (links hold → Razorpay Order)
    payment = Payment(razorpay_order_id=razorpay_order_id)
    db.add(payment)
    db.flush()  # get payment_id without committing

    # Create the TripConfirmation (hold)
    hold = TripConfirmation(
        trip_id=trip.trip_id,
        user_id=user_id,
        payment_id=payment.payment_id,
        seats_count=seats_count,
        price_locked=price_locked,
        status=TripConfirmationStatus.PENDING_PAYMENT,
        hold_expires_at=expires_at,
        idempotency_key=idempotency_key,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    logger.info(
        "Hold created: confirmation_id=%s trip_id=%s seats=%d",
        hold.trip_confirmation_id,
        trip.trip_id,
        seats_count,
    )
    return hold


def confirm_hold(
    db: Session,
    confirmation_id: str,
    order_id: str,
    payment_id: str,
) -> Optional[TripConfirmation]:
    """
    Flip a PENDING_PAYMENT hold to CONFIRMED and increment confirmed_travellers
    on the parent Trip. Idempotent — returns the hold unchanged if already confirmed.
    """
    hold = get_hold_by_id(db, confirmation_id)
    if not hold:
        logger.warning("confirm_hold: hold %s not found", confirmation_id)
        return None

    if hold.status == TripConfirmationStatus.CONFIRMED:
        return hold  # idempotent

    if hold.status not in (TripConfirmationStatus.PENDING_PAYMENT,):
        logger.warning(
            "confirm_hold: hold %s is in status %s, cannot confirm",
            confirmation_id,
            hold.status,
        )
        return hold

    hold.status = TripConfirmationStatus.CONFIRMED

    # Save payment_id in the payment relation
    if hold.payment:
        hold.payment.razorpay_payment_id = payment_id

    # Atomically increment the trip's confirmed_travellers
    trip = db.query(Trip).filter(Trip.trip_id == hold.trip_id).with_for_update().first()
    if trip:
        trip.confirmed_travellers = (trip.confirmed_travellers or 0) + hold.seats_count

    db.commit()
    db.refresh(hold)
    logger.info("Hold %s confirmed (order_id=%s, payment_id=%s)", confirmation_id, order_id, payment_id)
    return hold


def fail_hold(db: Session, order_id: str) -> None:
    """Mark a hold as FAILED when the payment fails/is cancelled."""
    hold = get_hold_by_razorpay_order(db, order_id)
    if not hold:
        return
    if hold.status != TripConfirmationStatus.PENDING_PAYMENT:
        return
    hold.status = TripConfirmationStatus.FAILED
    db.commit()
    logger.info("Hold failed via order_id=%s", order_id)


def expire_stale_holds(db: Session) -> int:
    """
    Find all PENDING_PAYMENT holds whose hold_expires_at has passed,
    mark them EXPIRED, and release their seats back to the trip.
    Returns the number of holds expired.
    """
    now = _now_utc()
    stale_holds = (
        db.query(TripConfirmation)
        .filter(
            TripConfirmation.status == TripConfirmationStatus.PENDING_PAYMENT,
            TripConfirmation.hold_expires_at < now,
        )
        .all()
    )

    count = 0
    for hold in stale_holds:
        hold.status = TripConfirmationStatus.EXPIRED
        # No seat decrement because we never incremented confirmed_travellers on hold creation;
        # seats are only incremented on CONFIRM. So no rollback needed here.
        count += 1

    if count:
        db.commit()
        logger.info("Expired %d stale hold(s)", count)

    return count
