from sqlalchemy.orm import Session, joinedload
from modules.trips.models import Trip
from modules.discussions.models import Discussion, Message

def get_trip_for_discussion(db: Session, trip_id: str):
    return db.query(Trip).filter(Trip.trip_id == trip_id).first()

def get_discussion_by_trip(db: Session, trip_id: str):
    return db.query(Discussion).filter(Discussion.trip_id == trip_id).first()

def create_discussion(db: Session, trip_id: str):
    discussion = Discussion(trip_id=trip_id)
    db.add(discussion)
    db.commit()
    db.refresh(discussion)
    return discussion

def get_discussion_with_messages(db: Session, trip_id: str):
    return (
        db.query(Discussion)
        .options(joinedload(Discussion.messages).joinedload(Message.user))
        .filter(Discussion.trip_id == trip_id)
        .first()
    )

def get_discussion_by_id(db: Session, discussion_id: str):
    return db.query(Discussion).filter(Discussion.discussion_id == discussion_id).first()

def create_message(db: Session, discussion_id: str, user_id: str, content: str):
    message = Message(discussion_id=discussion_id, user_id=user_id, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

def get_message_count(db: Session, discussion_id: str):
    return db.query(Message).filter(Message.discussion_id == discussion_id).count()

def get_messages_for_discussion(db: Session, discussion_id: str, page: int, per_page: int):
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

def update_message(db: Session, message: Message):
    db.commit()
    db.refresh(message)
    return message

def delete_message(db: Session, message: Message):
    db.delete(message)
    db.commit()
