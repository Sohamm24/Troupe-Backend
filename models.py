"""
models.py
---------
SQLAlchemy ORM models.
Updated Post model adds: tags, likes, saves, trip_start, trip_end,
single image_url (replacing image_urls array), and location as JSON string.
"""

from sqlalchemy.dialects.postgresql import JSONB,ARRAY
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, TIMESTAMP
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id          = Column(Integer, primary_key=True, index=True)
    external_id    = Column(String, unique=True, index=True, nullable=False)
    email       = Column(String, unique=True, index=True, nullable=True)
    username    = Column(String, unique=True, index=True, nullable=True)
    first_name  = Column(String, nullable=True)
    last_name   = Column(String, nullable=True)
    profile_pic_url  = Column(String, nullable=True)
    onboarded   = Column(Boolean, default=False, nullable=False)
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())

    posts = relationship("Post", back_populates="owner")


class Post(Base):
    __tablename__ = "posts"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=True)

    # Single image URL
    image_url   = Column(String, nullable=False)

    # Location stored as a JSON string: {"name": "...", "lat": 0.0, "lng": 0.0}
    location = Column(JSONB, nullable=True)

    # Auto-generated tags from OpenCV colour analysis (comma-separated for simplicity)
    tags        = Column(ARRAY(String), nullable=True, default=[])

    # Engagement counters
    likes       = Column(Integer, default=0, nullable=False)
    saves       = Column(Integer, default=0, nullable=False) 

    # Trip duration (stored as plain strings YYYY-MM-DD)
    trip_start  = Column(String, nullable=True)
    trip_end    = Column(String, nullable=True)

    # Visual features for similarity search
    # Structure: {"hsv_histogram": [float, float, ...]}
    image_features = Column(JSONB, nullable=True)

    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="posts")
