from sqlalchemy.orm import Session, joinedload
from modules.trips.models import Trip
from modules.discussions.models import Discussion, Message, UserDiscussion
from modules.discussions.schemas import MessageCreateRequest


def get_trip_for_discussion(db: Session, trip_id: str):
    return db.query(Trip).filter(Trip.trip_id == trip_id).first()


def get_discussion_by_trip(db: Session, trip_id: str):
    return db.query(Discussion).filter(Discussion.trip_id == trip_id).first()


def create_discussion(db: Session, trip_id: str, commit: bool = True) -> Discussion:
    discussion = Discussion(trip_id=trip_id)
    db.add(discussion)
    if commit:
        db.commit()
        db.refresh(discussion)
    return discussion

def add_participant_to_discussion(db: Session,discussion_id,user_id):
    participant = UserDiscussion(discussion_id=discussion_id,user_id=user_id,)
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant    

def is_user_interested(db: Session, discussion_id: str, user_id: str) -> bool:
    return (
        db.query(UserDiscussion).filter( UserDiscussion.discussion_id == discussion_id,
        UserDiscussion.user_id == user_id )
        .first()
        is not None
    )

def get_discussion_with_messages(db: Session, trip_id: str):
    return (
        db.query(Discussion)
        .options(joinedload(Discussion.messages).joinedload(Message.user))
        .filter(Discussion.trip_id == trip_id)
        .first()
    )


def get_discussion_by_id(db: Session, discussion_id: str):
    return db.query(Discussion).filter(Discussion.discussion_id == discussion_id).first()


def create_message(
    db: Session,
    discussion_id: str,
    user_id: str,
    payload: MessageCreateRequest,
) -> Message:
    """Create a message from a full MessageCreateRequest payload."""
    message = Message(
        discussion_id=discussion_id,
        user_id=user_id,
        type=payload.type,
        text=payload.text,
        media_url=payload.media_url,
        mime_type=payload.mime_type,
        file_name=payload.file_name,
        file_size=payload.file_size,
        thumbnail_url=payload.thumbnail_url,
        location=payload.location,
        reply_to_message_id=payload.reply_to_message_id,
        client_timestamp=payload.client_timestamp,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_message_count(db: Session, discussion_id: str) -> int:
    return db.query(Message).filter(Message.discussion_id == discussion_id).count()


def get_messages_for_discussion(
    db: Session,
    discussion_id: str,
    page: int,
    per_page: int,
):
    """Returns messages newest-first (caller reverses if needed)."""
    return (
        db.query(Message)
        .options(joinedload(Message.user))
        .filter(Message.discussion_id == discussion_id)
        .order_by(Message.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )


def get_message_by_id(db: Session, message_id: str):
    return db.query(Message).filter(Message.message_id == message_id).first()


def update_message(db: Session, message: Message) -> Message:
    db.commit()
    db.refresh(message)
    return message


def delete_message(db: Session, message: Message) -> None:
    db.delete(message)
    db.commit()


def delete_discussion(db: Session, discussion: Discussion) -> None:
    db.delete(discussion)
    db.commit()


def delete_discussion_for_traveller(
    db: Session, discussion_id: str, user_id: str
) -> None:
    """Remove the UserDiscussion join-row so the traveller leaves the discussion."""
    row = (
        db.query(UserDiscussion)
        .filter(
            UserDiscussion.discussion_id == discussion_id,
            UserDiscussion.user_id == user_id,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()