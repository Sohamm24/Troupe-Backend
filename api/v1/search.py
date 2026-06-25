"""
api/v1/search.py
----------------
GET /search             — Unified search across trips and organizers
GET /search/trips       — Trip-only search
GET /search/organizers  — Organizer-only search
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models.trip import Trip
from models.organizer import OrganizerProfile
from models.user import User

router = APIRouter()
logger = logging.getLogger("travel_platform")


@router.get("/")
def unified_search(
    q: str = Query(..., min_length=1),
    type: str = Query(None, description="Comma-separated: trip,organizer"),
    db: Session = Depends(get_db),
):
    """Unified search endpoint — searches trips and/or organizers."""
    search_types = set()
    if type:
        search_types = {t.strip().lower() for t in type.split(",")}
    else:
        search_types = {"trip", "organizer"}

    results = {"trips": [], "organizers": []}

    if "trip" in search_types:
        trips = (
            db.query(Trip)
            .options(
                joinedload(Trip.organizer).joinedload(OrganizerProfile.user),
            )
            .filter(Trip.title.ilike(f"%{q}%"))
            .order_by(Trip.created_at.desc())
            .limit(20)
            .all()
        )
        for trip in trips:
            organizer_name = None
            if trip.organizer and trip.organizer.user:
                organizer_name = trip.organizer.user.name
            results["trips"].append({
                "trip_id": str(trip.trip_id),
                "title": trip.title,
                "location": trip.location,
                "start_date": trip.start_date.isoformat() if trip.start_date else None,
                "budget": trip.budget,
                "organizer_name": organizer_name,
                "interested_count": trip.interested_count,
            })

    if "organizer" in search_types:
        organizers = (
            db.query(OrganizerProfile)
            .options(joinedload(OrganizerProfile.user))
            .join(User)
            .filter(User.name.ilike(f"%{q}%"))
            .limit(20)
            .all()
        )
        for org in organizers:
            results["organizers"].append({
                "organizer_id": str(org.organizer_id),
                "name": org.user.name if org.user else None,
                "bio": org.bio,
                "region": org.region,
                "verification_status": org.verification_status,
                "profile_pic": org.profile_pic,
            })

    return {"success": True, "data": results}


@router.get("/trips")
def search_trips(
    q: str = Query("", min_length=0),
    db: Session = Depends(get_db),
):
    """Search trips by title."""
    query = (
        db.query(Trip)
        .options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user))
        .order_by(Trip.created_at.desc())
    )
    if q:
        query = query.filter(Trip.title.ilike(f"%{q}%"))

    trips = query.limit(20).all()

    results = []
    for trip in trips:
        organizer_name = None
        if trip.organizer and trip.organizer.user:
            organizer_name = trip.organizer.user.name
        results.append({
            "trip_id": str(trip.trip_id),
            "title": trip.title,
            "location": trip.location,
            "start_date": trip.start_date.isoformat() if trip.start_date else None,
            "budget": trip.budget,
            "organizer_name": organizer_name,
            "interested_count": trip.interested_count,
        })

    return {"success": True, "data": results}


@router.get("/organizers")
def search_organizers(
    q: str = Query("", min_length=0),
    db: Session = Depends(get_db),
):
    """Search organizers by name."""
    query = (
        db.query(OrganizerProfile)
        .options(joinedload(OrganizerProfile.user))
        .join(User)
    )
    if q:
        query = query.filter(User.name.ilike(f"%{q}%"))

    organizers = query.limit(20).all()

    results = []
    for org in organizers:
        results.append({
            "organizer_id": str(org.organizer_id),
            "name": org.user.name if org.user else None,
            "bio": org.bio,
            "region": org.region,
            "verification_status": org.verification_status,
            "profile_pic": org.profile_pic,
        })

    return {"success": True, "data": results}
