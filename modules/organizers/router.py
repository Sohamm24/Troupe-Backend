from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from core.database import get_db
from core.dependencies import get_current_user
from modules.users.models import User
from modules.organizers.schemas import OrganizerResponse, OrganizerUpdateRequest, OrganizerListResponse
from modules.trips.schemas import TripListResponse
from modules.organizers.service import (
    process_list_organizers, process_get_organizer, process_update_organizer, process_get_organizer_trips
)
from uuid import UUID

router = APIRouter()

@router.get("/", response_model=OrganizerListResponse)
def list_organizers(
    page: int = Query(1, ge=1), search: str = Query(None), region: str = Query(None),
    verified: bool = Query(None), db: Session = Depends(get_db),
):
    return process_list_organizers(page, search, region, verified, db)

@router.get("/{organizer_id}", response_model=OrganizerResponse)
def get_organizer(organizer_id: str, db: Session = Depends(get_db)):
    return process_get_organizer(organizer_id, db)

@router.patch("/{organizer_id}", response_model=OrganizerResponse)
def update_organizer(
    organizer_id: str, payload: OrganizerUpdateRequest,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return process_update_organizer(organizer_id, payload, current_user, db)

@router.get("/{organizer_id}/trips", response_model=TripListResponse)
def get_organizer_trips(
    organizer_id: UUID, page: int = Query(1, ge=1), db: Session = Depends(get_db),
):
    return process_get_organizer_trips(organizer_id, page, db)
