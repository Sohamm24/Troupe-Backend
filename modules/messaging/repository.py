"""
modules/messaging/repository.py
--------------------------------
All database operations for the messaging module.
No business logic — pure data access.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from modules.messaging.models import Chat, UserChat, Message, MessageStatus
from modules.users.models import User
from modules.organizers.models import OrganizerProfile


# ── Chat / UserChat ──────────────────────────────────────────────────────────

def get_chat_between(db: Session, user_a_id: str, user_b_id: str) -> Optional[Chat]:
    """Find an existing chat shared by both users."""
    row = (
        db.query(UserChat)
        .filter(
            UserChat.user_id == user_a_id,
            UserChat.chat_id.in_(
                db.query(UserChat.chat_id).filter(UserChat.user_id == user_b_id)
            ),
        )
        .first()
    )
    return row.chat if row else None


def get_or_create_chat(
    db: Session, user_a_id: str, user_b_id: str
) -> Tuple[Chat, UserChat, UserChat]:
    """Find or atomically create a 1-to-1 chat between two users.

    Returns (chat, user_chat_for_a, user_chat_for_b).
    The chat is NOT committed here — callers commit when ready.
    """
    # Check if a shared chat already exists
    existing_uc = (
        db.query(UserChat)
        .filter(
            UserChat.user_id == user_a_id,
            UserChat.chat_id.in_(
                db.query(UserChat.chat_id).filter(UserChat.user_id == user_b_id)
            ),
        )
        .options(joinedload(UserChat.chat))
        .first()
    )
    if existing_uc:
        chat = existing_uc.chat
        uc_a = existing_uc
        uc_b = (
            db.query(UserChat)
            .filter(UserChat.chat_id == chat.chat_id, UserChat.user_id == user_b_id)
            .first()
        )
        return chat, uc_a, uc_b

    # Create new chat + two UserChat rows
    chat = Chat()
    db.add(chat)
    db.flush()  # get chat_id without committing

    uc_a = UserChat(
        user_chat_id=uuid.uuid4(),
        user_id=user_a_id,
        chat_id=chat.chat_id,
        last_read_timestamp=datetime.utcnow(),
        unread_count=0,
    )
    uc_b = UserChat(
        user_chat_id=uuid.uuid4(),
        user_id=user_b_id,
        chat_id=chat.chat_id,
        last_read_timestamp=datetime.utcnow(),
        unread_count=0,
    )
    db.add_all([uc_a, uc_b])
    db.flush()
    return chat, uc_a, uc_b


def get_user_chats(db: Session, user_id: str) -> List[UserChat]:
    """Return all UserChat rows for *user_id*, newest-last-message first."""
    rows = (
        db.query(UserChat)
        .filter(UserChat.user_id == user_id)
        .options(
            joinedload(UserChat.last_message).joinedload(Message.reply_to_message),
            joinedload(UserChat.user).joinedload(User.organizer_profile),
            joinedload(UserChat.chat).joinedload(Chat.userchats).joinedload(UserChat.user).joinedload(User.organizer_profile),
        )
        .all()
    )
    # Sort by last_message.created_at descending (nulls last)
    def _sort_key(uc: UserChat):
        if uc.last_message:
            return uc.last_message.created_at
        return uc.chat.created_at if uc.chat else datetime.min

    rows.sort(key=_sort_key, reverse=True)
    return rows


# ── Messages ─────────────────────────────────────────────────────────────────

def get_last_n_messages(db: Session, chat_id: str, n: int = 50) -> List[Message]:
    """Return the last *n* messages in *chat_id*, oldest-first.

    Note: Soft-deleted messages ARE included (is_deleted=True) so that reply
    context ("Message deleted") can be displayed correctly in the UI.
    """
    rows = (
        db.query(Message)
        .filter(Message.chat_id == chat_id)
        .options(joinedload(Message.reply_to_message))
        .order_by(Message.message_id.desc())
        .limit(n)
        .all()
    )
    rows.reverse()
    return rows


def get_messages_after(
    db: Session, chat_id: str, after_message_id: int, limit: int = 50
) -> List[Message]:
    """Return messages sent AFTER *after_message_id* (for race-condition catch-up).

    Includes soft-deleted messages for consistency with get_last_n_messages.
    """
    return (
        db.query(Message)
        .filter(
            Message.chat_id == chat_id,
            Message.message_id > after_message_id,
        )
        .options(joinedload(Message.reply_to_message))
        .order_by(Message.message_id.asc())
        .limit(limit)
        .all()
    )


def get_message_by_id(db: Session, message_id: int) -> Optional[Message]:
    """Return a single Message by its primary key, or None."""
    return (
        db.query(Message)
        .filter(Message.message_id == message_id)
        .options(joinedload(Message.reply_to_message))
        .first()
    )


def create_message(
    db: Session,
    chat_id: str,
    sender_id: str,
    text: str,
    reply_to_id: Optional[int] = None,
) -> Message:
    """Insert a new message and return the ORM object (not committed)."""
    msg = Message(
        chat_id=chat_id,
        sender_id=sender_id,
        text=text,
        is_edited=False,
        is_deleted=False,
        reply_to_message_id=reply_to_id,
        status=MessageStatus.SENT,
        created_at=datetime.utcnow(),
    )
    db.add(msg)
    db.flush()  # populate message_id
    return msg


def soft_delete_message(
    db: Session, message_id: int, requesting_user_id: str
) -> Optional[Message]:
    """Soft-delete a message. Only the original sender may delete their own message.

    Returns the updated Message on success, or None if not found / not authorised.
    """
    msg = db.query(Message).filter(Message.message_id == message_id).first()
    if not msg:
        return None
    if str(msg.sender_id) != str(requesting_user_id):
        return None  # not the sender — reject silently
    msg.is_deleted = True
    msg.text = ""   # wipe content for privacy
    db.flush()
    return msg


def edit_message(
    db: Session, message_id: int, requesting_user_id: str, new_text: str
) -> Optional[Message]:
    """Edit a message's text. Only the original sender may edit.

    Returns the updated Message on success, or None if not found / not authorised.
    """
    msg = db.query(Message).filter(Message.message_id == message_id).first()
    if not msg:
        return None
    if str(msg.sender_id) != str(requesting_user_id):
        return None
    if msg.is_deleted:
        return None  # cannot edit a deleted message
    msg.text = new_text.strip()
    msg.is_edited = True
    db.flush()
    return msg


def mark_messages_read(
    db: Session, chat_id: str, reader_user_id: str
) -> List[int]:
    """Mark all unread incoming messages as READ for the reader.

    Only updates messages sent by someone else (not the reader) that are not
    already READ. Returns the list of message_ids that were updated so the
    service layer can notify the original senders.
    """
    messages = (
        db.query(Message)
        .filter(
            Message.chat_id == chat_id,
            Message.sender_id != reader_user_id,
            Message.status != MessageStatus.READ,
            Message.is_deleted == False,
        )
        .all()
    )
    updated_ids: List[int] = []
    for msg in messages:
        msg.status = MessageStatus.READ
        updated_ids.append(msg.message_id)
    if updated_ids:
        db.flush()
    return updated_ids


def update_message_status(
    db: Session, message_id: int, new_status: MessageStatus
) -> Optional[Message]:
    """Update the delivery status of a single message."""
    msg = db.query(Message).filter(Message.message_id == message_id).first()
    if msg:
        msg.status = new_status
        db.flush()
    return msg


# ── Read receipts ─────────────────────────────────────────────────────────────

def mark_as_read(db: Session, user_chat_id: str, user_id: str) -> None:
    """Reset unread_count and update last_read_timestamp for the given UserChat."""
    uc = (
        db.query(UserChat)
        .filter(UserChat.user_chat_id == user_chat_id, UserChat.user_id == user_id)
        .first()
    )
    if uc:
        uc.unread_count = 0
        uc.last_read_timestamp = datetime.utcnow()
        db.flush()


def update_last_message(db: Session, chat_id: str, message_id: int) -> None:
    """Update last_message_id for all participants in the chat."""
    rows: List[UserChat] = (
        db.query(UserChat).filter(UserChat.chat_id == chat_id).all()
    )
    for uc in rows:
        uc.last_message_id = message_id
    db.flush()


def increment_unread_for_recipient(
    db: Session, chat_id: str, sender_id: str
) -> None:
    """Increment unread_count for every participant in the chat except the sender."""
    rows: List[UserChat] = (
        db.query(UserChat)
        .filter(UserChat.chat_id == chat_id, UserChat.user_id != sender_id)
        .all()
    )
    for uc in rows:
        uc.unread_count = (uc.unread_count or 0) + 1
    db.flush()


def reset_unread_for_user(db: Session, chat_id: str, user_id: str) -> None:
    """Reset unread_count to zero for *user_id* in *chat_id*."""
    uc = (
        db.query(UserChat)
        .filter(UserChat.chat_id == chat_id, UserChat.user_id == user_id)
        .first()
    )
    if uc:
        uc.unread_count = 0
        uc.last_read_timestamp = datetime.utcnow()
        db.flush()


def get_other_participant_user_chat(
    db: Session, chat_id: str, exclude_user_id: str
) -> Optional[UserChat]:
    """Return the UserChat belonging to the other participant."""
    return (
        db.query(UserChat)
        .filter(UserChat.chat_id == chat_id, UserChat.user_id != exclude_user_id)
        .first()
    )


def get_user_chat_by_chat_and_user(
    db: Session, chat_id: str, user_id: str
) -> Optional[UserChat]:
    """Return the UserChat for a specific user in a specific chat."""
    return (
        db.query(UserChat)
        .filter(UserChat.chat_id == chat_id, UserChat.user_id == user_id)
        .first()
    )


# ── Users / FCM ──────────────────────────────────────────────────────────────

def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.user_id == user_id).first()


def upsert_fcm_token(db: Session, user_id: str, fcm_token: str) -> None:
    """Store the FCM device token on the User row."""
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        user.fcm_token = fcm_token
        db.commit()


def get_fcm_token(db: Session, user_id: str) -> Optional[str]:
    """Return the FCM token for *user_id* or None."""
    user = db.query(User).filter(User.user_id == user_id).first()
    if user:
        return getattr(user, "fcm_token", None)
    return None
