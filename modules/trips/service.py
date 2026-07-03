import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from modules.trips.models import Trip, InterestedTrip, TripStatus
from modules.trips.schemas import (
    TripResponse, TripDetailResponse, TripListResponse, TripOrganizerInfo, ItineraryActivity, ItineraryResponse
)
from modules.trips.repository import (
    get_trip_by_id, get_owned_trip, create_trip, update_trip, delete_trip,
    get_trip_with_details, get_interest, create_interest, delete_interest, get_interests_for_trip
)

logger = logging.getLogger("travel_platform")

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
        title=trip.title,
        thumbnail=trip.thumbnail,
        budget=trip.budget or 0,                           
        confirmation_amount=trip.confirmation_amount or 0,
        max_travellers=trip.max_travellers or 0,          
        confirmed_travellers=trip.confirmed_travellers,
        interested_count=trip.interested_count,
        description=trip.description or "",             
        itinerary=[ItineraryActivity(**item) for item in (trip.itinerary or [])],                      
        frequently_asked=trip.frequently_asked,
        organizer=organizer_info,
        status=trip.status,
        last_completed_step = trip.last_completed_step,
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


def _patch_step(trip_id: str, step_num: int, data: dict, organizer, db: Session) -> Trip:
    trip = get_owned_trip(db, trip_id, organizer.organizer_id)
    if not trip:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    for key, value in data.items():
        setattr(trip, key, value)
    trip.last_completed_step = max(trip.last_completed_step, step_num)
    return update_trip(db, trip)

def process_create_draft(organizer, db: Session):
    trip = Trip(organizer_id=organizer.organizer_id, status=TripStatus.DRAFT)
    trip = create_trip(db, trip)
    return {"trip_id": str(trip.trip_id)}

def process_publish_trip(trip_id: str, organizer, db: Session):
    trip = get_owned_trip(db, trip_id, organizer.organizer_id)
    if not trip:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    if trip.last_completed_step < 6:
        raise HTTPException(status_code=400, detail="Complete all steps before publishing.")
    trip.status = TripStatus.PUBLISHED
    update_trip(db, trip)
    return {"message": "Trip published successfully", "trip_id": str(trip.trip_id), "status": trip.status}

def process_update_trip(trip_id: str, payload, organizer, db: Session):
    trip = get_trip_with_details(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.organizer_id != organizer.organizer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own trips")

    if payload.title is not None: trip.title = payload.title
    if payload.location is not None: trip.location = payload.location.model_dump()
    if payload.start_date is not None: trip.start_date = payload.start_date
    if payload.end_date is not None: trip.end_date = payload.end_date
    if payload.is_one_day_trip is not None: trip.is_one_day_trip = payload.is_one_day_trip
    if payload.budget is not None: trip.budget = payload.budget
    if payload.confirmation_amount is not None: trip.confirmation_amount = payload.confirmation_amount
    if payload.max_travellers is not None: trip.max_travellers = payload.max_travellers
    if payload.description is not None: trip.description = payload.description

    update_trip(db, trip)
    return _trip_to_response(get_trip_with_details(db, trip_id))

def process_delete_trip(trip_id: str, organizer, db: Session):
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    if trip.organizer_id != organizer.organizer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own trips")
    delete_trip(db, trip)
    logger.info(f"Trip {trip_id} deleted by organizer {organizer.organizer_id}")

def process_mark_interested(trip_id: str, user, db: Session):
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    if get_interest(db, trip_id, user.user_id):
        return {"success": True, "message": "Already interested"}
    create_interest(db, InterestedTrip(user_id=user.user_id, trip_id=trip.trip_id))
    trip.interested_count += 1
    update_trip(db, trip)
    return {"success": True, "message": "Marked as interested"}

def process_remove_interest(trip_id: str, user, db: Session):
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    interest = get_interest(db, trip_id, user.user_id)
    if interest:
        delete_interest(db, interest)
        trip.interested_count = max(0, trip.interested_count - 1)
        update_trip(db, trip)
    return {"success": True, "message": "Interest removed"}

def process_list_interested_users(trip_id: str, db: Session):
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    interests = get_interests_for_trip(db, trip_id)
    users = []
    for i in interests:
        if i.user:
            users.append({
                "user_id": str(i.user.user_id),
                "name": i.user.name,
                "interested_at": i.created_at.isoformat() if i.created_at else None,
            })
    return {"success": True, "data": users}
