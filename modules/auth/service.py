from core.security import verify_access_token
import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from modules.auth.repository import get_user_by_email, get_user_by_id, create_user
from modules.users.models import User
from modules.auth.schemas import RegisterRequest, LoginRequest, AuthResponse, RefreshAuthResponse
from core.security import hash_password, verify_password, create_access_token, create_refresh_token, verify_refresh_token

logger = logging.getLogger("travel_platform")

def process_refresh(payload, db: Session):
    try:
        token_data = verify_refresh_token(payload.refresh_token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = get_user_by_id(db, token_data["sub"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists",
        )

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("Token rotated for user_id=%s", token_data["sub"])

    return RefreshAuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )

def process_register(payload: RegisterRequest, db: Session):
    existing = get_user_by_email(db, payload.email)
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
    new_user = create_user(db, new_user)

    token_data = {"sub": str(new_user.user_id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("New user registered: user_id=%s", new_user.user_id)

    return AuthResponse(
        user_id=str(new_user.user_id),
        access_token=access_token,
        refresh_token=refresh_token,
    )

def process_login(payload: LoginRequest, db: Session):
    user = get_user_by_email(db, payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token_data = {"sub": str(user.user_id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("User logged in: user_id=%s", user.user_id)

    return AuthResponse(
        user_id=str(user.user_id),
        access_token=access_token,
        refresh_token=refresh_token,
    )

def process_logout(payload, db: Session):
    if payload.refresh_token:
        try:
            token_data = verify_refresh_token(payload.refresh_token)
            # TTL should match the refresh token's remaining lifetime
            from core.security import REFRESH_TOKEN_EXPIRE_SECONDS, add_token_to_blocklist
            add_token_to_blocklist(payload.refresh_token, ttl_seconds=REFRESH_TOKEN_EXPIRE_SECONDS)
            logger.info("Refresh token revoked for user_id=%s", token_data.get("sub"))
        except ValueError:
            # Token was already invalid — treat as a successful logout
            pass

    return {"success": True, "message": "Logged out successfully"}


def get_user_from_token(access_token: str, db: Session):
    try:
        token_data = verify_access_token(access_token)
        user = get_user_by_id(db, token_data["sub"])
        if not user:
            return None
        return user
    except ValueError:
        return None