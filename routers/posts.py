"""
routers/posts.py
-----------------
POST /api/posts/  — Create a new travel post (multipart/form-data)
GET  /api/posts/user — Get all posts for the current authenticated user
"""

import json
import uuid
import logging
import os

import cv2
import httpx
import numpy as np

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import Post, User
from schemas import PostResponse

router = APIRouter()
logger = logging.getLogger("travel_pinterest")


# ── Auth dependency ────────────────────────────────────────────────────────────

def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Verify the requesting user via the Clerk user ID passed as
    `Authorization: Bearer <external_id>` header.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    external_id = authorization.replace("Bearer ", "").strip()
    user = db.query(User).filter(User.external_id== external_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Image upload helper ────────────────────────────────────────────────────────

def upload_to_supabase(file_bytes: bytes, filename: str, content_type: str) -> str:
    """
    Upload image bytes to Supabase Storage and return the public URL.

    NOTE: Replace this function body with your own cloud upload logic
    (e.g. Cloudinary, S3, Firebase) if you switch storage providers.
    """
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_key or not supabase_url:
        raise HTTPException(status_code=500, detail="Supabase credentials not configured")

    bucket_name = "travel-pinterest"
    upload_url  = f"{supabase_url}/storage/v1/object/{bucket_name}/{filename}"

    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey":        supabase_key,
        "Content-Type":  content_type,
    }

    with httpx.Client() as client:
        response = client.post(upload_url, content=file_bytes, headers=headers)
        if response.status_code >= 400:
            logger.error(f"Supabase upload failed: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to upload image")

    return f"{supabase_url}/storage/v1/object/public/{bucket_name}/{filename}"


# ── OpenCV tag generation ──────────────────────────────────────────────────────

def generate_tags_from_image(file_bytes: bytes, n_clusters: int = 4) -> list[str]:
    """
    Analyse the dominant colours in an image using k-means clustering on HSV
    values and map them to descriptive travel tags.

    Returns a list of 3-5 unique tags such as:
      ["beach", "ocean", "sunset"]
    """
    # Decode image bytes → numpy array
    nparr = np.frombuffer(file_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img_bgr is None:
        logger.warning("Could not decode image for tag generation")
        return ["travel"]

    # Resize to a small thumbnail for speed (200×200 is plenty for colour stats)
    img_bgr = cv2.resize(img_bgr, (200, 200))
    img_hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    # Flatten to (N, 3) float32 for k-means
    pixels = img_hsv.reshape(-1, 3).astype(np.float32)

    # Run k-means to find dominant colour clusters
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(
        pixels, n_clusters, None, criteria,
        attempts=3, flags=cv2.KMEANS_RANDOM_CENTERS
    )

    # Count pixels per cluster so we process the most dominant colours first
    counts     = np.bincount(labels.flatten())
    sorted_idx = np.argsort(-counts)   # descending

    tags: list[str] = []

    for idx in sorted_idx:
        h, s, v = centers[idx]   # hue 0-179, sat 0-255, val 0-255

        # Low saturation → greyscale / urban
        if s < 50:
            if v > 180:
                _add_unique(tags, ["cloudy", "misty"])
            else:
                _add_unique(tags, ["city", "urban"])
            continue

        # Map hue ranges to travel categories
        # OpenCV hue: 0-179 (half of standard 360°)
        if h < 10 or h > 165:
            # Red tones
            _add_unique(tags, ["sunset", "desert", "warm"])
        elif h < 25:
            # Orange
            _add_unique(tags, ["sunset", "desert"])
        elif h < 35:
            # Yellow
            _add_unique(tags, ["beach", "sunny", "desert"])
        elif h < 85:
            # Green range
            if v < 120:
                _add_unique(tags, ["forest", "jungle"])
            else:
                _add_unique(tags, ["mountain", "nature", "hiking"])
        elif h < 105:
            # Cyan
            _add_unique(tags, ["ocean", "beach", "tropical"])
        elif h < 135:
            # Blue
            if v > 150:
                _add_unique(tags, ["sky", "coastal"])
            else:
                _add_unique(tags, ["ocean", "lake"])
        else:
            # Purple / magenta
            _add_unique(tags, ["sunset", "lavender"])

        if len(tags) >= 5:
            break

    return tags if tags else ["travel"]


def _add_unique(tags: list[str], candidates: list[str]) -> None:
    """Append candidates to tags list, skipping duplicates. Modifies in-place."""
    for c in candidates:
        if c not in tags:
            tags.append(c)
            break   # add at most one candidate per cluster


# ── POST /api/posts/ ───────────────────────────────────────────────────────────

@router.post("/", response_model=PostResponse)
def create_post(
    # Multipart form fields
    description:    Optional[str]  = Form(None),
    tripStartDate:  str            = Form(...),
    tripEndDate:    str            = Form(...),
    location:       Optional[str]  = Form(None),    # JSON string
    # Single image file
    image: UploadFile              = File(...),
    # Dependencies
    current_user: User             = Depends(get_current_user),
    db: Session                    = Depends(get_db),
) -> PostResponse:
    """
    Create a new travel post.

    - Accepts multipart/form-data with a single image field named 'image'.
    - Uploads the image to Supabase Storage and obtains a public URL.
    - Parses the location JSON string into a structured object.
    - Generates 3-5 travel tags from the image using OpenCV k-means colour analysis.
    - Persists the post to the database and returns the full response model.
    """
    try:
        # ── Read image bytes ──────────────────────────────────────────────────
        file_bytes = image.file.read()

        # ── Upload image ─────────────────────────────────────────────────────
        file_ext      = (image.filename or "photo.jpg").rsplit(".", 1)[-1]
        unique_name   = f"{uuid.uuid4()}.{file_ext}"
        image_url     = upload_to_supabase(file_bytes, unique_name, image.content_type or "image/jpeg")

        # ── Generate tags via OpenCV ──────────────────────────────────────────
        tags = generate_tags_from_image(file_bytes)
        logger.info(f"Generated tags for post: {tags}")

        # ── Validate & parse location JSON ────────────────────────────────────
        location_json: Optional[str] = None
        if location:
            try:
                parsed_loc = json.loads(location)
                # Normalise to ensure it has the expected keys
                location_json = json.dumps({
                    "name": parsed_loc.get("name", ""),
                    "lat":  float(parsed_loc.get("lat", 0)),
                    "lng":  float(parsed_loc.get("lng", 0)),
                })
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid location JSON received: {location!r}")
                # Store the raw string as fallback — don't reject the request
                location_json = location

        # ── Persist to database ───────────────────────────────────────────────
        new_post = Post(
            user_id     = current_user.id,
            description = description,
            image_url   = image_url,
            location    = location_json,
            tags        = tags,
            trip_start  = tripStartDate,
            trip_end    = tripEndDate,
            likes       = 0,
            saves       = 0,
        )
        db.add(new_post)
        db.commit()
        db.refresh(new_post)
        return new_post

    except HTTPException:
        raise   # re-raise known HTTP errors as-is
    except Exception as e:
        logger.error(f"Error creating post: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ── GET /api/posts/user ────────────────────────────────────────────────────────

@router.get("/user", response_model=list[PostResponse])
def get_user_posts(
    current_user: User = Depends(get_current_user),
    db: Session        = Depends(get_db),
) -> list[PostResponse]:
    """Return all posts created by the currently authenticated user."""
    return (
        db.query(Post)
        .filter(Post.user_id == current_user.id)
        .order_by(Post.created_at.desc())
        .all()
    )
