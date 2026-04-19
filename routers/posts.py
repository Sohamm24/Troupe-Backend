"""
routers/posts.py
-----------------
POST /api/posts/           — Create a new travel post (multipart/form-data)
GET  /api/posts/user       — Get all posts for the current authenticated user
GET  /api/posts/{id}/similar — Find visually similar posts via pgvector cosine search
POST /api/posts/{id}/embed   — Backfill SigLIP2 embedding for an existing post
"""

import json
import uuid
import logging
import os
import asyncio

import httpx
import numpy as np

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from models import Post, User
from schemas import PostResponse
from services.embedding import get_image_embedding

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


# ── POST /api/posts/ ───────────────────────────────────────────────────────────

@router.post("/", response_model=PostResponse)
async def create_post(
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
    - Generates a CLIP-ViT embedding (locally, CPU) for visual similarity search.
    - Persists the post to the database and returns the full response model.
    """
    try:
        # ── Read image bytes ──────────────────────────────────────────────────
        file_bytes = image.file.read()

        # ── Upload image ─────────────────────────────────────────────────────
        file_ext      = (image.filename or "photo.jpg").rsplit(".", 1)[-1]
        unique_name   = f"{uuid.uuid4()}.{file_ext}"
        image_url     = upload_to_supabase(file_bytes, unique_name, image.content_type or "image/jpeg")

        # ── CLIP embedding (local model, CPU-bound → thread executor) ─────────
        try:
            loop = asyncio.get_running_loop()
            embedding = await loop.run_in_executor(None, get_image_embedding, file_bytes)
        except Exception as emb_err:
            logger.warning(f"Embedding failed, storing null: {emb_err}")
            embedding = None

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
            user_id         = current_user.id,
            description     = description,
            image_url       = image_url,
            location        = location_json,
            trip_start      = tripStartDate,
            trip_end        = tripEndDate,
            embedding       = embedding,
            likes           = 0,
            saves           = 0,
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


# ── GET /api/posts/{post_id}/similar ──────────────────────────────────────────

@router.get("/{post_id}/similar", response_model=list[PostResponse])
def get_similar_posts(
    post_id: int,
    limit: int = 8,
    db: Session = Depends(get_db),
) -> list[PostResponse]:
    """
    Find posts visually similar to the target post using pgvector cosine distance
    on SigLIP2 embeddings.

    Falls back to recency ordering when the target post has no embedding yet.
    """
    target_post = db.query(Post).filter(Post.id == post_id).first()
    if not target_post:
        raise HTTPException(status_code=404, detail="Post not found")

    if target_post.embedding is None:
        return (
            db.query(Post)
            .filter(Post.id != post_id)
            .order_by(Post.created_at.desc())
            .limit(limit)
            .all()
        )

    from sqlalchemy import text
    results = db.execute(
        text("""
            SELECT id
            FROM posts
            WHERE id != :post_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:emb AS vector)
            LIMIT :limit
        """),
        {"post_id": post_id, "emb": str(target_post.embedding), "limit": limit}
    ).fetchall()

    ids = [r[0] for r in results]
    if not ids:
        return []

    id_order = {id_: i for i, id_ in enumerate(ids)}
    posts = db.query(Post).filter(Post.id.in_(ids)).all()
    posts.sort(key=lambda p: id_order[p.id])
    return posts


# ── POST /api/posts/{post_id}/embed ───────────────────────────────────────────

@router.post("/{post_id}/embed", response_model=PostResponse)
async def embed_existing_post(
    post_id: int,
    db: Session = Depends(get_db),
) -> PostResponse:
    """
    Backfill embedding for an existing post that was uploaded before
    this feature was added. Fetches the image from its Supabase URL,
    generates a SigLIP2 embedding, and saves it.

    Call this once per old post — GET /posts/{id}/similar will then
    return embedding-based results instead of the recency fallback.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.embedding is not None:
        return post  # already has embedding, nothing to do

    # Fetch image bytes from Supabase public URL
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(post.image_url)
            if r.status_code != 200:
                raise HTTPException(502, f"Could not fetch image: {r.status_code}")
            image_bytes = r.content
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Image fetch failed: {e}")

    # Embed via local CLIP model (CPU-bound → thread executor)
    try:
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(None, get_image_embedding, image_bytes)
    except Exception as e:
        raise HTTPException(502, f"Embedding failed: {e}")

    post.embedding = embedding
    db.commit()
    db.refresh(post)
    return post
