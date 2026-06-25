"""
api/v1/discussions.py
---------------------
POST   /trips/{id}/discussions           — Create discussion room
GET    /trips/{id}/discussions           — Get discussions + messages
POST   /discussions/{id}/messages        — Send message
GET    /discussions/{id}/messages        — Paginated message history
PATCH  /messages/{id}                    — Edit message (owner only)
DELETE /messages/{id}                    — Delete message (owner only)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from database import get_db
from core.dependencies import get_current_user
from models.user import User
from models.trip import Trip
from models.discussion import Discussion, Message
from models.interest import InterestedTrip
from schemas.discussion import (
    DiscussionResponse,
    MessageCreateRequest,
    MessageUpdateRequest,
    MessageResponse,
    MessageListResponse,
    MessageUserInfo,
)

router = APIRouter()
logger = logging.getLogger("travel_platform")


# ── Trip Discussion endpoints (mounted under /trips prefix in main) ──────────

@router.post("/trips/{trip_id}/discussions", status_code=status.HTTP_201_CREATED)
def create_discussion(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a discussion room for a trip (usually auto-created with trip)."""
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    # Check if a discussion already exists
    existing = db.query(Discussion).filter(Discussion.trip_id == trip.trip_id).first()
    if existing:
        return {
            "success": True,
            "data": {"discussion_id": str(existing.discussion_id)},
            "message": "Discussion already exists",
        }

    discussion = Discussion(trip_id=trip.trip_id)
    db.add(discussion)
    db.commit()
    db.refresh(discussion)

    return {
        "success": True,
        "data": {"discussion_id": str(discussion.discussion_id)},
        "message": "Discussion created",
    }


@router.get("/trips/{trip_id}/discussions", response_model=DiscussionResponse)
def get_trip_discussions(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get discussion with messages for a trip. User must be interested."""
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    discussion = (
        db.query(Discussion)
        .options(joinedload(Discussion.messages).joinedload(Message.user))
        .filter(Discussion.trip_id == trip.trip_id)
        .first()
    )
    if not discussion:
        raise HTTPException(status_code=404, detail="No discussion found for this trip")

    messages = []
    for msg in discussion.messages[-50:]:  # Return last 50 messages as preview
        user_info = None
        if msg.user:
            user_info = MessageUserInfo(
                user_id=str(msg.user.user_id),
                name=msg.user.name,
            )
        messages.append(MessageResponse(
            message_id=str(msg.message_id),
            discussion_id=str(msg.discussion_id),
            user_id=str(msg.user_id),
            user=user_info,
            content=msg.content,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
        ))

    return DiscussionResponse(
        discussion_id=str(discussion.discussion_id),
        trip_id=str(discussion.trip_id),
        messages=messages,
        created_at=discussion.created_at,
    )


# ── Message endpoints (mounted under /discussions prefix in main) ────────────

@router.post("/discussions/{discussion_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def send_message(
    discussion_id: str,
    payload: MessageCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a message in a discussion."""
    discussion = db.query(Discussion).filter(Discussion.discussion_id == discussion_id).first()
    if not discussion:
        raise HTTPException(status_code=404, detail="Discussion not found")

    message = Message(
        discussion_id=discussion.discussion_id,
        user_id=current_user.user_id,
        content=payload.message,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return MessageResponse(
        message_id=str(message.message_id),
        discussion_id=str(message.discussion_id),
        user_id=str(message.user_id),
        user=MessageUserInfo(
            user_id=str(current_user.user_id),
            name=current_user.name,
        ),
        content=message.content,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


@router.get("/discussions/{discussion_id}/messages", response_model=MessageListResponse)
def get_messages(
    discussion_id: str,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get paginated message history for a discussion."""
    discussion = db.query(Discussion).filter(Discussion.discussion_id == discussion_id).first()
    if not discussion:
        raise HTTPException(status_code=404, detail="Discussion not found")

    per_page = 50
    total = db.query(Message).filter(Message.discussion_id == discussion.discussion_id).count()

    msgs = (
        db.query(Message)
        .options(joinedload(Message.user))
        .filter(Message.discussion_id == discussion.discussion_id)
        .order_by(Message.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    messages = []
    for msg in reversed(msgs):  # Chronological order
        user_info = None
        if msg.user:
            user_info = MessageUserInfo(
                user_id=str(msg.user.user_id),
                name=msg.user.name,
            )
        messages.append(MessageResponse(
            message_id=str(msg.message_id),
            discussion_id=str(msg.discussion_id),
            user_id=str(msg.user_id),
            user=user_info,
            content=msg.content,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
        ))

    return MessageListResponse(messages=messages, page=page, total=total)


# ── Message edit/delete (mounted under /messages prefix in main) ─────────────

@router.patch("/messages/{message_id}", response_model=MessageResponse)
def edit_message(
    message_id: str,
    payload: MessageUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Edit a message. Only the message owner can edit."""
    message = db.query(Message).filter(Message.message_id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")

    message.content = payload.message
    db.commit()
    db.refresh(message)

    return MessageResponse(
        message_id=str(message.message_id),
        discussion_id=str(message.discussion_id),
        user_id=str(message.user_id),
        content=message.content,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a message. Only the message owner can delete."""
    message = db.query(Message).filter(Message.message_id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")

    db.delete(message)
    db.commit()
