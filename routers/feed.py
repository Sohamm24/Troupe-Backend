"""
routers/feed.py
---------------
GET /api/feed

Returns a personalised ranked feed of the 20 most relevant posts
for the current user.

Scoring algorithm per post:
  score = recency_score
        + engagement_score
        + followed_user_bonus
        + location_match_bonus
        + tag_match_bonus
        + ongoing_trip_bonus
"""

import json
import math
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import Post, User
from schemas import PostResponse

router = APIRouter()
logger = logging.getLogger("travel_pinterest")


# ── Auth dependency (same pattern as posts.py) ─────────────────────────────────

def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the requesting user from `Authorization: Bearer <external_id>`.
    Returns the User ORM object, including any relationships needed for scoring.

    NOTE: In production, extend the User model with:
      - followed_ids  (list of user IDs this user follows)
      - home_location ({"lat": ..., "lng": ...})
      - interests     (list of tag strings)
    For now we read those as empty defaults so the feed always works.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    external_id = authorization.replace("Bearer ", "").strip()
    user = db.query(User).filter(User.external_id == external_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Haversine distance helper ──────────────────────────────────────────────────

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in kilometres between two coordinates."""
    R = 6371.0
    phi1, phi2   = math.radians(lat1), math.radians(lat2)
    dphi         = math.radians(lat2 - lat1)
    dlambda      = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ── Scoring ────────────────────────────────────────────────────────────────────

def score_post(post: Post, user: User, today: date) -> float:
    """
    Compute a relevance score for a single post relative to the current user.

    Components (all additive):
      1. Recency       — sigmoid decay over days since creation (max ≈ 30)
      2. Engagement    — likes + saves×1.5 (max ≈ 20)
      3. Followed user — +25 if the post author is followed by the user
      4. Location      — +20 graded by proximity (within 500 km)
      5. Tag match     — +5 per shared interest tag (max 15)
      6. Ongoing trip  — +10 if today falls within [trip_start, trip_end]
    """
    score = 0.0

    # ── 1. Recency boost ────────────────────────────────────────────────────────
    if post.created_at:
        # Convert timezone-aware datetime → naive for arithmetic
        created = post.created_at.replace(tzinfo=None) if post.created_at.tzinfo else post.created_at
        age_days = (datetime.utcnow() - created).days
        # Smooth decay: score goes from ~30 (new) to ~0 (old)
        score += 30.0 / (1.0 + 0.1 * age_days)

    # ── 2. Engagement score ─────────────────────────────────────────────────────
    likes = post.likes or 0
    saves = post.saves or 0
    score += min(likes + saves * 1.5, 20.0)   # cap to avoid viral posts dominating

    # ── 3. Followed-user boost ──────────────────────────────────────────────────
    # followed_ids should be a list attribute on the user model (extend later)
    followed_ids: list[int] = getattr(user, "followed_ids", []) or []
    if post.user_id in followed_ids:
        score += 25.0

    # ── 4. Location proximity boost ─────────────────────────────────────────────
    home_location: Optional[dict] = getattr(user, "home_location", None)
    if home_location and post.location:
        try:
            post_loc = json.loads(post.location)
            dist_km  = haversine_km(
                home_location["lat"], home_location["lng"],
                post_loc["lat"],      post_loc["lng"],
            )
            # Linear decay: full 20 pts within 50 km, 0 pts at 500 km+
            score += max(0.0, 20.0 * (1.0 - dist_km / 500.0))
        except (json.JSONDecodeError, KeyError, TypeError):
            pass   # skip location scoring if data is malformed

    # ── 5. Tag match (personalisation) ──────────────────────────────────────────
    user_interests: list[str] = getattr(user, "interests", []) or []
    post_tags:      list[str] = post.tags or []
    shared = len(set(user_interests) & set(post_tags))
    score += min(shared * 5.0, 15.0)   # +5 per tag, capped at 15

    # ── 6. Ongoing trip bonus ────────────────────────────────────────────────────
    try:
        if post.trip_start and post.trip_end:
            start = date.fromisoformat(post.trip_start)
            end   = date.fromisoformat(post.trip_end)
            if start <= today <= end:
                score += 10.0
    except ValueError:
        pass   # malformed dates — skip

    return score


# ── GET /api/feed ──────────────────────────────────────────────────────────────

from schemas import FeedResponse

@router.get("/", response_model=FeedResponse)
def get_feed(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session        = Depends(get_db),
) -> FeedResponse:
    """
    Return a personalised feed of the top 20 posts for the current user.

    Pipeline:
      1. Fetch the 200 most recent posts from the database.
      2. Score each post using the multi-factor algorithm above.
      3. Sort descending by score.
      4. Return the top 20.
    """
    logger.info(f"==> Feed Request | User ID: {current_user.id} (@{getattr(current_user, 'username', 'N/A')}) | Limit: {limit} | Offset: {offset}")
    today = date.today()

    # Step 1 — Fetch up to 200 recent posts (with owner join)
    recent_posts: list[Post] = (
        db.query(Post)
        .options(joinedload(Post.owner))
        .order_by(Post.created_at.desc())
        .limit(200)
        .all()
    )

    if not recent_posts:
        return FeedResponse(total=0, returned=0, offset=offset, limit=limit, posts=[])

    # Step 2 — Score each post
    scored: list[tuple[float, Post]] = []
    for post in recent_posts:
        try:
            s = score_post(post, current_user, today)
            scored.append((s, post))
        except Exception as e:
            logger.warning(f"Skipping post {post.id} in feed scoring: {e}")

    # Step 3 — Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Step 4 — Return paginated slice based on offset and limit
    top_posts = [post for _, post in scored[offset : offset + limit]]

    logger.info(
        f"Feed for user {current_user.id}: "
        f"scored {len(scored)} posts, returning {len(top_posts)}"
    )

    return FeedResponse(
        total=len(recent_posts),
        returned=len(top_posts),
        offset=offset,
        limit=limit,
        posts=top_posts,
    )
