from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from core.database import get_db
from core.dependencies import get_current_user, require_organizer
from modules.users.models import User
from modules.trips.service import (
    _patch_step, process_create_draft, process_publish_trip, process_update_trip, process_delete_trip, _trip_to_response,
    get_confirmation_data, process_get_confirmed_trips
)
from modules.trips.schemas import (
    TripUpdateRequest, TripResponse, TripListResponse, 
    Step1BasicInfo, Step2Itinerary, Step3Inclusions, Step4Pricing, Step5TargetAudience, Step6Description,
    ItineraryResponse, ItineraryUpdateRequest, TripConfirmationDataResponse
)
from modules.trips.repository import update_trip, get_trip_by_id
from modules.trips.models import Trip
from sqlalchemy.orm import joinedload
from modules.organizers.models import OrganizerProfile
from datetime import date

router = APIRouter()

@router.post("/draft", status_code=201)
async def create_empty_draft(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    organizer = current_user.organizer_profile
    if not organizer: raise HTTPException(status_code=403, detail="Organizer profile not found")
    return process_create_draft(organizer, db)

@router.patch("/{trip_id}/step1")
def update_basic_info(trip_id: str, payload: Step1BasicInfo, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    _patch_step(trip_id, 1, payload.model_dump(), organizer, db)

@router.patch("/{trip_id}/step2")
def update_itinerary(trip_id: str, payload: Step2Itinerary, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    _patch_step(trip_id, 2, {"itinerary": [a.model_dump(mode="json") for a in payload.itinerary]}, organizer, db)

@router.patch("/{trip_id}/step3")
def update_inclusions(trip_id: str, payload: Step3Inclusions, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    _patch_step(trip_id, 3, {"inclusions": payload.inclusions.model_dump()}, organizer, db)

@router.patch("/{trip_id}/step4")
def update_pricing(trip_id: str, payload: Step4Pricing, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    _patch_step(trip_id, 4, payload.model_dump(), organizer, db)

@router.patch("/{trip_id}/step5")
def update_audience(trip_id: str, payload: Step5TargetAudience, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    _patch_step(trip_id, 5, {"categories": [c.value for c in payload.categories]}, organizer, db)

@router.patch("/{trip_id}/step6")
def update_description(trip_id: str, payload: Step6Description, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    _patch_step(trip_id, 6, {"description": payload.description, "frequently_asked": [f.model_dump() for f in (payload.frequently_asked or [])]}, organizer, db)

@router.post("/{trip_id}/publish")
def publish_trip(trip_id: str, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    return process_publish_trip(trip_id, organizer, db)

@router.get("/", response_model=TripListResponse)
def list_trips(
    page: int = Query(1, ge=1), search: str = Query(None), category: str = Query(None),
    minBudget: int = Query(None), maxBudget: int = Query(None), location: str = Query(None),
    startDate: date = Query(None), sort: str = Query("newest"), db: Session = Depends(get_db),
):
    per_page = 20
    query = db.query(Trip).options(
        joinedload(Trip.organizer).joinedload(OrganizerProfile.user),
        joinedload(Trip.organizer).joinedload(OrganizerProfile.trips),
    )
    if search: query = query.filter(Trip.title.ilike(f"%{search}%"))
    if minBudget is not None: query = query.filter(Trip.budget >= minBudget)
    if maxBudget is not None: query = query.filter(Trip.budget <= maxBudget)
    if startDate: query = query.filter(Trip.start_date >= startDate)
    
    if sort == "budget_asc": query = query.order_by(Trip.budget.asc())
    elif sort == "budget_desc": query = query.order_by(Trip.budget.desc())
    elif sort == "popular": query = query.order_by(Trip.interested_count.desc())
    elif sort == "date": query = query.order_by(Trip.start_date.asc())
    else: query = query.order_by(Trip.created_at.desc())
    
    total = query.count()
    trips = query.offset((page - 1) * per_page).limit(per_page).all()
    seen = set()
    unique_trips = []
    for trip in trips:
        if trip.trip_id not in seen:
            seen.add(trip.trip_id)
            unique_trips.append(trip)
            
    return TripListResponse(trips=[_trip_to_response(t) for t in unique_trips], page=page, total=total)

@router.get("/confirmed", response_model=List[TripResponse])
def get_confirmed_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return process_get_confirmed_trips(current_user.user_id, db)

@router.get("/{trip_id}", response_model=TripResponse)
def get_trip_details(trip_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user)).first()
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    return _trip_to_response(trip)

@router.patch("/{trip_id}", response_model=TripResponse)
def patch_trip(trip_id: str, payload: TripUpdateRequest, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    return process_update_trip(trip_id, payload, organizer, db)

@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_trip(trip_id: str, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    return process_delete_trip(trip_id, organizer, db)

@router.get("/{trip_id}/itinerary", response_model=ItineraryResponse)
def get_itinerary(trip_id: str, db: Session = Depends(get_db)):
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    return ItineraryResponse(trip_id=str(trip.trip_id), itinerary=trip.itinerary or [])

@router.patch("/{trip_id}/itinerary", response_model=ItineraryResponse)
def patch_itinerary(trip_id: str, payload: ItineraryUpdateRequest, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    if trip.organizer_id != organizer.organizer_id: raise HTTPException(status_code=403, detail="You can only manage your own trips")
    trip.itinerary = payload.itinerary
    update_trip(db, trip)
    return ItineraryResponse(trip_id=str(trip.trip_id), itinerary=trip.itinerary or [])

@router.get("/{trip_id}/faqs")
def get_faqs(trip_id: str, db: Session = Depends(get_db)):
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    return {"success": True, "data": {"frequently_asked": trip.frequently_asked or []}}

@router.patch("/{trip_id}/faqs")
def patch_faqs(trip_id: str, payload: dict, organizer_data=Depends(require_organizer), db: Session = Depends(get_db)):
    _, organizer = organizer_data
    trip = get_trip_by_id(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    if trip.organizer_id != organizer.organizer_id: raise HTTPException(status_code=403, detail="You can only manage your own trips")
    trip.frequently_asked = payload.get("frequently_asked", [])
    update_trip(db, trip)
    return {"success": True, "data": {"frequently_asked": trip.frequently_asked}}


@router.get("/{trip_id}/confirmation-data", response_model=TripConfirmationDataResponse)
def get_trip_confirmation_data(
    trip_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Read-only snapshot of price and availability for the confirmation page.
    Nothing is locked or charged here.
    """
    return get_confirmation_data(trip_id, db)
