from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from modules.users.models import User
from modules.discussions.schemas import (
    DiscussionResponse, MessageCreateRequest, MessageUpdateRequest, MessageResponse, MessageListResponse, MessageUserInfo
)
from modules.discussions.repository import (
    get_trip_for_discussion, get_discussion_by_trip, create_discussion, get_discussion_with_messages,
    get_discussion_by_id, create_message, get_message_count, get_messages_for_discussion, get_message_by_id,
    update_message, delete_message
)

def process_create_discussion(trip_id: str, current_user: User, db: Session):
    trip = get_trip_for_discussion(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    existing = get_discussion_by_trip(db, trip.trip_id)
    if existing:
        return {"success": True, "data": {"discussion_id": str(existing.discussion_id)}, "message": "Discussion already exists"}
    discussion = create_discussion(db, trip.trip_id)
    return {"success": True, "data": {"discussion_id": str(discussion.discussion_id)}, "message": "Discussion created"}

def process_get_trip_discussions(trip_id: str, current_user: User, db: Session):
    trip = get_trip_for_discussion(db, trip_id)
    if not trip: raise HTTPException(status_code=404, detail="Trip not found")
    discussion = get_discussion_with_messages(db, trip.trip_id)
    if not discussion: raise HTTPException(status_code=404, detail="No discussion found for this trip")

    messages = []
    for msg in discussion.messages[-50:]:
        user_info = None
        if msg.user:
            user_info = MessageUserInfo(user_id=str(msg.user.user_id), name=msg.user.name)
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

def process_send_message(discussion_id: str, payload: MessageCreateRequest, current_user: User, db: Session):
    discussion = get_discussion_by_id(db, discussion_id)
    if not discussion: raise HTTPException(status_code=404, detail="Discussion not found")
    message = create_message(db, discussion.discussion_id, current_user.user_id, payload.message)
    return MessageResponse(
        message_id=str(message.message_id),
        discussion_id=str(message.discussion_id),
        user_id=str(message.user_id),
        user=MessageUserInfo(user_id=str(current_user.user_id), name=current_user.name),
        content=message.content,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )

def process_get_messages(discussion_id: str, page: int, db: Session):
    discussion = get_discussion_by_id(db, discussion_id)
    if not discussion: raise HTTPException(status_code=404, detail="Discussion not found")
    per_page = 50
    total = get_message_count(db, discussion.discussion_id)
    msgs = get_messages_for_discussion(db, discussion.discussion_id, page, per_page)
    
    messages = []
    for msg in reversed(msgs):
        user_info = None
        if msg.user: user_info = MessageUserInfo(user_id=str(msg.user.user_id), name=msg.user.name)
        messages.append(MessageResponse(
            message_id=str(msg.message_id), discussion_id=str(msg.discussion_id), user_id=str(msg.user_id),
            user=user_info, content=msg.content, created_at=msg.created_at, updated_at=msg.updated_at,
        ))
    return MessageListResponse(messages=messages, page=page, total=total)

def process_edit_message(message_id: str, payload: MessageUpdateRequest, current_user: User, db: Session):
    message = get_message_by_id(db, message_id)
    if not message: raise HTTPException(status_code=404, detail="Message not found")
    if message.user_id != current_user.user_id: raise HTTPException(status_code=403, detail="You can only edit your own messages")
    message.content = payload.message
    update_message(db, message)
    return MessageResponse(
        message_id=str(message.message_id), discussion_id=str(message.discussion_id), user_id=str(message.user_id),
        content=message.content, created_at=message.created_at, updated_at=message.updated_at,
    )

def process_delete_message(message_id: str, current_user: User, db: Session):
    message = get_message_by_id(db, message_id)
    if not message: raise HTTPException(status_code=404, detail="Message not found")
    if message.user_id != current_user.user_id: raise HTTPException(status_code=403, detail="You can only delete your own messages")
    delete_message(db, message)
