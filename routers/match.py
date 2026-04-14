"""
routers/match.py
----------------
POST /api/match

Upload any travel photo → returns top-10 visually similar images from the dataset.

Request:   multipart/form-data with field "file" (jpeg/png)
Response:
  {
    "query_image": "original filename",
    "matches": [
      {
        "id": "...",
        "category": "Beach",
        "subcategory": "turquoise_water",
        "image_url": "http://...",
        "similarity_score": 0.87,
        "mood": "vibrant",
        "dominant_colors": ["#...", ...],
        "features": ["clear_water", "horizon_view"],
        ...
      }
    ]
  }
"""

import logging
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Query

from services.image_matcher import match_from_upload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/match", tags=["match"])

ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_SIZE_MB   = 10


@router.post("")
def match_image(
    request: Request,
    file: UploadFile = File(..., description="Travel photo to find matches for"),
    top_n: int = Query(10, ge=1, le=30, description="Number of matches to return"),
):
    # ── Validate matcher is ready ────────────────────────────────────────────
    matcher = request.app.state.image_matcher
    if matcher is None:
        raise HTTPException(status_code=503, detail="Matcher not ready. Descriptors still building.")

    # ── Validate file type ───────────────────────────────────────────────────
    ct = file.content_type or ""
    if ct not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ct}'. Allowed: jpeg, png, webp"
        )

    # ── Read bytes (size guard) ──────────────────────────────────────────────
    raw = file.file.read()
    size_mb = len(raw) / (1024 * 1024)
    if size_mb > MAX_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Max {MAX_SIZE_MB} MB."
        )

    # ── Run matching ─────────────────────────────────────────────────────────
    try:
        matches = match_from_upload(matcher, raw, top_n=top_n)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Match error")
        raise HTTPException(status_code=500, detail=str(e))

    # ── Enrich with full image URLs ──────────────────────────────────────────
    base_url = str(request.base_url).rstrip("/")
    for m in matches:
        m["image_url"] = f"{base_url}/{m['path'].lstrip('/')}"

    return {
        "query_image": file.filename,
        "top_n": top_n,
        "matches": matches,
    }
