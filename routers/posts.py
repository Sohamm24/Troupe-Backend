"""
routers/posts.py
-----------------
POST   /api/posts/                — Create a new travel post
GET    /api/posts/user            — Get all posts for the current user (with owner join)
PATCH  /api/posts/{id}            — Edit a post's text fields (owner only)
DELETE /api/posts/{id}            — Delete a post (owner only)
GET    /api/posts/{id}/similar    — Visually similar posts via pgvector cosine search
POST   /api/posts/{id}/embed      — Backfill SigLIP2 embedding for an existing post
"""

import json
import uuid
import logging
import os
import asyncio

import httpx

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from sqlalchemy.orm import Session, joinedload
from typing import Optional

from database import get_db
from models import Post, User, PostLike, PostSave
from schemas import PostResponse, PostUpdateRequest
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
    user = db.query(User).filter(User.external_id == external_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Image upload helper ────────────────────────────────────────────────────────

def upload_to_supabase(file_bytes: bytes, filename: str, content_type: str) -> str:
    """
    Upload image bytes to Supabase Storage and return the public URL.
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


# ── Helper: load post with owner joined ───────────────────────────────────────

def _get_post_with_owner(post_id: int, db: Session) -> Post:
    post = (
        db.query(Post)
        .options(joinedload(Post.owner))
        .filter(Post.id == post_id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


# ── POST /api/posts/ ───────────────────────────────────────────────────────────

@router.post("/", response_model=PostResponse)
async def create_post(
    description:    Optional[str]  = Form(None),
    tripDays:       int            = Form(...),
    location:       Optional[str]  = Form(None),    # JSON string
    images:         list[UploadFile] = File(...),
    current_user: User             = Depends(get_current_user),
    db: Session                    = Depends(get_db),
) -> PostResponse:
    """
    Create a new travel post.
    Accepts multipart/form-data with multiple image fields named 'images'.
    """
    try:
        media_urls = []
        embedding = None
        
        for idx, image in enumerate(images):
            file_bytes    = image.file.read()
            file_ext      = (image.filename or "photo.jpg").rsplit(".", 1)[-1]
            unique_name   = f"{uuid.uuid4()}.{file_ext}"
            image_url     = upload_to_supabase(file_bytes, unique_name, image.content_type or "image/jpeg")
            media_urls.append(image_url)
            
            # Generate embedding for the very first image only
            if idx == 0:
                try:
                    loop = asyncio.get_running_loop()
                    embedding = await loop.run_in_executor(None, get_image_embedding, file_bytes)
                except Exception as emb_err:
                    logger.warning(f"Embedding failed, storing null: {emb_err}")

        location_data: Optional[dict] = None
        if location:
            try:
                parsed_loc = json.loads(location)
                location_data = {
                    "name": parsed_loc.get("name", ""),
                    "lat":  float(parsed_loc.get("lat", 0)),
                    "lng":  float(parsed_loc.get("lng", 0)),
                }
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid location JSON received: {location!r}")

        new_post = Post(
            user_id     = current_user.id,
            description = description,
            image_url   = media_urls[0] if media_urls else None, # Legacy
            media_urls  = media_urls,
            location    = location_data,
            trip_days   = tripDays,
            embedding   = embedding,
            likes       = 0,
            saves       = 0,
        )
        db.add(new_post)
        db.commit()
        db.refresh(new_post)
        return _get_post_with_owner(new_post.id, db)

    except HTTPException:
        raise
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
    """Return all posts created by the currently authenticated user (with owner join)."""
    return (
        db.query(Post)
        .options(joinedload(Post.owner))
        .filter(Post.user_id == current_user.id)
        .order_by(Post.created_at.desc())
        .all()
    )


# ── PATCH /api/posts/{post_id} ────────────────────────────────────────────────

@router.patch("/{post_id}", response_model=PostResponse)
def update_post(
    post_id: int,
    payload: PostUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session        = Depends(get_db),
) -> PostResponse:
    """
    Edit a post's text fields (description, location, trip dates).
    Only the post owner may update their post.
    """
    post = _get_post_with_owner(post_id, db)

    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own posts")

    if payload.description is not None:
        post.description = payload.description

    if payload.location is not None:
        post.location = {
            "name": payload.location.name or "",
            "lat":  payload.location.lat,
            "lng":  payload.location.lng,
        }

    if payload.trip_start is not None:
        post.trip_start = payload.trip_start

    if payload.trip_end is not None:
        post.trip_end = payload.trip_end

    db.commit()
    db.refresh(post)
    return _get_post_with_owner(post_id, db)


# ── DELETE /api/posts/{post_id} ───────────────────────────────────────────────

@router.delete("/{post_id}", status_code=204)
def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session        = Depends(get_db),
):
    """
    Delete a post. Only the post owner may delete it.
    Returns 204 No Content on success.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own posts")

    db.delete(post)
    db.commit()
    return {"detail": "Post deleted"}

# ── Likes & Saves ──────────────────────────────────────────────────────────────

@router.post("/{post_id}/like")
def like_post(post_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post: raise HTTPException(404, "Post not found")
    
    like = db.query(PostLike).filter_by(user_id=current_user.id, post_id=post_id).first()
    if not like:
        db.add(PostLike(user_id=current_user.id, post_id=post_id))
        post.likes += 1
        db.commit()
    return {"detail": "Liked"}

@router.delete("/{post_id}/like")
def unlike_post(post_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post: raise HTTPException(404, "Post not found")
    
    like = db.query(PostLike).filter_by(user_id=current_user.id, post_id=post_id).first()
    if like:
        db.delete(like)
        post.likes = max(0, post.likes - 1)
        db.commit()
    return {"detail": "Unliked"}

@router.post("/{post_id}/save")
def save_post(post_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post: raise HTTPException(404, "Post not found")
    
    save = db.query(PostSave).filter_by(user_id=current_user.id, post_id=post_id).first()
    if not save:
        db.add(PostSave(user_id=current_user.id, post_id=post_id))
        post.saves += 1
        db.commit()
    return {"detail": "Saved"}

@router.delete("/{post_id}/save")
def unsave_post(post_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post: raise HTTPException(404, "Post not found")
    
    save = db.query(PostSave).filter_by(user_id=current_user.id, post_id=post_id).first()
    if save:
        db.delete(save)
        post.saves = max(0, post.saves - 1)
        db.commit()
    return {"detail": "Unsaved"}

# ── GET /api/posts/{post_id}/similar ──────────────────────────────────────────

@router.get("/{post_id}/similar", response_model=list[PostResponse])
def get_similar_posts(
    post_id: int,
    limit: int = 8,
    db: Session = Depends(get_db),
) -> list[PostResponse]:
    """
    Find posts visually similar to the target post using pgvector cosine distance
    on SigLIP2 embeddings. Falls back to recency ordering when no embedding exists.
    """
    target_post = db.query(Post).filter(Post.id == post_id).first()
    if not target_post:
        raise HTTPException(status_code=404, detail="Post not found")

    if target_post.embedding is None:
        return (
            db.query(Post)
            .options(joinedload(Post.owner))
            .filter(Post.id != post_id)
            .order_by(Post.created_at.desc())
            .limit(limit)
            .all()
        )

    from sqlalchemy import text
    emb_str = "[" + ",".join(f"{v:.8f}" for v in target_post.embedding) + "]"
    results = db.execute(
        text("""
            SELECT id
            FROM posts
            WHERE id != :post_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:emb AS vector)
            LIMIT :limit
        """),
        {"post_id": post_id, "emb": emb_str, "limit": limit}
    ).fetchall()

    ids = [r[0] for r in results]
    if not ids:
        return []

    id_order = {id_: i for i, id_ in enumerate(ids)}
    posts = (
        db.query(Post)
        .options(joinedload(Post.owner))
        .filter(Post.id.in_(ids))
        .all()
    )
    posts.sort(key=lambda p: id_order[p.id])
    return posts


# ── POST /api/posts/{post_id}/embed ───────────────────────────────────────────

@router.post("/{post_id}/embed", response_model=PostResponse)
async def embed_existing_post(
    post_id: int,
    db: Session = Depends(get_db),
) -> PostResponse:
    """
    Backfill embedding for an existing post.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.embedding is not None:
        return _get_post_with_owner(post_id, db)

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

    try:
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(None, get_image_embedding, image_bytes)
    except Exception as e:
        raise HTTPException(502, f"Embedding failed: {e}")

    post.embedding = embedding
    db.commit()
    db.refresh(post)
    return _get_post_with_owner(post_id, db)
