"""
models.py
---------
SQLAlchemy ORM models.
Updated Post model adds: tags, likes, saves, trip_start, trip_end,
single image_url (replacing image_urls array), location as JSON string,
and a SigLIP2 vector embedding for pgvector similarity search.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class PostLike(Base):
    __tablename__ = "post_likes"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    post_id    = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    
    __table_args__ = (UniqueConstraint('user_id', 'post_id', name='uq_post_like_user_post'),)


class PostSave(Base):
    __tablename__ = "post_saves"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    post_id    = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint('user_id', 'post_id', name='uq_post_save_user_post'),)


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
    post_likes = relationship("PostLike", backref="user", cascade="all, delete-orphan")
    post_saves = relationship("PostSave", backref="user", cascade="all, delete-orphan")

    @property
    def liked_post_ids(self):
        return [like.post_id for like in self.post_likes]

    @property
    def saved_post_ids(self):
        return [save.post_id for save in self.post_saves]


class Post(Base):
    __tablename__ = "posts"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=True)

    # Single image URL (Legacy, kept for backwards compatibility)
    image_url   = Column(String, nullable=True)

    # Array of image URLs for multiple pics
    media_urls  = Column(JSONB, nullable=True, default=[])

    # Location stored as a JSON string: {"name": "...", "lat": 0.0, "lng": 0.0}
    location = Column(JSONB, nullable=True)

    # Auto-generated tags from OpenCV colour analysis (comma-separated for simplicity)
    tags        = Column(ARRAY(String), nullable=True, default=[])

    # Engagement counters
    likes       = Column(Integer, default=0, nullable=False)
    saves       = Column(Integer, default=0, nullable=False) 

    # Trip duration (stored as plain strings YYYY-MM-DD) - Legacy
    trip_start  = Column(String, nullable=True)
    trip_end    = Column(String, nullable=True)
    
    # Trip duration in days
    trip_days   = Column(Integer, nullable=True)

    # SigLIP2 embedding for pgvector cosine similarity search
    embedding = Column(Vector(512), nullable=True)

    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="posts")
    post_likes = relationship("PostLike", backref="post", cascade="all, delete-orphan")
    post_saves = relationship("PostSave", backref="post", cascade="all, delete-orphan")
