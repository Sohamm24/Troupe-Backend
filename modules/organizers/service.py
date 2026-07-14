import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from modules.organizers.models import OrganizerProfile
from modules.users.models import User
from modules.organizers.schemas import OrganizerResponse, OrganizerUpdateRequest, OrganizerListResponse
from modules.trips.schemas import TripListResponse
from modules.trips.service import _trip_to_response
from modules.organizers.repository import get_organizer_by_id, update_organizer, get_organizers_query, get_organizer_trips_query
from uuid import UUID

logger = logging.getLogger("travel_platform")

def _organizer_to_response(org: OrganizerProfile) -> OrganizerResponse:
    return OrganizerResponse(
        organizer_id=str(org.organizer_id),
        user_id=str(org.user_id),
        name=org.user.name if org.user else None,
        bio=org.bio,
        verification_status=org.verification_status,
        profile_pic=org.user.profile_pic if org.user else None,
        region=org.region,
        ratings=org.ratings,
        trip_count=len(org.trips) if org.trips else 0,
        created_at=org.created_at,
    )

def process_list_organizers(page: int, search: str, region: str, verified: bool, db: Session):
    per_page = 20
    query = get_organizers_query(db)

    if search:
        query = query.join(User).filter(User.name.ilike(f"%{search}%"))
    if region:
        query = query.filter(OrganizerProfile.region.ilike(f"%{region}%"))
    if verified is not None:
        query = query.filter(OrganizerProfile.verification_status == verified)

    total = query.count()
    organizers = query.offset((page - 1) * per_page).limit(per_page).all()

    seen = set()
    unique_organizers = []
    for org in organizers:
        if org.organizer_id not in seen:
            seen.add(org.organizer_id)
            unique_organizers.append(org)

    return OrganizerListResponse(
        organizers=[_organizer_to_response(o) for o in unique_organizers],
        page=page,
        total=total,
    )

def process_get_organizer(organizer_id: str, db: Session):
    organizer = get_organizer_by_id(db, organizer_id)
    if not organizer:
        raise HTTPException(status_code=404, detail="Organizer not found")
    return _organizer_to_response(organizer)

def process_update_organizer(organizer_id: str, payload: OrganizerUpdateRequest, current_user: User, db: Session):
    organizer = get_organizer_by_id(db, organizer_id)
    if not organizer:
        raise HTTPException(status_code=404, detail="Organizer not found")
    if organizer.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own organizer profile",
        )

    if payload.bio is not None: organizer.bio = payload.bio
    if payload.region is not None: organizer.region = payload.region
    if payload.profile_pic is not None and organizer.user:
        organizer.user.profile_pic = payload.profile_pic

    update_organizer(db, organizer)
    logger.info(f"Organizer {organizer_id} profile updated")
    return _organizer_to_response(organizer)

def process_get_organizer_trips(organizer_id: UUID, page: int, db: Session):
    per_page = 20
    query = get_organizer_trips_query(db, organizer_id)
    total = query.count()
    trips = query.offset((page - 1) * per_page).limit(per_page).all()

    return TripListResponse(
        trips=[_trip_to_response(t) for t in trips],
        page=page,
        total=total,
    )
