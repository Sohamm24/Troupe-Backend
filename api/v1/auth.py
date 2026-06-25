"""
api/v1/auth.py
--------------
POST /auth/register   — Create a new account
POST /auth/login      — Login and receive JWT
POST /auth/logout     — Logout (client-side token discard)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from schemas.auth import RegisterRequest, LoginRequest, AuthResponse
from core.security import hash_password, verify_password, create_access_token, create_refresh_token

router = APIRouter()
logger = logging.getLogger("travel_platform")


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account and return JWT tokens."""

    # Check if email already exists
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # Create user
    new_user = User(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Generate tokens
    token_data = {"sub": str(new_user.user_id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info(f"New user registered: {new_user.email}")

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

    logger.info(f"User logged in: {user.email}")

    return AuthResponse(
        user_id=str(user.user_id),
        token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/logout")
def logout():
    """
    Logout — for stateless JWT this is handled client-side by discarding the token.
    This endpoint exists for API completeness.
    """
    return {"success": True, "message": "Logged out successfully"}
