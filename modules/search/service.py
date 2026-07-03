from sqlalchemy.orm import Session
from modules.search.repository import search_trips_query, search_organizers_query

def process_unified_search(q: str, type_str: str, db: Session):
    search_types = set()
    if type_str:
        search_types = {t.strip().lower() for t in type_str.split(",")}
    else:
        search_types = {"trip", "organizer"}

    results = {"trips": [], "organizers": []}

    if "trip" in search_types:
        trips = search_trips_query(db, q).limit(20).all()
        for trip in trips:
            organizer_name = trip.organizer.user.name if trip.organizer and trip.organizer.user else None
            results["trips"].append({
                "trip_id": str(trip.trip_id),
                "title": trip.title,
                "location": trip.location,
                "start_date": trip.start_date.isoformat() if trip.start_date else None,
                "budget": trip.budget,
                "organizer_name": organizer_name,
                "interested_count": trip.interested_count,
            })

    if "organizer" in search_types:
        organizers = search_organizers_query(db, q).limit(20).all()
        for org in organizers:
            results["organizers"].append({
                "organizer_id": str(org.organizer_id),
                "name": org.user.name if org.user else None,
                "bio": org.bio,
                "region": org.region,
                "verification_status": org.verification_status,
                "profile_pic": org.profile_pic,
            })

    return {"success": True, "data": results}

def process_search_trips(q: str, db: Session):
    trips = search_trips_query(db, q).limit(20).all()
    results = []
    for trip in trips:
        organizer_name = trip.organizer.user.name if trip.organizer and trip.organizer.user else None
        results.append({
            "trip_id": str(trip.trip_id),
            "title": trip.title,
            "location": trip.location,
            "start_date": trip.start_date.isoformat() if trip.start_date else None,
            "budget": trip.budget,
            "organizer_name": organizer_name,
            "interested_count": trip.interested_count,
        })
    return {"success": True, "data": results}

def process_search_organizers(q: str, db: Session):
    organizers = search_organizers_query(db, q).limit(20).all()
    results = []
    for org in organizers:
        results.append({
            "organizer_id": str(org.organizer_id),
            "name": org.user.name if org.user else None,
            "bio": org.bio,
            "region": org.region,
            "verification_status": org.verification_status,
            "profile_pic": org.profile_pic,
        })
    return {"success": True, "data": results}
