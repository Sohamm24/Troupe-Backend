"""
api/v1/uploads.py
-----------------
POST /uploads — Upload media files to Supabase Storage.
"""

import uuid
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from core.config import settings
from core.dependencies import get_current_user
from models.user import User

router = APIRouter()
logger = logging.getLogger("travel_platform")


@router.post("/")
async def upload_media(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a media file (image) to Supabase Storage.
    Returns the public URL.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Storage not configured")

    file_bytes = await file.read()
    file_ext = (file.filename or "upload.jpg").rsplit(".", 1)[-1]
    unique_name = f"{uuid.uuid4()}.{file_ext}"
    content_type = file.content_type or "image/jpeg"

    bucket = settings.SUPABASE_BUCKET
    upload_url = f"{settings.SUPABASE_URL}/storage/v1/object/{bucket}/{unique_name}"

    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_KEY}",
        "apikey": settings.SUPABASE_KEY,
        "Content-Type": content_type,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(upload_url, content=file_bytes, headers=headers)
        if response.status_code >= 400:
            logger.error(f"Supabase upload failed: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to upload file")

    public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{bucket}/{unique_name}"
    logger.info(f"File uploaded: {unique_name} by user {current_user.user_id}")

    return {"success": True, "data": {"url": public_url}}
