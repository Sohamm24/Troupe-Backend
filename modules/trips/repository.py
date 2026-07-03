from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from datetime import date
from modules.trips.models import Trip, InterestedTrip
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

def update_trip(db: Session, trip: Trip):
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

def get_interest(db: Session, trip_id: str, user_id: UUID):
    return db.query(InterestedTrip).filter_by(user_id=user_id, trip_id=trip_id).first()

def create_interest(db: Session, interest: InterestedTrip):
    db.add(interest)
    db.commit()
    return interest

def delete_interest(db: Session, interest: InterestedTrip):
    db.delete(interest)
    db.commit()

def get_interests_for_trip(db: Session, trip_id: str):
    return (
        db.query(InterestedTrip)
        .options(joinedload(InterestedTrip.user))
        .filter(InterestedTrip.trip_id == trip_id)
        .order_by(InterestedTrip.created_at.desc())
        .all()
    )
