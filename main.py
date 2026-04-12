"""
main.py — Travel Pinterest MVP Backend
---------------------------------------
Two routes only:
  GET  /api/feed   — Personalised image feed (scored by mobile interaction history)
  POST /api/match  — Upload a photo → find visually similar images

Startup sequence:
  1. Serve images/ folder as static files at /images
  2. Build metadata index (if not already built) → metadata/index.json
  3. Build ORB+colour descriptor store (if not already built) → metadata/descriptors.npz
  4. Load both into app.state for sub-second per-request access
"""

import os
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import feed, match, webhook, posts
from database import engine
import models

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("travel_pinterest")

# ──────────────────────────────────────────────────────────────────────────────
# Paths  (resolved relative to this file so uvicorn cwd doesn't matter)
# ──────────────────────────────────────────────────────────────────────────────
BACKEND_DIR  = Path(__file__).parent
PROJECT_ROOT = BACKEND_DIR.parent          # c:\...\Travel-Pinterest
IMAGES_DIR   = PROJECT_ROOT / "images"
METADATA_DIR = BACKEND_DIR / "metadata"
INDEX_PATH   = METADATA_DIR / "index.json"
DESC_PATH    = str(METADATA_DIR / "descriptors.npz")
STAMP_PATH   = METADATA_DIR / ".build_stamp"


# ──────────────────────────────────────────────────────────────────────────────
# Background build thread
# ──────────────────────────────────────────────────────────────────────────────

def _build_pipeline(app: FastAPI):
    """
    Run in a background thread so the server starts accepting requests
    immediately. The /api/feed and /api/match routes return 503 until ready.
    """
    from services.feature_extractor import build_metadata_index
    from services.image_matcher import build_descriptor_store, ImageMatcher

    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Metadata index ─────────────────────────────────────────────
    if INDEX_PATH.exists() and STAMP_PATH.exists():
        logger.info("Metadata index already built, loading from cache…")
        with open(INDEX_PATH) as f:
            index = json.load(f)
    else:
        logger.info("Building metadata index (this takes a few minutes first time)…")
        index = build_metadata_index(str(IMAGES_DIR), str(INDEX_PATH))
        STAMP_PATH.write_text("done")

    app.state.metadata_index = index
    logger.info(f"✓ Metadata index ready  ({len(index)} images)")

    # ── Step 2: Descriptor store ───────────────────────────────────────────
    if os.path.exists(DESC_PATH):
        logger.info("Descriptor store already built, loading…")
    else:
        logger.info("Building ORB + colour histogram descriptors…")
        build_descriptor_store(index, str(PROJECT_ROOT), DESC_PATH)

    app.state.image_matcher = ImageMatcher(DESC_PATH, index)
    logger.info("✓ Image matcher ready")


# ──────────────────────────────────────────────────────────────────────────────
# Lifespan
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise state placeholders so routes can return 503 while building
    app.state.metadata_index = []
    app.state.image_matcher  = None

    # Initialise DB tables manually for MVP (in prod use Alembic)
    try:
        models.Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created/verified")
    except Exception as e:
        logger.error(f"Database error on startup: {e}")

    # Kick off build in background thread
    t = threading.Thread(target=_build_pipeline, args=(app,), daemon=True)
    t.start()

    yield  # server is running

    # (cleanup if needed)


# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Travel Pinterest API",
    description="Personalised travel feed + visual image matching. No auth, no DB.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for local dev / mobile emulator
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files ──────────────────────────────────────────────────────────────
# Serves images/train_set/Beach/img001.jpg at  /images/train_set/Beach/img001.jpg
if IMAGES_DIR.exists():
    app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")
    logger.info(f"Serving images from {IMAGES_DIR}")
else:
    logger.warning(f"images/ directory not found at {IMAGES_DIR}")

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(feed.router)
app.include_router(match.router)
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
app.include_router(webhook.router, prefix="/api/webhook", tags=["webhooks"])


@app.get("/health", tags=["health"])
def health():
    index_size  = len(app.state.metadata_index)
    matcher_ok  = app.state.image_matcher is not None
    return {
        "status":        "building" if index_size == 0 else "ok",
        "index_size":    index_size,
        "matcher_ready": matcher_ok,
    }


@app.post("/api/admin/rebuild", tags=["admin"])
def force_rebuild():
    """Delete build stamps and trigger a full rebuild in the background."""
    import shutil
    if STAMP_PATH.exists():
        STAMP_PATH.unlink()
    if os.path.exists(DESC_PATH):
        os.remove(DESC_PATH)
    if INDEX_PATH.exists():
        INDEX_PATH.unlink()
    app.state.metadata_index = []
    app.state.image_matcher  = None
    t = threading.Thread(target=_build_pipeline, args=(app,), daemon=True)
    t.start()
    return {"status": "rebuild started"}
