from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from core.database import get_db
from modules.search.service import process_unified_search, process_search_trips, process_search_organizers

router = APIRouter()

@router.get("/")
def unified_search(
    q: str = Query(..., min_length=1),
    type: str = Query(None, description="Comma-separated: trip,organizer"),
    db: Session = Depends(get_db),
):
    return process_unified_search(q, type, db)

@router.get("/trips")
def search_trips(
    q: str = Query("", min_length=0),
    db: Session = Depends(get_db),
):
    return process_search_trips(q, db)

@router.get("/organizers")
def search_organizers(
    q: str = Query("", min_length=0),
    db: Session = Depends(get_db),
):
    return process_search_organizers(q, db)
