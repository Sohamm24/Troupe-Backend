"""
routers/user.py — User profile & onboarding endpoints
------------------------------------------------------
GET   /api/user/me          — Return current user profile (with posts joined)
POST  /api/user/onboard     — Complete onboarding (username, names, optional profile pic)
PATCH /api/user/me          — Update profile info (name, username, optional new avatar)
"""

import logging
import os
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from typing import Optional

from database import get_db
from models import User, Post
from schemas import User as UserSchema, UserUpdateRequest

router  = APIRouter()
logger  = logging.getLogger("travel_pinterest")


# ── Auth helper ────────────────────────────────────────────────────────────────

def _get_or_create_user(external_id: str, db: Session) -> User:
    user = db.query(User).filter(User.external_id == external_id).first()
    if not user:
        user = User(external_id=external_id)
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"Lazy created missing user {external_id} in Neon DB.")
    return user


def _load_user_with_posts(user_id: int, db: Session) -> User:
    """Load user with eagerly fetched posts (newest first), each post with owner join."""
    user = (
        db.query(User)
        .options(joinedload(User.posts).joinedload(Post.owner))
        .filter(User.id == user_id)
        .first()
    )
    if user:
        user.posts.sort(key=lambda p: p.created_at or "", reverse=True)
    return user


# ── Supabase upload helper ─────────────────────────────────────────────────────

def _upload_profile_pic(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Upload profile picture to Supabase Storage and return the public URL."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_key or not supabase_url:
        raise HTTPException(status_code=500, detail="Supabase credentials not configured")

    bucket_name = "travel-pinterest"
    object_path = f"avatars/{filename}"
    upload_url  = f"{supabase_url}/storage/v1/object/{bucket_name}/{object_path}"

    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey":        supabase_key,
        "Content-Type":  content_type,
    }

    with httpx.Client() as client:
        response = client.post(upload_url, content=file_bytes, headers=headers)
        if response.status_code >= 400:
            logger.error(f"Supabase profile pic upload failed: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to upload profile picture")

    return f"{supabase_url}/storage/v1/object/public/{bucket_name}/{object_path}"


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserSchema)
def get_me(
    authorization: str = Header(..., description="Bearer <external_id>"),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's profile with posts ordered newest-first."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    external_id = authorization.removeprefix("Bearer ").strip()
    user = _get_or_create_user(external_id, db)
    return _load_user_with_posts(user.id, db)


@router.post("/onboard", response_model=UserSchema)
def onboard(
    username:   Optional[str]        = Form(None),
    first_name: Optional[str]        = Form(None),
    last_name:  Optional[str]        = Form(None),
    profile_pic: Optional[UploadFile] = File(None),
    authorization: str               = Header(..., description="Bearer <external_id>"),
    db: Session                      = Depends(get_db),
):
    """
    Complete onboarding — sets username, name, and optionally a profile picture.
    Sets onboarded=True on the user record.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    external_id = authorization.removeprefix("Bearer ").strip()
    user = _get_or_create_user(external_id, db)

    if username:
        conflict = db.query(User).filter(
            User.username == username,
            User.external_id != external_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Username already taken")
        user.username = username

    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        user.last_name = last_name

    if profile_pic and profile_pic.filename:
        file_bytes   = profile_pic.file.read()
        file_ext     = (profile_pic.filename or "avatar.jpg").rsplit(".", 1)[-1]
        unique_name  = f"{uuid.uuid4()}.{file_ext}"
        content_type = profile_pic.content_type or "image/jpeg"
        user.profile_pic_url = _upload_profile_pic(file_bytes, unique_name, content_type)
        logger.info(f"Profile pic uploaded for user {external_id}: {user.profile_pic_url}")

    user.onboarded = True
    db.commit()
    db.refresh(user)
    logger.info(f"User {external_id} completed onboarding")
    return _load_user_with_posts(user.id, db)


@router.patch("/me", response_model=UserSchema)
def update_profile(
    # Text fields via Form (multipart so we can also accept a new avatar)
    username:    Optional[str]        = Form(None),
    first_name:  Optional[str]        = Form(None),
    last_name:   Optional[str]        = Form(None),
    profile_pic: Optional[UploadFile] = File(None),
    authorization: str               = Header(..., description="Bearer <external_id>"),
    db: Session                      = Depends(get_db),
):
    """
    Update profile info without touching the onboarded flag.
    Accepts multipart/form-data:
      - username    (string, optional)
      - first_name  (string, optional)
      - last_name   (string, optional)
      - profile_pic (file,   optional) — re-uploaded to Supabase
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    external_id = authorization.removeprefix("Bearer ").strip()

    user = db.query(User).filter(User.external_id == external_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if username is not None and username != user.username:
        conflict = db.query(User).filter(
            User.username == username,
            User.external_id != external_id,
        ).first()
        if conflict:
            raise HTTPException(status_code=409, detail="Username already taken")
        user.username = username

    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        user.last_name = last_name

    if profile_pic and profile_pic.filename:
        file_bytes   = profile_pic.file.read()
        file_ext     = (profile_pic.filename or "avatar.jpg").rsplit(".", 1)[-1]
        unique_name  = f"{uuid.uuid4()}.{file_ext}"
        content_type = profile_pic.content_type or "image/jpeg"
        user.profile_pic_url = _upload_profile_pic(file_bytes, unique_name, content_type)
        logger.info(f"Profile pic updated for user {external_id}")

    db.commit()
    db.refresh(user)
    logger.info(f"User {external_id} updated profile")
    return _load_user_with_posts(user.id, db)
