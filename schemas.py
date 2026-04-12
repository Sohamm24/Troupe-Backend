from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class PostBase(BaseModel):
    description: Optional[str] = None
    location: Optional[str] = None
    image_urls: List[str]

class PostCreate(PostBase):
    pass

class PostOut(PostBase):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class UserOut(BaseModel):
    id: int
    clerk_id: str
    email: str
    created_at: datetime
    posts: List[PostOut] = []

    class Config:
        from_attributes = True
