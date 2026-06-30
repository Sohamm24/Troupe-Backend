"""
api/v1/users.py
---------------
GET    /users/me                — Current user profile
PATCH  /users/me                — Update profile (name, phone)
POST   /users/become-organizer  — Convert user to organizer
GET    /users/me/upcoming-trips — User's confirmed upcoming trips
GET    /users/me/past-trips     — User's past trips
GET    /users/me/interested-trips — Trips user marked interested
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from core.database import get_db
from core.dependencies import get_current_user
from models.user import User
from models.organizer import OrganizerProfile
from models.trip import Trip
from models.interest import InterestedTrip
from schemas.user import UserResponse, UserUpdateRequest
from schemas.trip import TripResponse

router = APIRouter()
logger = logging.getLogger("travel_platform")


def _user_to_response(user: User) -> UserResponse:
    """Convert User ORM object to UserResponse, adding is_organizer flag."""
    return UserResponse(
        user_id=str(user.user_id),
        name=user.name,
        email=user.email,
        phone=user.phone,
        is_organizer=user.organizer_profile is not None,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's profile."""
    # Re-query to ensure organizer_profile is loaded
    user = (
        db.query(User)
        .options(joinedload(User.organizer_profile))
        .filter(User.user_id == current_user.user_id)
        .first()
    )
    return _user_to_response(user)


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user's profile info."""
    if payload.name is not None:
        current_user.name = payload.name
    if payload.phone is not None:
        current_user.phone = payload.phone

    db.commit()
    db.refresh(current_user)
    logger.info(f"User {current_user.user_id} updated profile")

    user = (
        db.query(User)
        .options(joinedload(User.organizer_profile))
        .filter(User.user_id == current_user.user_id)
        .first()
    )
    return _user_to_response(user)


@router.post("/become-organizer", status_code=status.HTTP_201_CREATED)
def become_organizer(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Convert current user account into an organizer account."""
    existing = (
        db.query(OrganizerProfile)
        .filter(OrganizerProfile.user_id == current_user.user_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already an organizer",
        )

    organizer = OrganizerProfile(user_id=current_user.user_id)
    db.add(organizer)
    db.commit()
    db.refresh(organizer)

    logger.info(f"User {current_user.user_id} became organizer {organizer.organizer_id}")
    return {
        "success": True,
        "data": {"organizer_id": str(organizer.organizer_id)},
        "message": "You are now an organizer",
    }


@router.get("/me/upcoming-trips", response_model=list[TripResponse])
def get_upcoming_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return trips the user is interested in that haven't started yet."""
    today = date.today()
    trips = (
        db.query(Trip)
        .join(InterestedTrip)
        .options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user))
        .filter(
            InterestedTrip.user_id == current_user.user_id,
            Trip.start_date >= today,
        )
        .order_by(Trip.start_date.asc())
        .all()
    )
    return [_trip_to_response(t) for t in trips]


@router.get("/me/past-trips", response_model=list[TripResponse])
def get_past_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return trips the user was interested in that have already ended."""
    today = date.today()
    trips = (
        db.query(Trip)
        .join(InterestedTrip)
        .options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user))
        .filter(
            InterestedTrip.user_id == current_user.user_id,
            Trip.start_date < today,
        )
        .order_by(Trip.start_date.desc())
        .all()
    )
    return [_trip_to_response(t) for t in trips]


@router.get("/me/interested-trips", response_model=list[TripResponse])
def get_interested_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all trips the user has marked as interested."""
    trips = (
        db.query(Trip)
        .join(InterestedTrip)
        .options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user))
        .filter(InterestedTrip.user_id == current_user.user_id)
        .order_by(Trip.start_date.desc())
        .all()
    )
    return [_trip_to_response(t) for t in trips]


# ── Helper ────────────────────────────────────────────────────────────────────

def _trip_to_response(trip: Trip) -> TripResponse:
    """Convert Trip ORM to TripResponse with embedded organizer info."""
    from schemas.trip import TripOrganizerInfo

    organizer_info = None
    if trip.organizer:
        organizer_info = TripOrganizerInfo(
            organizer_id=str(trip.organizer.organizer_id),
            name=trip.organizer.user.name if trip.organizer.user else None,
            profile_pic=trip.organizer.profile_pic,
            verification_status=trip.organizer.verification_status,
            ratings=float(trip.organizer.ratings) if trip.organizer.ratings else None,
            trip_count=len(trip.organizer.trips) if trip.organizer.trips else 0,
        )

    return TripResponse(
        trip_id=str(trip.trip_id),
        organizer_id=str(trip.organizer_id),
        title=trip.title,
        location=trip.location,
        start_date=trip.start_date,
        end_date=trip.end_date,
        is_one_day_trip=trip.is_one_day_trip,
        budget=trip.budget,
        confirmation_amount=trip.confirmation_amount,
        max_travellers=trip.max_travellers,
        confirmed_travellers=trip.confirmed_travellers,
        interested_count=trip.interested_count,
        description=trip.description,
        frequently_asked=trip.frequently_asked,
        organizer=organizer_info,
        created_at=trip.created_at,
    )
