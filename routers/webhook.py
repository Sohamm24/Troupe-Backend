from fastapi import APIRouter, Request, HTTPException, Depends
from svix.webhooks import Webhook, WebhookVerificationError
from sqlalchemy.orm import Session
import os
import logging

from database import get_db
from models import User

router = APIRouter()
logger = logging.getLogger("travel_pinterest")

@router.post("/clerk")
async def clerk_webhook(request: Request, db: Session = Depends(get_db)):
    secret = os.getenv("CLERK_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="Missing webhooks secret")
    
    payload = await request.body()
    headers = request.headers
    
    svix_id = headers.get("svix-id")
    svix_timestamp = headers.get("svix-timestamp")
    svix_signature = headers.get("svix-signature")
    
    if not svix_id or not svix_timestamp or not svix_signature:
        raise HTTPException(status_code=400, detail="Missing svix headers")
        
    wh = Webhook(secret)
    try:
        evt = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        logger.error("Webhook verification failed")
        raise HTTPException(status_code=400, detail=str(e))
        
    event_type = evt.get("type")
    data = evt.get("data")
    
    if event_type == "user.created":
        external_id = data.get("id")
        email_addresses = data.get("email_addresses", [])
        email = email_addresses[0].get("email_address") if email_addresses else None
        first_name = data.get("first_name") or None
        last_name  = data.get("last_name")  or None
        username   = data.get("username")   or None
        image_url  = data.get("image_url")  or None

        existing = db.query(User).filter(User.external_id == external_id).first()
        if not existing:
            new_user = User(
                external_id=external_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                username=username,
                profile_pic_url=image_url,
            )
            db.add(new_user)
            db.commit()
            logger.info(f"Created user {external_id} in Neon DB.")

    elif event_type == "user.updated":
        external_id = data.get("id")
        user = db.query(User).filter(User.extenral_id == external_id).first()
        if user:
            # Only overwrite if the field is not already set by onboarding
            if not user.first_name:
                user.first_name = data.get("first_name") or None
            if not user.last_name:
                user.last_name = data.get("last_name") or None
            if not user.username:
                user.username = data.get("username") or None
            if not user.profile_pic_url:
                user.profile_pic_url = data.get("image_url") or None
            db.commit()
            logger.info(f"Updated user {external_id} in Neon DB.")
                
    elif event_type == "user.deleted":
        external_id = data.get("id")
        user = db.query(User).filter(User.external_id == external_id).first()
        if user:
            db.delete(user)
            db.commit()
            logger.info(f"Deleted user {external_id} from Neon DB.")
            
    return {"success": True}
