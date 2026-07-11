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
from fastapi.responses import HTMLResponse
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


# ── Razorpay HTML Checkout page ────────────────────────────────────────────────

@router.get(
    "/checkout-page",
    response_class=HTMLResponse,
    summary="Razorpay Standard Checkout Webpage",
)
def get_checkout_page(
    confirmation_id: str,
    redirect_url: str,
    db: Session = Depends(get_db),
):
    """
    Renders an HTML page that loads Razorpay standard checkout.
    Handles success / failure redirects to custom deep link URL scheme.
    """
    from modules.payment.repository import get_hold_by_id
    from core.config import settings

    hold = get_hold_by_id(db, confirmation_id)
    if not hold or not hold.payment:
        return HTMLResponse(
            content="<h3>Error: Seat hold reservation not found.</h3>",
            status_code=404
        )

    # Get user details for prefill
    user_name = hold.user.name if hold.user else "Traveler"
    user_email = hold.user.email if hold.user else ""
    user_phone = hold.user.phone if hold.user else ""

    amount_paise = int(hold.price_locked * hold.seats_count * 100)
    razorpay_order_id = hold.payment.razorpay_order_id or ""

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Troupe Secure Payment</title>
      <style>
        body {{
          margin: 0;
          padding: 0;
          background-color: #0F0726;
          color: #FFFFFF;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          display: flex;
          flex-direction: column;
          justify-content: center;
          align-items: center;
          height: 100vh;
          text-align: center;
        }}
        .container {{
          padding: 24px;
          border-radius: 16px;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          max-width: 90%;
          box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }}
        h3 {{
          margin: 0 0 16px 0;
          font-size: 20px;
          font-weight: 600;
        }}
        p {{
          color: #A09BB5;
          font-size: 14px;
          margin: 0 0 24px 0;
        }}
        .spinner {{
          border: 3px solid rgba(255, 255, 255, 0.1);
          width: 40px;
          height: 40px;
          border-radius: 50%;
          border-left-color: #7C3AED;
          animation: spin 1s linear infinite;
          margin-bottom: 24px;
        }}
        @keyframes spin {{
          0% {{ transform: rotate(0deg); }}
          100% {{ transform: rotate(360deg); }}
        }}
        .btn {{
          background: #7C3AED;
          color: white;
          border: none;
          padding: 12px 32px;
          font-size: 16px;
          font-weight: 600;
          border-radius: 8px;
          cursor: pointer;
          transition: background 0.2s;
        }}
        .btn:hover {{
          background: #6D28D9;
        }}
      </style>
      <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    </head>
    <body>
      <div class="container">
        <div style="display: flex; justify-content: center;">
          <div class="spinner"></div>
        </div>
        <h3>Secure Payment</h3>
        <p>Opening Razorpay Secure Checkout...</p>
        <button class="btn" id="pay-btn">Pay Manually</button>
      </div>
      <script>
        var options = {{
          "key": "{settings.RAZORPAY_KEY_ID}",
          "amount": "{amount_paise}",
          "currency": "INR",
          "name": "Troupe",
          "description": "Trip Reservation Payment",
          "order_id": "{razorpay_order_id}",
          "handler": function (response){{
            var redir = "{redirect_url}?status=success&payment_id=" + encodeURIComponent(response.razorpay_payment_id) + "&order_id=" + encodeURIComponent(response.razorpay_order_id);
            window.location.href = redir;
          }},
          "prefill": {{
            "name": "{user_name}",
            "email": "{user_email}",
            "contact": "{user_phone}"
          }},
          "theme": {{
            "color": "#7C3AED"
          }},
          "modal": {{
            "ondismiss": function(){{
              window.location.href = "{redirect_url}?status=cancelled";
            }}
          }}
        }};
        var rzp1 = new Razorpay(options);
        rzp1.on('payment.failed', function (response){{
          window.location.href = "{redirect_url}?status=failed&error=" + encodeURIComponent(response.error.description || "Payment failed");
        }});
        window.onload = function() {{
          setTimeout(function() {{
            rzp1.open();
          }}, 500);
        }};
        document.getElementById('pay-btn').onclick = function(e){{
          rzp1.open();
          e.preventDefault();
        }}
      </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
