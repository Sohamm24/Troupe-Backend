"""
main.py — Travel Platform API
===============================
Community-driven travel platform connecting travelers with organizers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from core.database import engine
from core.database import Base
from core.exceptions import register_exception_handlers

# ── API Routers ───────────────────────────────────────────────────────────────
from modules.auth import router as auth
from modules.users import router as users
from modules.organizers import router as organizers
from modules.trips import router as trips
from modules.discussions import router as discussions
from modules.uploads import router as uploads
from modules.search import router as search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("travel_platform")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise DB tables on startup
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created/verified")
    except Exception as e:
        logger.error(f"Database error on startup: {e}")

    yield  # server is running


# ──────────────────────────────────────────────────────────────────────────────
# App
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Travel Platform API",
    description="Community-driven travel platform — trips, organizers, discussions",
    version="2.0.0",
    lifespan=lifespan,
)

# Register custom exception handlers (SRS response format)
register_exception_handlers(app)

# CORS — allow all origins for local dev / mobile emulator
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST Routes (all under /api/v1/) ─────────────────────────────────────────
app.include_router(auth.router,         prefix="/api/v1/auth",         tags=["authentication"])
app.include_router(users.router,        prefix="/api/v1/user",         tags=["users"])
app.include_router(organizers.router,   prefix="/api/v1/organizers",   tags=["organizers"])
app.include_router(trips.router,        prefix="/api/v1/trips",        tags=["trips"])
app.include_router(discussions.router,  prefix="/api/v1/discussions",  tags=["discussions"])
app.include_router(uploads.router,      prefix="/api/v1/uploads",      tags=["uploads"])
app.include_router(search.router,       prefix="/api/v1/search",       tags=["search"])
# ── Health Check ──────────────────────────────────────────────────────────────
@app.get("/api/v1/health", tags=["health"])
def health():
    return {"status": "UP"}

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return Response(status_code=200)

@app.get("/", tags=["health"], include_in_schema=False)
def root():
    return {"status": "UP", "service": "Travel Platform API"}

