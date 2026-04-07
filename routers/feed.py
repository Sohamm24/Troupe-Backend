"""
routers/feed.py
---------------
GET /api/feed

Query params:
  categories  : comma-separated category filter, e.g. "Beach,Temple"
  history     : URL-encoded JSON array of last-20 interactions from mobile cache
  seen_ids    : comma-separated image IDs already shown (to penalise duplicates)
  limit       : page size (default 20)
  offset      : pagination offset (default 0)

Response:
  {
    "total": 42,
    "page": 1,
    "images": [ ...ranked image dicts... ]
  }
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from services.feed_engine import generate_feed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.get("")
async def get_feed(
    request: Request,
    categories: Optional[str] = Query(None, description="Comma-separated category names"),
    history: Optional[str]    = Query(None, description="JSON-encoded last-20 interactions"),
    seen_ids: Optional[str]   = Query(None, description="Comma-separated already-seen image IDs"),
    limit: int                = Query(20, ge=1, le=100),
    offset: int               = Query(0, ge=0),
):
    # ── Parse index from app state ─────────────────────────────────────────
    index: list[dict] = request.app.state.metadata_index
    if not index:
        raise HTTPException(status_code=503, detail="Metadata index not ready. Try again shortly.")

    # ── Parse params ────────────────────────────────────────────────────────
    cat_filter = [c.strip() for c in categories.split(",")] if categories else None

    history_list = []
    if history:
        try:
            history_list = json.loads(history)
            if not isinstance(history_list, list):
                history_list = []
        except json.JSONDecodeError:
            logger.warning("Invalid history JSON, ignoring")

    seen_list = [s.strip() for s in seen_ids.split(",")] if seen_ids else []

    # ── Generate feed ───────────────────────────────────────────────────────
    try:
        ranked = generate_feed(
            index=index,
            history=history_list,
            categories=cat_filter,
            seen_ids=seen_list,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.exception("Feed generation error")
        raise HTTPException(status_code=500, detail=str(e))

    # ── Build image URLs ─────────────────────────────────────────────────────
    base_url = str(request.base_url).rstrip("/")
    for img in ranked:
        img["image_url"] = f"{base_url}/{img['path'].lstrip('/')}"

    return {
        "total": len(index),
        "returned": len(ranked),
        "offset": offset,
        "limit": limit,
        "images": ranked,
    }
