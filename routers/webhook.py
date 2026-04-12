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
        clerk_id = data.get("id")
        email_addresses = data.get("email_addresses", [])
        if email_addresses:
            email = email_addresses[0].get("email_address")
            
            # Create user in db
            existing = db.query(User).filter(User.clerk_id == clerk_id).first()
            if not existing:
                new_user = User(clerk_id=clerk_id, email=email)
                db.add(new_user)
                db.commit()
                logger.info(f"Created user {clerk_id} in Neon DB.")
                
    elif event_type == "user.deleted":
        clerk_id = data.get("id")
        user = db.query(User).filter(User.clerk_id == clerk_id).first()
        if user:
            db.delete(user)
            db.commit()
            logger.info(f"Deleted user {clerk_id} from Neon DB.")
            
    return {"success": True}
