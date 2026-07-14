import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from modules.users.models import User
from modules.users.schemas import UserResponse, UserUpdateRequest
from modules.trips.schemas import TripResponse
from modules.users.repository import (
    get_user_with_organizer_profile,
    get_organizer_profile_by_user_id,
    create_organizer_profile,
)

logger = logging.getLogger("travel_platform")

def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=str(user.user_id),
        name=user.name,
        email=user.email,
        phone=user.phone,
        profile_pic=user.profile_pic,
        is_organizer=user.organizer_profile is not None,
        organizer_id=str(user.organizer_profile.organizer_id) if user.organizer_profile else None,
        created_at=user.created_at,
    )

def _trip_to_response(trip) -> TripResponse:
    from modules.trips.schemas import TripOrganizerInfo
    organizer_info = None
    if trip.organizer:
        organizer_info = TripOrganizerInfo(
            organizer_id=str(trip.organizer.organizer_id),
            name=trip.organizer.user.name if trip.organizer.user else None,
            profile_pic=trip.organizer.user.profile_pic if trip.organizer.user else None,
            verification_status=trip.organizer.verification_status,
            ratings=float(trip.organizer.ratings) if trip.organizer.ratings else None,
            trip_count=len(trip.organizer.trips) if trip.organizer.trips else 0,
        )
    return TripResponse(
        trip_id=str(trip.trip_id),
        organizer_id=str(trip.organizer_id),
        title=trip.title,
        location=trip.location,
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

def process_get_me(current_user: User, db: Session):
    user = get_user_with_organizer_profile(db, current_user.user_id)
    return _user_to_response(user)

def process_update_me(payload: UserUpdateRequest, current_user: User, db: Session):
    if payload.name is not None:
        current_user.name = payload.name
    if payload.phone is not None:
        current_user.phone = payload.phone
    if payload.profile_pic is not None:
        current_user.profile_pic = payload.profile_pic
    db.commit()
    db.refresh(current_user)
    logger.info(f"User {current_user.user_id} updated profile")
    user = get_user_with_organizer_profile(db, current_user.user_id)
    return _user_to_response(user)

def process_update_name(payload, current_user: User, db: Session):
    current_user.name = payload.name
    db.commit()
    db.refresh(current_user)
    logger.info(f"User {current_user.user_id} updated name to {payload.name}")
    user = get_user_with_organizer_profile(db, current_user.user_id)
    return _user_to_response(user)

def process_become_organizer(current_user: User, db: Session):
    existing = get_organizer_profile_by_user_id(db, current_user.user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already an organizer",
        )
    organizer = create_organizer_profile(db, current_user.user_id)
    logger.info(f"User {current_user.user_id} became organizer {organizer.organizer_id}")
    return {
        "success": True,
        "data": {"organizer_id": str(organizer.organizer_id)},
        "message": "You are now an organizer",
    }


