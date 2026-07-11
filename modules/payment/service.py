"""
modules/payment/service.py
--------------------------
Business logic for the payment module.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import razorpay
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from core.config import settings
from modules.organizers.models import OrganizerProfile
from modules.payment.models import TripConfirmationStatus
from modules.payment.repository import (
    create_hold,
    expire_stale_holds,
    fail_hold,
    get_hold_by_id,
    get_hold_by_idempotency,
    get_hold_by_razorpay_order,
    confirm_hold,
)
from modules.payment.schemas import HoldResponse, HoldStatusResponse
from modules.trips.models import Trip
from modules.users.models import User

razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_SECRET_KEY))

logger = logging.getLogger("travel_platform")


# ── Hold creation ─────────────────────────────────────────────────────────────

def process_create_hold(
    trip_id: str,
    seats_count: int,
    idempotency_key: str,
    current_user: User,
    db: Session,
) -> HoldResponse:
    """
    1. Check idempotency — return existing hold if the key was already used.
    2. Load trip and validate seat availability.
    3. Create a Stripe PaymentIntent for the locked amount.
    4. Atomically create TripConfirmation (hold) in the DB.
    5. Return hold details + Stripe client_secret to the frontend.
    """

    # ── Check idempotency ─────────────────────────────────────────────────────
    existing = get_hold_by_idempotency(db, idempotency_key)
    if existing:
        if existing.status == TripConfirmationStatus.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Previous hold with this idempotency key has expired. Please retry with a new key.",
            )
        total = existing.price_locked * existing.seats_count
        available = (
            (existing.trip.max_travellers or 0) - (existing.trip.confirmed_travellers or 0)
        )
        return HoldResponse(
            trip_confirmation_id=str(existing.trip_confirmation_id),
            price_locked=existing.price_locked,
            total_amount=total,
            hold_expires_at=existing.hold_expires_at,
            seats_left=available,
            razorpay_order_id=existing.payment.razorpay_order_id or "",
            razorpay_key_id=settings.RAZORPAY_KEY_ID,
        )

    # ── Load trip ─────────────────────────────────────────────────────────────
    trip = (
        db.query(Trip)
        .options(
            joinedload(Trip.organizer).joinedload(OrganizerProfile.user),
        )
        .filter(Trip.trip_id == trip_id)
        .first()
    )
    if not trip:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

    if trip.status.value != "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This trip is not accepting confirmations yet.",
        )

    # ── Seat availability check ───────────────────────────────────────────────
    available = (trip.max_travellers or 0) - (trip.confirmed_travellers or 0)
    if available <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SOLD_OUT", "seats_left": 0},
        )
    if seats_count > available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NOT_ENOUGH_SEATS", "seats_left": available},
        )

    # ── Price calculation (server-side, never trust client) ───────────────────
    price_per_seat = Decimal(str(trip.confirmation_amount or 0))
    total_amount_inr = price_per_seat * seats_count
    # Razorpay uses currency subunit (paise for INR)
    amount_paise = int(total_amount_inr * 100)

    # ── Create Razorpay Order ─────────────────────────────────────────────────
    try:
        order_data = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"rcpt_{idempotency_key[:30]}",
            "notes": {
                "trip_id": trip_id,
                "user_id": str(current_user.user_id),
                "seats_count": str(seats_count),
                "idempotency_key": idempotency_key,
            }
        }
        order = razorpay_client.order.create(data=order_data)
    except Exception as exc:
        logger.error("Razorpay Order creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment gateway error. Please try again.",
        )

    # ── Create DB hold ────────────────────────────────────────────────────────
    try:
        hold = create_hold(
            db=db,
            trip=trip,
            user_id=current_user.user_id,
            seats_count=seats_count,
            idempotency_key=idempotency_key,
            razorpay_order_id=order["id"],
        )
    except ValueError as exc:
        # Race condition: seats just got taken between our check and insert
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NOT_ENOUGH_SEATS", "seats_left": available, "message": str(exc)},
        )

    # ── Reload available seats after hold ─────────────────────────────────────
    db.refresh(trip)
    seats_left = max(0, (trip.max_travellers or 0) - (trip.confirmed_travellers or 0))

    return HoldResponse(
        trip_confirmation_id=str(hold.trip_confirmation_id),
        price_locked=price_per_seat,
        total_amount=total_amount_inr,
        hold_expires_at=hold.hold_expires_at,
        seats_left=seats_left,
        razorpay_order_id=order["id"],
        razorpay_key_id=settings.RAZORPAY_KEY_ID,
    )


# ── Hold status ───────────────────────────────────────────────────────────────

def process_get_hold_status(confirmation_id: str, current_user: User, db: Session) -> HoldStatusResponse:
    hold = get_hold_by_id(db, confirmation_id)
    if not hold:
        raise HTTPException(status_code=404, detail="Hold not found")
    if str(hold.user_id) != str(current_user.user_id):
        raise HTTPException(status_code=403, detail="Not your hold")

    return HoldStatusResponse(
        trip_confirmation_id=str(hold.trip_confirmation_id),
        status=hold.status.value,
        hold_expires_at=hold.hold_expires_at,
        price_locked=hold.price_locked,
        seats_count=hold.seats_count,
    )


# ── Webhook handling ──────────────────────────────────────────────────────────

def process_razorpay_webhook(payload: bytes, sig_header: str, db: Session) -> dict:
    """
    Verify Razorpay webhook signature, dispatch to appropriate handler,
    and return a success/ignored response dict.
    """
    try:
        # Verify Razorpay signature using the utility method
        # verify_webhook_signature takes a string payload, so we decode bytes
        razorpay_client.utility.verify_webhook_signature(
            payload.decode("utf-8"), sig_header, settings.RAZORPAY_WEBHOOK_SECRET
        )
    except Exception as exc:
        logger.error("Razorpay signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature")

    import json
    try:
        event = json.loads(payload.decode("utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("event")
    event_payload = event.get("payload", {})
    payment_entity = event_payload.get("payment", {}).get("entity", {})
    order_id = payment_entity.get("order_id")
    payment_id = payment_entity.get("id")

    logger.info("Razorpay webhook received: %s order_id=%s payment_id=%s", event_type, order_id, payment_id)

    if event_type == "payment.captured":
        if order_id:
            hold = get_hold_by_razorpay_order(db, order_id)
            if hold:
                confirm_hold(db, str(hold.trip_confirmation_id), order_id, payment_id)
            else:
                logger.warning("Webhook: no hold found for order %s", order_id)

    elif event_type == "payment.failed":
        if order_id:
            fail_hold(db, order_id)

    else:
        logger.debug("Webhook: unhandled event type %s", event_type)

    return {"received": True, "event": event_type}


# ── Cleanup ───────────────────────────────────────────────────────────────────

def process_expire_holds(db: Session) -> dict:
    count = expire_stale_holds(db)
    return {"expired": count}
