from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from core.database import get_db
from core.dependencies import get_current_user
from modules.users.models import User
from modules.users.schemas import UserResponse, UserUpdateRequest
from modules.trips.schemas import TripResponse
from modules.users.service import (
    process_get_me,
    process_update_me,
    process_become_organizer,
)

router = APIRouter()

@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return process_get_me(current_user, db)

@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return process_update_me(payload, current_user, db)

@router.post("/become-organizer", status_code=status.HTTP_201_CREATED)
def become_organizer(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return process_become_organizer(current_user, db)

@router.get("/me/upcoming-trips", response_model=list[TripResponse])
def get_upcoming_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return []

@router.get("/me/past-trips", response_model=list[TripResponse])
def get_past_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return []

@router.get("/me/interested-trips", response_model=list[TripResponse])
def get_interested_trips(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return []
