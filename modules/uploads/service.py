import uuid
import logging
import time
import mimetypes
from fastapi import HTTPException
from sqlalchemy.orm import Session
from core.config import settings
from modules.users.models import User
from modules.trips.models import Trip
from supabase import create_client
from storage3.types import CreateSignedUploadUrlOptions
from modules.uploads.schemas import PresignRequest, ConfirmUploadRequest
from modules.uploads.repository import get_trip_for_upload, save_trip_changes

logger = logging.getLogger("travel_platform")
supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

def _ext(mime_type: str) -> str:
    return mimetypes.guess_extension(mime_type) or ".jpg"

def _check_trip_ownership(trip: Trip | None, user: User) -> Trip:
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    if not user.organizer_profile: raise HTTPException(status_code=403, detail="Organizer profile not found")
    if trip.organizer_id != user.organizer_profile.organizer_id: raise HTTPException(status_code=403, detail="Not authorized")
    return trip

def _build_path(trip_id: str, media_context: str, ext: str, slot: str | None) -> str:
    if media_context == "thumbnail": return f"trips/{trip_id}/thumbnail{ext}"
    if media_context == "itinerary":
        slot_id = slot or str(uuid.uuid4())
        return f"trips/{trip_id}/itinerary/{slot_id}{ext}"
    raise HTTPException(status_code=400, detail=f"Unknown media_context: {media_context}")

def process_create_signed_upload(body: PresignRequest, current_user: User, db: Session):
    if body.mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}")
    
    ext = _ext(body.mime_type)
    if body.media_context == "profile_pic":
        file_path = f"users/{current_user.user_id}/profile_pic{ext}"
        bucket = settings.SUPABASE_PROFILE_PICS_BUCKET
    else:
        if not body.trip_id:
            raise HTTPException(status_code=400, detail="trip_id is required for trip uploads")
        trip = get_trip_for_upload(db, body.trip_id)
        _check_trip_ownership(trip, current_user)
        file_path = _build_path(body.trip_id, body.media_context, ext, body.itinerary_slot)
        bucket = settings.SUPABASE_BUCKET

    try:
        res = supabase.storage.from_(bucket).create_signed_upload_url(
            file_path, options=CreateSignedUploadUrlOptions(upsert="true")
        )
    except Exception as e:
        logger.exception("Supabase presign failed")
        raise HTTPException(status_code=500, detail="Could not generate upload URL")
    if not res or "signed_url" not in res:
        raise HTTPException(status_code=500, detail="Invalid response from storage")
    return {"presigned_url": res["signed_url"], "file_path": file_path}

def process_confirm_upload(payload: ConfirmUploadRequest, current_user: User, db: Session):
    if payload.media_context == "profile_pic":
        bucket = settings.SUPABASE_PROFILE_PICS_BUCKET
    else:
        if not payload.trip_id:
            raise HTTPException(status_code=400, detail="trip_id is required for trip uploads")
        bucket = settings.SUPABASE_BUCKET

    folder = "/".join(payload.file_path.split("/")[:-1])
    filename = payload.file_path.split("/")[-1]
    try:
        file_list = supabase.storage.from_(bucket).list(path=folder)
    except Exception:
        raise HTTPException(status_code=500, detail="Storage check failed")
    if not any(f["name"] == filename for f in (file_list or [])):
        raise HTTPException(status_code=400, detail="File not found in storage — upload may have failed")
    
    if payload.media_context == "profile_pic":
        public_url = supabase.storage.from_(bucket).get_public_url(payload.file_path)
        public_url = f"{public_url}?t={int(time.time())}"
        current_user.profile_pic = public_url
        db.commit()
        db.refresh(current_user)
        return {"success": True, "data": {"user_id": str(current_user.user_id), "file_path": payload.file_path, "public_url": public_url, "media_context": payload.media_context}}

    trip = get_trip_for_upload(db, payload.trip_id)
    _check_trip_ownership(trip, current_user)
    public_url = supabase.storage.from_(bucket).get_public_url(payload.file_path)
    public_url = f"{public_url}?t={int(time.time())}"
    if payload.media_context == "thumbnail":
        trip.thumbnail = public_url
    elif payload.media_context == "itinerary":
        itinerary = trip.itinerary or []
        updated = False
        for item in itinerary:
            if str(item.get("id")) == payload.itinerary_slot:
                item["image"] = public_url
                updated = True
                break
        if not updated:
            logger.warning("itinerary slot %s not found on trip %s", payload.itinerary_slot, payload.trip_id)
        trip.itinerary = itinerary
    else:
        raise HTTPException(status_code=400, detail=f"Unknown media_context: {payload.media_context}")
    save_trip_changes(db, trip)
    return {"success": True, "data": {"trip_id": trip.trip_id, "file_path": payload.file_path, "public_url": public_url, "media_context": payload.media_context}}

