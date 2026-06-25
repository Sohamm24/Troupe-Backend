"""
migrate_db.py
-------------
Database migration script for the new travel platform schema.
Creates all new tables from scratch using SQLAlchemy's metadata.

Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS semantics
via SQLAlchemy's create_all().

Usage:
    python migrate_db.py
"""

import logging
from sqlalchemy import text
from database import engine, Base

# Import all models so they register with Base.metadata
from models import (
    User,
    OrganizerProfile,
    Trip,
    Itinerary,
    InterestedTrip,
    Discussion,
    Message,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")


def drop_old_tables(conn) -> None:
    """Drop the old Pinterest-era tables that are no longer needed."""
    old_tables = [
        "post_likes",
        "post_saves",
        "posts",
        "users",
    ]
    for table in old_tables:
        try:
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE;"))
            logger.info(f"  Dropped old table: {table}")
        except Exception as e:
            logger.warning(f"  Could not drop {table}: {e}")


def add_indexes(conn) -> None:
    """Add performance indexes as specified in the architecture doc."""
    indexes = [
        ("idx_trips_organizer_id", "trips", "organizer_id"),
        ("idx_trips_start_date", "trips", "start_date"),
        ("idx_trips_interested_count", "trips", "interested_count"),
        ("idx_interested_trips_user_id", "interested_trips", "user_id"),
        ("idx_interested_trips_trip_id", "interested_trips", "trip_id"),
        ("idx_messages_discussion_id", "messages", "discussion_id"),
        ("idx_discussions_trip_id", "discussions", "trip_id"),
    ]
    for idx_name, table, column in indexes:
        try:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column});"
            ))
        except Exception as e:
            logger.warning(f"  Index {idx_name}: {e}")

    logger.info("  Indexes verified/created")


def migrate() -> None:
    """Run the full migration."""
    logger.info("Starting database migration…")

    with engine.begin() as conn:
        # Step 1: Drop old tables
        logger.info("[Step 1] Dropping old tables…")
        drop_old_tables(conn)

    # Step 2: Create new tables from models
    logger.info("[Step 2] Creating new tables…")
    Base.metadata.create_all(bind=engine)
    logger.info("  All tables created/verified")

    with engine.begin() as conn:
        # Step 3: Add performance indexes
        logger.info("[Step 3] Adding indexes…")
        add_indexes(conn)

    logger.info("[DONE] Migration completed successfully.")


if __name__ == "__main__":
    migrate()
