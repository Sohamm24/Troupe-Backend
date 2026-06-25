"""
api/v1/organizers.py
--------------------
GET   /organizers              — List/search organizers
GET   /organizers/{id}         — Organizer profile + trips
PATCH /organizers/{id}         — Update organizer profile (owner only)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from database import get_db
from core.dependencies import get_current_user
from models.user import User
from models.organizer import OrganizerProfile
from models.trip import Trip
from schemas.organizer import OrganizerResponse, OrganizerUpdateRequest, OrganizerListResponse

router = APIRouter()
logger = logging.getLogger("travel_platform")


def _organizer_to_response(org: OrganizerProfile) -> OrganizerResponse:
    """Convert OrganizerProfile ORM to response schema."""
    return OrganizerResponse(
        organizer_id=str(org.organizer_id),
        user_id=str(org.user_id),
        name=org.user.name if org.user else None,
        bio=org.bio,
        verification_status=org.verification_status,
        profile_pic=org.profile_pic,
        region=org.region,
        ratings=org.ratings,
        trip_count=len(org.trips) if org.trips else 0,
        created_at=org.created_at,
    )


@router.get("/", response_model=OrganizerListResponse)
def list_organizers(
    page: int = Query(1, ge=1),
    search: str = Query(None),
    region: str = Query(None),
    verified: bool = Query(None),
    db: Session = Depends(get_db),
):
    """List organizers with optional search, region, and verification filters."""
    per_page = 20
    query = (
        db.query(OrganizerProfile)
        .options(
            joinedload(OrganizerProfile.user),
            joinedload(OrganizerProfile.trips),
        )
    )

    if search:
        query = query.join(User).filter(User.name.ilike(f"%{search}%"))

    if region:
        query = query.filter(OrganizerProfile.region.ilike(f"%{region}%"))

    if verified is not None:
        query = query.filter(OrganizerProfile.verification_status == verified)

    total = query.count()
    organizers = (
        query
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Deduplicate (joinedload can cause duplicates)
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


@router.get("/{organizer_id}", response_model=OrganizerResponse)
def get_organizer(
    organizer_id: str,
    db: Session = Depends(get_db),
):
    """Get a specific organizer's profile with their trips."""
    organizer = (
        db.query(OrganizerProfile)
        .options(
            joinedload(OrganizerProfile.user),
            joinedload(OrganizerProfile.trips),
        )
        .filter(OrganizerProfile.organizer_id == organizer_id)
        .first()
    )
    if not organizer:
        raise HTTPException(status_code=404, detail="Organizer not found")

    return _organizer_to_response(organizer)


@router.patch("/{organizer_id}", response_model=OrganizerResponse)
def update_organizer(
    organizer_id: str,
    payload: OrganizerUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update organizer profile. Only the profile owner can update."""
    organizer = (
        db.query(OrganizerProfile)
        .options(
            joinedload(OrganizerProfile.user),
            joinedload(OrganizerProfile.trips),
        )
        .filter(OrganizerProfile.organizer_id == organizer_id)
        .first()
    )
    if not organizer:
        raise HTTPException(status_code=404, detail="Organizer not found")

    if organizer.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own organizer profile",
        )

    if payload.bio is not None:
        organizer.bio = payload.bio
    if payload.region is not None:
        organizer.region = payload.region
    if payload.profile_pic is not None:
        organizer.profile_pic = payload.profile_pic

    db.commit()
    db.refresh(organizer)
    logger.info(f"Organizer {organizer_id} profile updated")

    return _organizer_to_response(organizer)
