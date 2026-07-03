import uuid
import logging
import mimetypes
 
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
 
from core.config import settings
from core.database import get_db
from core.dependencies import get_current_user
from models.user import User
from models.trip import Trip
from supabase import create_client
 
router = APIRouter()
logger = logging.getLogger("travel_platform")
 
supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
 
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_MB = 10
 
 
# ── Schemas ────────────────────────────────────────────────────────────────────
 
class PresignRequest(BaseModel):
    trip_id: str 
    # "thumbnail" | "itinerary"
    media_context: str
    # e.g. "image/jpeg"
    mime_type: str
    # optional: which itinerary slot (index or temp id from client)
    itinerary_slot: str | None = None
 
 
class ConfirmUploadRequest(BaseModel):
    trip_id: str
    file_path: str
    # "thumbnail" | "itinerary"
    media_context: str
    itinerary_slot: str | None = None
 
 
class ReplaceImageRequest(BaseModel):
    trip_id: str
    new_file_path: str
    # "thumbnail" | "itinerary"
    media_context: str
    itinerary_slot: str | None = None
 
 
# ── Helpers ────────────────────────────────────────────────────────────────────
 
def _ext(mime_type: str) -> str:
    return mimetypes.guess_extension(mime_type) or ".jpg"
 
 
def _check_trip_ownership(trip: Trip | None, user: User) -> Trip:
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    if not user.organizer_profile:
        raise HTTPException(
            status_code=403,
            detail="Organizer profile not found",
        )

    if trip.organizer_id != user.organizer_profile.organizer_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized",
        )

    return trip
 
 
def _build_path(trip_id: str, media_context: str, ext: str, slot: str | None) -> str:
    """
    Produces deterministic bucket paths:
      trips/{trip_id}/thumbnail.jpg
      trips/{trip_id}/itinerary/{slot}.jpg
    """
    if media_context == "thumbnail":
        return f"trips/{trip_id}/thumbnail{ext}"
    if media_context == "itinerary":
        slot_id = slot or str(uuid.uuid4())
        return f"trips/{trip_id}/itinerary/{slot_id}{ext}"
    raise HTTPException(status_code=400, detail=f"Unknown media_context: {media_context}")
 
 
# ── Routes ─────────────────────────────────────────────────────────────────────
 
@router.post("/presign")
async def create_signed_upload(
    body: PresignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Step 1: client asks for a presigned upload URL before touching the file.
    Returns the URL + the path so the client can PUT directly to Supabase.
    """
    if body.mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )
 
    # Validate trip ownership before issuing any URL
    trip = db.query(Trip).filter(Trip.trip_id == body.trip_id).first()
    _check_trip_ownership(trip, current_user)
 
    ext = _ext(body.mime_type)
    file_path = _build_path(body.trip_id, body.media_context, ext, body.itinerary_slot)
 
    try:
        res = supabase.storage.from_(settings.SUPABASE_BUCKET).create_signed_upload_url(file_path)
        logger.info("Supabase response: %r", res)
        logger.info("Response type: %s", type(res))
    except Exception as e:
        logger.exception("Supabase presign failed")
        raise HTTPException(status_code=500, detail="Could not generate upload URL")
 
    if not res or "signed_url" not in res:
        raise HTTPException(status_code=500, detail="Invalid response from storage")
 
    return {
        "presigned_url": res["signed_url"],
        "file_path": file_path,
    }
 
 
@router.post("/confirm", status_code=status.HTTP_200_OK)
async def confirm_upload(
    payload: ConfirmUploadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Step 2: called after the client successfully PUTs the file to Supabase.
    Verifies the file exists, then writes the path into the correct DB column.
    """
    bucket = settings.SUPABASE_BUCKET
 
    # 1. Verify file actually landed in the bucket
    folder = "/".join(payload.file_path.split("/")[:-1])
    filename = payload.file_path.split("/")[-1]
    try:
        file_list = supabase.storage.from_(bucket).list(path=folder)
    except Exception:
        raise HTTPException(status_code=500, detail="Storage check failed")
 
    if not any(f["name"] == filename for f in (file_list or [])):
        raise HTTPException(status_code=400, detail="File not found in storage — upload may have failed")
 
    # 2. Ownership check
    trip = db.query(Trip).filter(Trip.trip_id == payload.trip_id).first()
    _check_trip_ownership(trip, current_user)
 
    # 3. Persist into the right column
    if payload.media_context == "thumbnail":
        trip.cover_image = payload.file_path
 
    elif payload.media_context == "itinerary":
        # itinerary is stored as a list of dicts on the trip model
        # update the matching slot by itinerary_slot id
        itinerary = trip.itinerary or []
        updated = False
        for item in itinerary:
            if str(item.get("id")) == payload.itinerary_slot:
                item["image"] = payload.file_path
                updated = True
                break
        if not updated:
            # slot not found yet — this means the itinerary item is being
            # created for the first time; client will attach it on save
            logger.warning("itinerary slot %s not found on trip %s", payload.itinerary_slot, payload.trip_id)
        trip.itinerary = itinerary  # trigger SQLAlchemy dirty tracking for JSONB
 
    else:
        raise HTTPException(status_code=400, detail=f"Unknown media_context: {payload.media_context}")
 
    db.commit()
    db.refresh(trip)
 
    # 4. Return the public URL so the client can render immediately
    public_url = supabase.storage.from_(bucket).get_public_url(payload.file_path)
 
    return {
        "success": True,
        "data": {
            "trip_id": trip.trip_id,
            "file_path": payload.file_path,
            "public_url": public_url,
            "media_context": payload.media_context,
        },
    }
 
 
@router.post("/upload/replace", status_code=status.HTTP_200_OK)
async def replace_image(
    payload: ReplaceImageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Replace an existing image path (thumbnail or itinerary slot).
    DB is updated first; old file deletion is best-effort.
    """
    bucket = settings.SUPABASE_BUCKET
 
    trip = db.query(Trip).filter(Trip.trip_id == payload.trip_id).first()
    _check_trip_ownership(trip, current_user)
 
    old_path: str | None = None
 
    if payload.media_context == "thumbnail":
        old_path = trip.cover_image
        trip.cover_image = payload.new_file_path
 
    elif payload.media_context == "itinerary":
        itinerary = trip.itinerary or []
        for item in itinerary:
            if str(item.get("id")) == payload.itinerary_slot:
                old_path = item.get("image")
                item["image"] = payload.new_file_path
                break
        trip.itinerary = itinerary
 
    else:
        raise HTTPException(status_code=400, detail=f"Unknown media_context: {payload.media_context}")
 
    # DB update is the source of truth
    db.commit()
    db.refresh(trip)
 
    # Best-effort: remove old file from storage
    if old_path:
        try:
            supabase.storage.from_(bucket).remove([old_path])
        except Exception:
            logger.warning("Could not delete old file %s — skipping", old_path)
 
    public_url = supabase.storage.from_(bucket).get_public_url(payload.new_file_path)
 
    return {
        "success": True,
        "data": {
            "trip_id": trip.trip_id,
            "new_file_path": payload.new_file_path,
            "public_url": public_url,
            "deleted_old_file": old_path,
        },
    }