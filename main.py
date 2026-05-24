"""
main.py — Travel Pinterest MVP Backend
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import feed, webhook, posts, user
from database import engine
import models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("travel_pinterest")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise DB tables
    try:
        models.Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created/verified")
    except Exception as e:
        logger.error(f"Database error on startup: {e}")

    yield  # server is running


# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Travel Pinterest API",
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

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(feed.router, prefix="/api/feed", tags=["feed"])
app.include_router(posts.router, prefix="/api/posts", tags=["posts"])
app.include_router(user.router,  prefix="/api/user",  tags=["user"])
app.include_router(webhook.router, prefix="/api/webhook", tags=["webhooks"])


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
