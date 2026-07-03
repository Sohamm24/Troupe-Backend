from sqlalchemy.orm import Session, joinedload
from datetime import date
from modules.users.models import User
from modules.organizers.models import OrganizerProfile
from modules.trips.models import Trip, InterestedTrip

def get_user_with_organizer_profile(db: Session, user_id: str):
    return db.query(User).options(joinedload(User.organizer_profile)).filter(User.user_id == user_id).first()

def get_organizer_profile_by_user_id(db: Session, user_id: str):
    return db.query(OrganizerProfile).filter(OrganizerProfile.user_id == user_id).first()

def create_organizer_profile(db: Session, user_id: str):
    organizer = OrganizerProfile(user_id=user_id)
    db.add(organizer)
    db.commit()
    db.refresh(organizer)
    return organizer

def get_upcoming_trips_for_user(db: Session, user_id: str):
    today = date.today()
    return (
        db.query(Trip)
        .join(InterestedTrip)
        .options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user))
        .filter(
            InterestedTrip.user_id == user_id,
            Trip.start_date >= today,
        )
        .order_by(Trip.start_date.asc())
        .all()
    )

def get_past_trips_for_user(db: Session, user_id: str):
    today = date.today()
    return (
        db.query(Trip)
        .join(InterestedTrip)
        .options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user))
        .filter(
            InterestedTrip.user_id == user_id,
            Trip.start_date < today,
        )
        .order_by(Trip.start_date.desc())
        .all()
    )

def get_interested_trips_for_user(db: Session, user_id: str):
    return (
        db.query(Trip)
        .join(InterestedTrip)
        .options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user))
        .filter(InterestedTrip.user_id == user_id)
        .order_by(Trip.start_date.desc())
        .all()
    )
