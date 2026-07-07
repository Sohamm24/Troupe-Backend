from sqlalchemy.orm import Session, joinedload
from datetime import date
from modules.users.models import User
from modules.organizers.models import OrganizerProfile
from modules.trips.models import Trip

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

