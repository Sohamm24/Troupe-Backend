from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from datetime import date
from modules.trips.models import Trip
from modules.organizers.models import OrganizerProfile

def get_trip_by_id(db: Session, trip_id: str):
    return db.query(Trip).filter(Trip.trip_id == trip_id).first()

def get_owned_trip(db: Session, trip_id: str, organizer_id: UUID):
    return db.query(Trip).filter(Trip.trip_id == trip_id, Trip.organizer_id == organizer_id).first()

def create_trip(db: Session, trip: Trip):
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip

def update_trip(db: Session, trip: Trip, commit: bool = True):
    if commit:
        db.commit()
        db.refresh(trip)
    return trip

def delete_trip(db: Session, trip: Trip):
    db.delete(trip)
    db.commit()

def get_trip_with_details(db: Session, trip_id: str):
    return (
        db.query(Trip)
        .options(
            joinedload(Trip.organizer).joinedload(OrganizerProfile.user),
            joinedload(Trip.organizer).joinedload(OrganizerProfile.trips),
        )
        .filter(Trip.trip_id == trip_id)
        .first()
    )

def get_confirmed_confirmations_by_user(db: Session, user_id):
    from modules.payment.models import TripConfirmation, TripConfirmationStatus
    
    return (
        db.query(TripConfirmation)
        .options(
            joinedload(TripConfirmation.trip).joinedload(Trip.organizer).joinedload(OrganizerProfile.user)
        )
        .filter(
            TripConfirmation.user_id == user_id,
            TripConfirmation.status == TripConfirmationStatus.CONFIRMED,
        )
        .all()
    )
