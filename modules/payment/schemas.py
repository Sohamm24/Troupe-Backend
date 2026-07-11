"""
modules/payment/schemas.py
--------------------------
Pydantic models for the payment module endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── Hold ─────────────────────────────────────────────────────────────────────

class HoldRequest(BaseModel):
    trip_id: str
    seats_count: int = Field(..., ge=1, le=20)
    idempotency_key: str = Field(..., min_length=8, max_length=255)


class HoldResponse(BaseModel):
    trip_confirmation_id: str
    price_locked: Decimal
    total_amount: Decimal
    hold_expires_at: datetime
    seats_left: int
    razorpay_order_id: str
    razorpay_key_id: str

    model_config = {"from_attributes": True}


# ── Hold Status ───────────────────────────────────────────────────────────────

class HoldStatusResponse(BaseModel):
    trip_confirmation_id: str
    status: str                        # pending_payment | confirmed | expired | failed | cancelled
    hold_expires_at: Optional[datetime] = None
    price_locked: Decimal
    seats_count: int

    model_config = {"from_attributes": True}
