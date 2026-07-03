from sqlalchemy.orm import Session, joinedload
from modules.users.models import User
from modules.organizers.models import OrganizerProfile
from modules.trips.models import Trip
from uuid import UUID

def get_organizers_query(db: Session):
    return db.query(OrganizerProfile).options(
        joinedload(OrganizerProfile.user),
        joinedload(OrganizerProfile.trips),
    )

def get_organizer_by_id(db: Session, organizer_id: str):
    return get_organizers_query(db).filter(OrganizerProfile.organizer_id == organizer_id).first()

def update_organizer(db: Session, organizer: OrganizerProfile):
    db.commit()
    db.refresh(organizer)
    return organizer

def get_organizer_trips_query(db: Session, organizer_id: UUID):
    return (
        db.query(Trip)
        .filter(Trip.organizer_id == organizer_id)
        .options(
            joinedload(Trip.organizer).joinedload(OrganizerProfile.user),
            joinedload(Trip.organizer).joinedload(OrganizerProfile.trips),
        )
        .order_by(Trip.created_at.desc())
    )
