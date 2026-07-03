from sqlalchemy.orm import Session
from modules.trips.models import Trip
from modules.users.models import User

def get_trip_for_upload(db: Session, trip_id: str):
    return db.query(Trip).filter(Trip.trip_id == trip_id).first()

def save_trip_changes(db: Session, trip: Trip):
    db.commit()
    db.refresh(trip)
    return trip
