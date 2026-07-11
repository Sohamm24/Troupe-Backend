"""
modules/payment/webhook.py
--------------------------
Razorpay webhook signature verification helper.
The actual route is in router.py; this module provides the raw-body
dependency used to read the request before FastAPI parses it.
"""

from fastapi import Request, HTTPException


async def get_raw_body(request: Request) -> bytes:
    """
    FastAPI dependency that returns the raw request body.
    Must be used BEFORE any body parsing dependency so the bytes are intact
    for Razorpay signature verification.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body")
    return body
