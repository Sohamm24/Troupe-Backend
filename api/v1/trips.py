"""
api/v1/trips.py
---------------
Trip CRUD, interest management, itinerary, and FAQ endpoints.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from database import get_db
from core.dependencies import get_current_user, require_organizer
from models.user import User
from models.organizer import OrganizerProfile
from models.trip import Trip
from models.itinerary import Itinerary
from models.interest import InterestedTrip
from models.discussion import Discussion
from schemas.trip import (
    TripCreateRequest,
    TripUpdateRequest,
    TripResponse,
    TripDetailResponse,
    TripListResponse,
    TripOrganizerInfo,
)
from schemas.itinerary import ItineraryResponse, ItineraryUpdateRequest

router = APIRouter()
logger = logging.getLogger("travel_platform")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trip_to_response(trip: Trip) -> TripResponse:
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


def _trip_to_detail(trip: Trip, user_id=None, db: Session = None) -> TripDetailResponse:
    base = _trip_to_response(trip)

    itinerary_data = None
    if trip.itinerary:
        itinerary_data = trip.itinerary.itinerary

    discussion_id = None
    if trip.discussions:
        discussion_id = str(trip.discussions[0].discussion_id)

    is_interested = False
    if user_id and db:
        interest = (
            db.query(InterestedTrip)
            .filter(
                InterestedTrip.user_id == user_id,
                InterestedTrip.trip_id == trip.trip_id,
            )
            .first()
        )
        is_interested = interest is not None

    return TripDetailResponse(
        **base.model_dump(),
        itinerary=itinerary_data,
        discussion_id=discussion_id,
        is_interested=is_interested,
    )


def _load_trip(trip_id: str, db: Session) -> Trip:
    trip = (
        db.query(Trip)
        .options(
            joinedload(Trip.organizer).joinedload(OrganizerProfile.user),
            joinedload(Trip.organizer).joinedload(OrganizerProfile.trips),
            joinedload(Trip.itinerary),
            joinedload(Trip.discussions),
        )
        .filter(Trip.trip_id == trip_id)
        .first()
    )
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    return trip


# ── TRIP CRUD ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
def create_trip(
    payload: TripCreateRequest,
    organizer_data=Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """Create a new trip. Only organizers can create trips."""
    current_user, organizer = organizer_data

    # Build location dict
    location_data = None
    if payload.location:
        location_data = payload.location.model_dump()

    # Build FAQ list
    faq_data = [faq.model_dump() for faq in payload.frequently_asked] if payload.frequently_asked else []

    new_trip = Trip(
        organizer_id=organizer.organizer_id,
        title=payload.title,
        location=location_data,
        start_date=payload.start_date,
        end_date=payload.end_date,
        is_one_day_trip=payload.is_one_day_trip,
        budget=payload.budget,
        confirmation_amount=payload.confirmation_amount,
        max_travellers=payload.max_travellers,
        description=payload.description,
        frequently_asked=faq_data,
    )
    db.add(new_trip)
    db.flush()

    # Create itinerary if provided
    if payload.itinerary:
        itinerary_data = [day.model_dump() for day in payload.itinerary]
        itin = Itinerary(trip_id=new_trip.trip_id, itinerary=itinerary_data)
        db.add(itin)

    # Auto-create a discussion room for the trip
    discussion = Discussion(trip_id=new_trip.trip_id)
    db.add(discussion)

    db.commit()
    logger.info(f"Trip created: {new_trip.trip_id} by organizer {organizer.organizer_id}")

    trip = _load_trip(str(new_trip.trip_id), db)
    return _trip_to_response(trip)


@router.get("/", response_model=TripListResponse)
def list_trips(
    page: int = Query(1, ge=1),
    search: str = Query(None),
    category: str = Query(None),
    minBudget: int = Query(None),
    maxBudget: int = Query(None),
    location: str = Query(None),
    startDate: date = Query(None),
    sort: str = Query("newest"),
    db: Session = Depends(get_db),
):
    """Infinite feed endpoint — paginated trip listing with filters."""
    per_page = 20
    query = (
        db.query(Trip)
        .options(
            joinedload(Trip.organizer).joinedload(OrganizerProfile.user),
            joinedload(Trip.organizer).joinedload(OrganizerProfile.trips),
        )
    )

    # ── Filters ───────────────────────────────────────────────────────────
    if search:
        query = query.filter(Trip.title.ilike(f"%{search}%"))

    if minBudget is not None:
        query = query.filter(Trip.budget >= minBudget)

    if maxBudget is not None:
        query = query.filter(Trip.budget <= maxBudget)

    if startDate:
        query = query.filter(Trip.start_date >= startDate)

    # ── Sorting ───────────────────────────────────────────────────────────
    if sort == "budget_asc":
        query = query.order_by(Trip.budget.asc())
    elif sort == "budget_desc":
        query = query.order_by(Trip.budget.desc())
    elif sort == "popular":
        query = query.order_by(Trip.interested_count.desc())
    elif sort == "date":
        query = query.order_by(Trip.start_date.asc())
    else:
        query = query.order_by(Trip.created_at.desc())

    total = query.count()
    trips = query.offset((page - 1) * per_page).limit(per_page).all()

    # Deduplicate (joinedload can cause duplicates)
    seen = set()
    unique_trips = []
    for trip in trips:
        if trip.trip_id not in seen:
            seen.add(trip.trip_id)
            unique_trips.append(trip)

    return TripListResponse(
        trips=[_trip_to_response(t) for t in unique_trips],
        page=page,
        total=total,
    )


@router.get("/{trip_id}", response_model=TripDetailResponse)
def get_trip(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get full trip details including itinerary, FAQs, organizer, and interest status."""
    trip = _load_trip(trip_id, db)
    return _trip_to_detail(trip, user_id=current_user.user_id, db=db)


@router.patch("/{trip_id}", response_model=TripResponse)
def update_trip(
    trip_id: str,
    payload: TripUpdateRequest,
    organizer_data=Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """Update trip information. Only the owning organizer can update."""
    current_user, organizer = organizer_data
    trip = _load_trip(trip_id, db)

    if trip.organizer_id != organizer.organizer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own trips",
        )

    if payload.title is not None:
        trip.title = payload.title
    if payload.location is not None:
        trip.location = payload.location.model_dump()
    if payload.start_date is not None:
        trip.start_date = payload.start_date
    if payload.end_date is not None:
        trip.end_date = payload.end_date
    if payload.is_one_day_trip is not None:
        trip.is_one_day_trip = payload.is_one_day_trip
    if payload.budget is not None:
        trip.budget = payload.budget
    if payload.confirmation_amount is not None:
        trip.confirmation_amount = payload.confirmation_amount
    if payload.max_travellers is not None:
        trip.max_travellers = payload.max_travellers
    if payload.description is not None:
        trip.description = payload.description

    db.commit()
    trip = _load_trip(trip_id, db)
    return _trip_to_response(trip)


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip(
    trip_id: str,
    organizer_data=Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """Delete a trip. Only the owning organizer can delete."""
    current_user, organizer = organizer_data
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.organizer_id != organizer.organizer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own trips",
        )

    db.delete(trip)
    db.commit()
    logger.info(f"Trip {trip_id} deleted by organizer {organizer.organizer_id}")


# ── INTEREST MANAGEMENT ──────────────────────────────────────────────────────

@router.post("/{trip_id}/interested", status_code=status.HTTP_201_CREATED)
def mark_interested(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark the current user as interested in a trip."""
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    existing = (
        db.query(InterestedTrip)
        .filter_by(user_id=current_user.user_id, trip_id=trip.trip_id)
        .first()
    )
    if existing:
        return {"success": True, "message": "Already interested"}

    db.add(InterestedTrip(user_id=current_user.user_id, trip_id=trip.trip_id))
    trip.interested_count += 1
    db.commit()

    return {"success": True, "message": "Marked as interested"}


@router.delete("/{trip_id}/interested")
def remove_interest(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove interest from a trip."""
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    interest = (
        db.query(InterestedTrip)
        .filter_by(user_id=current_user.user_id, trip_id=trip.trip_id)
        .first()
    )
    if interest:
        db.delete(interest)
        trip.interested_count = max(0, trip.interested_count - 1)
        db.commit()

    return {"success": True, "message": "Interest removed"}


@router.get("/{trip_id}/interested")
def list_interested_users(
    trip_id: str,
    db: Session = Depends(get_db),
):
    """List users interested in a trip."""
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    interests = (
        db.query(InterestedTrip)
        .options(joinedload(InterestedTrip.user))
        .filter(InterestedTrip.trip_id == trip.trip_id)
        .order_by(InterestedTrip.created_at.desc())
        .all()
    )

    users = []
    for i in interests:
        if i.user:
            users.append({
                "user_id": str(i.user.user_id),
                "name": i.user.name,
                "interested_at": i.created_at.isoformat() if i.created_at else None,
            })

    return {"success": True, "data": users}


# ── ITINERARY ─────────────────────────────────────────────────────────────────

@router.get("/{trip_id}/itinerary", response_model=ItineraryResponse)
def get_itinerary(trip_id: str, db: Session = Depends(get_db)):
    """Get the itinerary for a trip."""
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    itin = db.query(Itinerary).filter(Itinerary.trip_id == trip.trip_id).first()
    if not itin:
        return ItineraryResponse(trip_id=str(trip.trip_id), itinerary=[])

    return ItineraryResponse(
        itinerary_id=str(itin.itinerary_id),
        trip_id=str(itin.trip_id),
        itinerary=itin.itinerary or [],
    )


@router.patch("/{trip_id}/itinerary", response_model=ItineraryResponse)
def update_itinerary(
    trip_id: str,
    payload: ItineraryUpdateRequest,
    organizer_data=Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """Update or create itinerary for a trip. Organizer only."""
    current_user, organizer = organizer_data

    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.organizer_id != organizer.organizer_id:
        raise HTTPException(status_code=403, detail="You can only manage your own trips")

    itin = db.query(Itinerary).filter(Itinerary.trip_id == trip.trip_id).first()
    if itin:
        itin.itinerary = payload.itinerary
    else:
        itin = Itinerary(trip_id=trip.trip_id, itinerary=payload.itinerary)
        db.add(itin)

    db.commit()
    db.refresh(itin)

    return ItineraryResponse(
        itinerary_id=str(itin.itinerary_id),
        trip_id=str(itin.trip_id),
        itinerary=itin.itinerary,
    )


# ── FAQ ───────────────────────────────────────────────────────────────────────

@router.get("/{trip_id}/faqs")
def get_faqs(trip_id: str, db: Session = Depends(get_db)):
    """Get FAQs for a trip."""
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    return {"success": True, "data": {"frequently_asked": trip.frequently_asked or []}}


@router.patch("/{trip_id}/faqs")
def update_faqs(
    trip_id: str,
    payload: dict,
    organizer_data=Depends(require_organizer),
    db: Session = Depends(get_db),
):
    """Update FAQs for a trip. Organizer only."""
    current_user, organizer = organizer_data

    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.organizer_id != organizer.organizer_id:
        raise HTTPException(status_code=403, detail="You can only manage your own trips")

    trip.frequently_asked = payload.get("frequently_asked", [])
    db.commit()

    return {"success": True, "data": {"frequently_asked": trip.frequently_asked}}
