from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import httpx
import uuid
import logging
import asyncio

from database import get_db
from models import Post, User
from schemas import PostOut, PostCreate

router = APIRouter()
logger = logging.getLogger("travel_pinterest")

# Verify current user from Clerk ID passed in Authorization Header
async def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    clerk_id = authorization.replace("Bearer ", "")
    user = db.query(User).filter(User.clerk_id == clerk_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def upload_to_supabase(file_bytes: bytes, filename: str, content_type: str) -> str:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_key or not supabase_url:
        raise HTTPException(status_code=500, detail="Supabase credentials not configured")

    bucket_name = "travel-pinterest"
    upload_url = f"{supabase_url}/storage/v1/object/{bucket_name}/{filename}"
    
    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apikey": supabase_key,
        "Content-Type": content_type
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(upload_url, content=file_bytes, headers=headers)
        if response.status_code >= 400:
            logger.error(f"Supabase upload failed: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to upload image")
            
    # Return public URL
    return f"{supabase_url}/storage/v1/object/public/{bucket_name}/{filename}"


@router.post("/", response_model=PostOut)
async def create_post(
    description: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    images: List[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        uploaded_urls = []
        for image in images:
            file_bytes = await image.read()
            file_ext = image.filename.split('.')[-1] if '.' in image.filename else 'jpg'
            unique_filename = f"{uuid.uuid4()}.{file_ext}"
            
            url = await upload_to_supabase(file_bytes, unique_filename, image.content_type)
            uploaded_urls.append(url)
            
        new_post = Post(
            user_id=current_user.id,
            description=description,
            location=location,
            image_urls=uploaded_urls
        )
        db.add(new_post)
        db.commit()
        db.refresh(new_post)
        return new_post
    except Exception as e:
        logger.error(f"Error creating post: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user", response_model=List[PostOut])
async def get_user_posts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Post).filter(Post.user_id == current_user.id).order_by(Post.created_at.desc()).all()
