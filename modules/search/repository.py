from sqlalchemy.orm import Session, joinedload
from modules.trips.models import Trip
from modules.organizers.models import OrganizerProfile
from modules.users.models import User

def search_trips_query(db: Session, query_str: str):
    query = db.query(Trip).options(joinedload(Trip.organizer).joinedload(OrganizerProfile.user)).order_by(Trip.created_at.desc())
    if query_str:
        query = query.filter(Trip.title.ilike(f"%{query_str}%"))
    return query

def search_organizers_query(db: Session, query_str: str):
    query = db.query(OrganizerProfile).options(joinedload(OrganizerProfile.user)).join(User)
    if query_str:
        query = query.filter(User.name.ilike(f"%{query_str}%"))
    return query
