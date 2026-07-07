from modules.trips.models import TripStatus
from modules.organizers.models import OrganizerProfile
from core.dependencies import require_organizer
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException
from modules.users.models import User
from modules.discussions.schemas import (
    DiscussionResponse, MessageCreateRequest, MessageUpdateRequest,
    MessageResponse, MessageListResponse, MessageUserInfo
)
from modules.discussions.repository import (
    get_trip_for_discussion, get_discussion_by_trip, create_discussion,
    get_discussion_with_messages, get_discussion_by_id, create_message,
    get_message_count, get_messages_for_discussion, get_message_by_id,
    update_message, delete_message as repo_delete_message,
    delete_discussion as repo_delete_discussion,
    delete_discussion_for_traveller as repo_delete_discussion_for_traveller,
    add_participant_to_discussion
)

def _build_message_response(msg, user=None) -> MessageResponse:
    """Helper to build a MessageResponse from a Message ORM object."""
    user_info = None
    if user:
        user_info = MessageUserInfo(user_id=str(user.user_id), name=user.name)
    elif msg.user:
        user_info = MessageUserInfo(user_id=str(msg.user.user_id), name=msg.user.name)

    return MessageResponse(
        message_id=str(msg.message_id),
        discussion_id=str(msg.discussion_id),
        user_id=str(msg.user_id),
        user=user_info,
        type=msg.type,
        status=msg.status,
        text=msg.text,
        media_url=msg.media_url,
        mime_type=msg.mime_type,
        file_name=msg.file_name,
        file_size=msg.file_size,
        thumbnail_url=msg.thumbnail_url,
        location=msg.location,
        reply_to_message_id=str(msg.reply_to_message_id) if msg.reply_to_message_id else None,
        client_timestamp=msg.client_timestamp,
        server_timestamp=msg.server_timestamp,
        is_edited=msg.is_edited,
        is_deleted=msg.is_deleted,
        created_at=msg.created_at,
        updated_at=msg.updated_at,
        edited_at=msg.edited_at,
        deleted_at=msg.deleted_at,
    )

def create_trip_discussion(trip_id: str, organizer_data, db: Session, commit: bool = True):
    trip = get_trip_for_discussion(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
 

    # Only the trip organizer may open a discussion
    if not organizer_data or trip.organizer_id != organizer_data.organizer_id:
        raise HTTPException(
            status_code=403,
            detail="Only the trip organizer can create a discussion",
        )
        
    discussion = create_discussion(db, trip.trip_id, commit=commit)
    return {
        "success": True,
        "data": {"discussion_id": str(discussion.discussion_id)},
        "message": "Discussion created",
    }

def join_trip_discussion(trip_id: str, current_user: User, db: Session):
    trip = get_trip_for_discussion(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404,detail="Trip not found")

    if trip.organizer_id == current_user.user_id:
        raise HTTPException(status_code=403, detail="You are the organizer of this trip")
    
    if trip.status != TripStatus.PUBLISHED:
        raise HTTPException(status_code=403, detail="You can only join published trips")    

    discussion = get_discussion_by_trip(db, trip.trip_id)
    if not discussion:
        raise HTTPException(
            status_code=404,
            detail="Discussion not found",
        )

    add_participant_to_discussion(
        db,
        discussion.discussion_id,
        current_user.user_id,
    )

    return {
        "success": True,
        "message": "Joined discussion successfully",
        "data": {
            "discussion_id": str(discussion.discussion_id)
        },
    }

def get_traveller_discussions(trip_id: str, current_user: User, db: Session):
    """
    Returns the DiscussionResponse for a traveller — mirrors the organizer view.
    (Access-control differences between roles should be enforced at the router layer.)
    """
    trip = get_trip_for_discussion(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    discussion = get_discussion_with_messages(db, trip.trip_id)
    if not discussion:
        raise HTTPException(status_code=404, detail="No discussion found for this trip")

    messages = [_build_message_response(msg) for msg in discussion.messages[-50:]]

    return DiscussionResponse(
        discussion_id=str(discussion.discussion_id),
        trip_id=str(discussion.trip_id),
        messages=messages,
        created_at=discussion.created_at,
    )


def get_organizer_discussions(trip_id: str, current_user: User, db: Session):
    trip = get_trip_for_discussion(db, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    discussion = get_discussion_with_messages(db, trip.trip_id)
    if not discussion:
        raise HTTPException(status_code=404, detail="No discussion found for this trip")

    messages = [_build_message_response(msg) for msg in discussion.messages[-50:]]

    return DiscussionResponse(
        discussion_id=str(discussion.discussion_id),
        trip_id=str(discussion.trip_id),
        messages=messages,
        created_at=discussion.created_at,
    )


def save_message(
    discussion_id: str,
    payload: MessageCreateRequest,
    current_user: User,
    db: Session,
) -> MessageResponse:
    discussion = get_discussion_by_id(db, discussion_id)
    if not discussion:
        raise HTTPException(status_code=404, detail="Discussion not found")

    message = create_message(db, discussion.discussion_id, current_user.user_id, payload)
    return _build_message_response(message, user=current_user)


def process_get_messages(discussion_id: str, page: int, db: Session) -> MessageListResponse:
    discussion = get_discussion_by_id(db, discussion_id)
    if not discussion:
        raise HTTPException(status_code=404, detail="Discussion not found")

    per_page = 50
    total = get_message_count(db, discussion.discussion_id)
    # Repository returns newest-first; reverse so the response is oldest-first.
    msgs = get_messages_for_discussion(db, discussion.discussion_id, page, per_page)
    messages = [_build_message_response(msg) for msg in reversed(msgs)]

    return MessageListResponse(messages=messages, page=page, total=total)


def edit_message(
    message_id: str,
    payload: MessageUpdateRequest,
    current_user: User,
    db: Session,
) -> MessageResponse:
    message = get_message_by_id(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")

    message.text = payload.text
    message.is_edited = True
    update_message(db, message)
    return _build_message_response(message)


def remove_message(
    message_id: str,
    current_user: User,
    db: Session,
) -> None:
    """Soft-or-hard delete a single message (hard delete via repository)."""
    message = get_message_by_id(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own messages")
    repo_delete_message(db, message)


def remove_discussion(
    discussion_id: str,
    current_user: User,
    db: Session,
) -> None:
    """Organizer deletes an entire discussion."""
    discussion = get_discussion_by_id(db, discussion_id)
    if not discussion:
        raise HTTPException(status_code=404, detail="Discussion not found")
    if discussion.organizer_id != current_user.organizer_profile.organizer_id:
        raise HTTPException(status_code=403, detail="You can only delete your own discussion")
    repo_delete_discussion(db, discussion)


def leave_discussion(
    discussion_id: str,
    current_user: User,
    db: Session,
) -> None:
    """Traveller leaves / removes themselves from a discussion."""
    discussion = get_discussion_by_id(db, discussion_id)
    if not discussion:
        raise HTTPException(status_code=404, detail="Discussion not found")
    repo_delete_discussion_for_traveller(db, discussion_id, current_user.user_id)