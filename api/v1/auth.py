"""
api/v1/auth.py
--------------
POST /auth/register   — Create a new account
POST /auth/login      — Login and receive JWT
POST /auth/refresh    — Rotate access + refresh tokens
POST /auth/logout     — Logout (client-side token discard)
"""

from core.security import verify_refresh_token
from schemas.auth import RefreshAuthRequest, RefreshAuthResponse
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.database import get_db
from models.user import User
from schemas.auth import RegisterRequest, LoginRequest, AuthResponse
from core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token   
)

router = APIRouter()
logger = logging.getLogger("travel_platform")


@router.post(
    "/refresh",
    response_model=RefreshAuthResponse,
    status_code=status.HTTP_200_OK,
)
def refresh(payload: RefreshAuthRequest, db: Session = Depends(get_db)):
    # Validate the refresh token signature and expiry
    try:
        token_data = verify_refresh_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # verify the user still exists; deleted accounts must not be able to refresh
    user = db.query(User).filter(User.user_id == token_data["sub"]).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists",
        )

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # log user_id, not email (avoid PII in logs)
    logger.info("Token rotated for user_id=%s", token_data["sub"])

    return RefreshAuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account and return JWT tokens."""

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    new_user = User(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token_data = {"sub": str(new_user.user_id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # log user_id instead of email (PII)
    logger.info("New user registered: user_id=%s", new_user.user_id)

    return AuthResponse(
        user_id=str(new_user.user_id),
        token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return JWT tokens."""

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token_data = {"sub": str(user.user_id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # log user_id instead of email (PII)
    logger.info("User logged in: user_id=%s", user.user_id)

    return AuthResponse(
        user_id=str(user.user_id),
        token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/logout")
def logout(payload: RefreshAuthRequest, db: Session = Depends(get_db)):
    """
    Fix #7 — Invalidate the refresh token server-side so stolen tokens cannot
    be used to obtain new access tokens after logout.

    Implementation requires `add_token_to_blocklist` in core/security.py:

        def add_token_to_blocklist(token: str, ttl_seconds: int) -> None:
            # Store jti (or full token hash) in Redis with TTL = refresh token max age
            redis_client.setex(f"blocklist:{hash_token(token)}", ttl_seconds, "1")

        def verify_refresh_token(token: str) -> dict:
            ...
            if redis_client.exists(f"blocklist:{hash_token(token)}"):
                raise ValueError("Token has been revoked")
            ...

    If Redis is not available, a DB-backed blocklist table is an acceptable fallback.
    """
    if payload.refresh_token:
        try:
            token_data = verify_refresh_token(payload.refresh_token)
            # TTL should match the refresh token's remaining lifetime
            from backend.core.security import REFRESH_TOKEN_EXPIRE_SECONDS
            add_token_to_blocklist(payload.refresh_token, ttl_seconds=REFRESH_TOKEN_EXPIRE_SECONDS)
            logger.info("Refresh token revoked for user_id=%s", token_data.get("sub"))
        except ValueError:
            # Token was already invalid — treat as a successful logout
            pass

    return {"success": True, "message": "Logged out successfully"}