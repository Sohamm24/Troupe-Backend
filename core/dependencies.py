"""
core/dependencies.py
--------------------
Reusable FastAPI dependencies for authentication and authorisation.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_token

security_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db),
):
    """
    Extract and validate the JWT from the Authorization header.
    Returns the User ORM object.
    """
    from models.user import User  # deferred import to avoid circular deps

    token = credentials.credentials
    payload = decode_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def require_organizer(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Dependency that ensures the current user has an organizer profile.
    Returns a tuple of (user, organizer_profile).
    """
    from models.organizer import OrganizerProfile  # deferred import

    organizer = (
        db.query(OrganizerProfile)
        .filter(OrganizerProfile.user_id == current_user.user_id)
        .first()
    )
    if not organizer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be an organizer to perform this action",
        )
    return current_user, organizer
