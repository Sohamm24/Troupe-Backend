"""
modules/payment/router.py
--------------------------
Payment module HTTP routes.

Routes:
    POST   /api/v1/payments/hold             — Create seat hold + Stripe PaymentIntent
    GET    /api/v1/payments/hold/{id}        — Poll hold status (fallback to webhook)
    POST   /api/v1/payments/webhook          — Stripe webhook handler
    POST   /api/v1/payments/cleanup          — Expire stale holds (call from cron)
"""

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.dependencies import get_current_user
from modules.payment.schemas import HoldRequest, HoldResponse, HoldStatusResponse
from modules.payment.service import (
    process_create_hold,
    process_expire_holds,
    process_get_hold_status,
    process_razorpay_webhook,
)
from modules.payment.webhook import get_raw_body
from modules.users.models import User

router = APIRouter()


# ── Create hold ───────────────────────────────────────────────────────────────

@router.post(
    "/hold",
    response_model=HoldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a seat hold and Razorpay Order",
)
def create_hold(
    payload: HoldRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Atomically checks seat availability, locks the price, and creates a
    Razorpay Order. Returns the razorpay_order_id and razorpay_key_id for
    the frontend to complete payment with the Razorpay SDK.
    """
    return process_create_hold(
        trip_id=payload.trip_id,
        seats_count=payload.seats_count,
        idempotency_key=payload.idempotency_key,
        current_user=current_user,
        db=db,
    )


# ── Hold status ───────────────────────────────────────────────────────────────

@router.get(
    "/hold/{confirmation_id}",
    response_model=HoldStatusResponse,
    summary="Get hold / payment status",
)
def get_hold_status(
    confirmation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return process_get_hold_status(confirmation_id, current_user, db)


# ── Razorpay webhook ──────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Razorpay webhook endpoint",
    include_in_schema=False,   # don't expose in OpenAPI docs
)
async def razorpay_webhook(
    raw_body: bytes = Depends(get_raw_body),
    razorpay_signature: str = Header(..., alias="x-razorpay-signature"),
    db: Session = Depends(get_db),
):
    """
    Razorpay sends signed POST requests here on payment events.
    We verify the signature and flip hold status accordingly.
    """
    return process_razorpay_webhook(raw_body, razorpay_signature, db)


# ── Cleanup cron endpoint ─────────────────────────────────────────────────────

@router.post(
    "/cleanup",
    status_code=status.HTTP_200_OK,
    summary="Expire stale holds (call from scheduler / cron)",
    include_in_schema=False,
)
def cleanup_holds(db: Session = Depends(get_db)):
    """
    Marks all PENDING_PAYMENT holds whose TTL has elapsed as EXPIRED.
    Should be triggered externally (e.g., QStash cron, render.yaml cron).
    """
    return process_expire_holds(db)
