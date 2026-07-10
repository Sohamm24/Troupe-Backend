"""
modules/payment/service.py
--------------------------
Business logic for the payment module.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import stripe
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
    get_hold_by_payment_intent,
    confirm_hold,
)
from modules.payment.schemas import HoldResponse, HoldStatusResponse
from modules.trips.models import Trip
from modules.users.models import User

stripe.api_key = settings.STRIPE_SECRET_KEY

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

    # ── Idempotency check ─────────────────────────────────────────────────────
    existing = get_hold_by_idempotency(db, idempotency_key)
    if existing:
        if existing.status == TripConfirmationStatus.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Previous hold with this idempotency key has expired. Please retry with a new key.",
            )
        # Re-build the response from the existing hold (fetch pi client_secret from Stripe)
        pi = stripe.PaymentIntent.retrieve(existing.payment.stripe_payment_intent_id)
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
            stripe_client_secret=pi.client_secret,
            stripe_publishable_key=settings.STRIPE_PUBLISHABLE_KEY if hasattr(settings, "STRIPE_PUBLISHABLE_KEY") else "",
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
    # Stripe uses smallest currency unit; INR does not have sub-units in practice
    amount_paise = int(total_amount_inr * 100)

    # ── Create Stripe PaymentIntent ───────────────────────────────────────────
    try:
        pi = stripe.PaymentIntent.create(
            amount=amount_paise,
            currency="inr",
            metadata={
                "trip_id": trip_id,
                "user_id": str(current_user.user_id),
                "seats_count": seats_count,
                "idempotency_key": idempotency_key,
            },
            idempotency_key=f"pi-{idempotency_key}",  # Stripe-level idempotency
        )
    except stripe.error.StripeError as exc:
        logger.error("Stripe PaymentIntent creation failed: %s", exc)
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
            stripe_payment_intent_id=pi.id,
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
        stripe_client_secret=pi.client_secret,
        stripe_publishable_key="",  # sent separately via env; here for schema completeness
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

def process_stripe_webhook(payload: bytes, sig_header: str, db: Session) -> dict:
    """
    Verify Stripe webhook signature, dispatch to appropriate handler,
    and return a success/ignored response dict.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data_object = event["data"]["object"]

    logger.info("Stripe webhook received: %s  id=%s", event_type, event["id"])

    if event_type == "payment_intent.succeeded":
        pi_id = data_object["id"]
        hold = get_hold_by_payment_intent(db, pi_id)
        if hold:
            confirm_hold(db, str(hold.trip_confirmation_id), pi_id)
        else:
            logger.warning("Webhook: no hold found for payment_intent %s", pi_id)

    elif event_type in ("payment_intent.payment_failed", "payment_intent.canceled"):
        pi_id = data_object["id"]
        fail_hold(db, pi_id)

    else:
        logger.debug("Webhook: unhandled event type %s", event_type)

    return {"received": True, "event": event_type}


# ── Cleanup ───────────────────────────────────────────────────────────────────

def process_expire_holds(db: Session) -> dict:
    count = expire_stale_holds(db)
    return {"expired": count}
