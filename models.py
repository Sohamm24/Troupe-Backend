from sqlalchemy import Column, Integer, String, Text, ForeignKey, TIMESTAMP, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    clerk_id = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    posts = relationship("Post", back_populates="owner")

class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    image_urls = Column(ARRAY(String), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="posts")
