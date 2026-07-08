"""
modules/messaging/service.py
-----------------------------
Business logic for the messaging module.

Orchestrates DB (repository), Redis (presence + cache), QStash (async dispatch),
Firebase (push notifications), and the in-memory ConnectionManager.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from fastapi import WebSocket
from sqlalchemy.orm import Session

from core.config import settings
from modules.messaging.connection_manager import manager
from modules.messaging.redis_client import redis
from modules.messaging.firebase_client import send_push_notification
from modules.messaging import repository as repo
from modules.messaging.schemas import (
    JoinUserChatPayload,
    MessageOut,
    MessageStatusSchema,
    QStashMessagePayload,
    ReplyMessageOut,
    SendMessagePayload,
    UserChatOut,
    UserOut,
)

logger = logging.getLogger("travel_platform")

# Redis key helpers
_PRESENCE_KEY = "user:{user_id}:online"
_CHAT_LIST_KEY = "chat_list:{user_id}"
PRESENCE_TTL = 5 * 60  # 5 minutes; renewed on every heartbeat


# ── Serialisation helpers ────────────────────────────────────────────────────

def _msg_to_out(msg) -> MessageOut:
    reply = None
    if msg.reply_to_message:
        r = msg.reply_to_message
        reply = ReplyMessageOut(
            message_id=r.message_id,
            sender_id=str(r.sender_id),
            text=r.text,
            is_deleted=r.is_deleted,
        )
    return MessageOut(
        message_id=msg.message_id,
        chat_id=str(msg.chat_id),
        sender_id=str(msg.sender_id),
        text=msg.text,
        is_edited=msg.is_edited,
        is_deleted=msg.is_deleted,
        reply_to_message=reply,
        status=MessageStatusSchema(msg.status.value),
        created_at=msg.created_at.isoformat(),
    )


def _user_to_out(user, organizer_profile=None) -> UserOut:
    organizer_id = None
    is_verified = None
    profile_pic = None
    if organizer_profile:
        organizer_id = str(organizer_profile.organizer_id)
        is_verified = organizer_profile.verification_status
        profile_pic = organizer_profile.profile_pic
    return UserOut(
        user_id=str(user.user_id),
        name=user.name,
        profile_pic=profile_pic,
        organizer_id=organizer_id,
        is_verified=is_verified,
    )


def _uc_to_out(uc) -> UserChatOut:
    other_user = uc.user
    organizer_profile = getattr(other_user, "organizer_profile", None)
    user_out = _user_to_out(other_user, organizer_profile)
    last_msg_out = _msg_to_out(uc.last_message) if uc.last_message else None
    return UserChatOut(
        user_chat_id=str(uc.user_chat_id),
        chat_id=str(uc.chat_id),
        last_read_timestamp=uc.last_read_timestamp.isoformat(),
        last_message=last_msg_out,
        unread_count=uc.unread_count,
        user=user_out,
    )


# ── REST services ────────────────────────────────────────────────────────────

async def get_user_chats(user_id: str, db: Session):
    """Return chat list, using Redis cache when available."""
    cache_key = _CHAT_LIST_KEY.format(user_id=user_id)
    cached = await redis.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    rows = repo.get_user_chats(db, user_id)
    result = [_uc_to_out(uc).model_dump(mode="json") for uc in rows]

    # Cache for 60 seconds (short TTL so list stays fresh)
    await redis.set(cache_key, json.dumps(result), ex=60)
    return result


async def register_fcm_token(user_id: str, fcm_token: str, db: Session) -> None:
    repo.upsert_fcm_token(db, user_id, fcm_token)


# ── Presence helpers ──────────────────────────────────────────────────────────

async def set_online(user_id: str) -> None:
    await redis.set(_PRESENCE_KEY.format(user_id=user_id), "1", ex=PRESENCE_TTL)


async def set_offline(user_id: str) -> None:
    await redis.delete(_PRESENCE_KEY.format(user_id=user_id))


async def is_online_in_redis(user_id: str) -> bool:
    val = await redis.get(_PRESENCE_KEY.format(user_id=user_id))
    return val is not None


async def renew_presence(user_id: str) -> None:
    """Called on heartbeat to keep TTL alive."""
    await redis.set(_PRESENCE_KEY.format(user_id=user_id), "1", ex=PRESENCE_TTL)


# ── Cache invalidation ────────────────────────────────────────────────────────

async def invalidate_chat_list_cache(user_id: str) -> None:
    await redis.delete(_CHAT_LIST_KEY.format(user_id=user_id))


# ── WebSocket event handlers ──────────────────────────────────────────────────

async def handle_join(
    ws: WebSocket,
    user_id: str,
    payload: JoinUserChatPayload,
    db: Session,
) -> None:
    """Handle 'joinUserChat' event.

    1. Set Redis presence
    2. Get or create chat with organizer
    3. Fetch history + race-condition catch-up
    4. Mark as read
    5. Emit 'userChatJoined' back
    """
    organizer_user_id = payload.organizer_user_id
    last_seq = payload.last_received_sequence

    await set_online(user_id)

    # Get/create chat
    chat, uc_me, uc_other = repo.get_or_create_chat(db, user_id, organizer_user_id)
    db.commit()

    # Refresh to load relationships after commit
    db.refresh(uc_me)
    db.refresh(uc_other)

    # Fetch messages
    if last_seq > 0:
        # Race-condition catch-up: any messages the client might have missed
        catchup = repo.get_messages_after(db, str(chat.chat_id), last_seq)
        # Also get the standard window so the client has context
        history = repo.get_last_n_messages(db, str(chat.chat_id))
        # Merge, dedup by message_id, keep order
        seen = set()
        merged = []
        for m in history + catchup:
            if m.message_id not in seen:
                seen.add(m.message_id)
                merged.append(m)
        merged.sort(key=lambda m: m.message_id)
        messages = merged
    else:
        messages = repo.get_last_n_messages(db, str(chat.chat_id))

    # Mark as read
    repo.mark_as_read(db, str(uc_me.user_chat_id), user_id)
    db.commit()

    # Build other participant info
    other_user = repo.get_user_by_id(db, organizer_user_id)
    organizer_profile = getattr(other_user, "organizer_profile", None) if other_user else None
    participant_out = _user_to_out(other_user, organizer_profile) if other_user else None

    # Build response
    messages_out = [_msg_to_out(m).model_dump(mode="json") for m in messages]
    user_chat_id = str(uc_me.user_chat_id)

    await ws.send_json({
        "event": "userChatJoined",
        "data": {
            "user_chat_id": user_chat_id,
            "chat_id": str(chat.chat_id),
            "messages": messages_out,
            "participant": participant_out.model_dump(mode="json") if participant_out else None,
        },
    })

    logger.info(f"userChatJoined: user={user_id} chat={chat.chat_id} msgs={len(messages_out)}")


async def handle_send_message(
    ws: WebSocket,
    user_id: str,
    chat_id: str,
    payload: SendMessagePayload,
    db: Session,
) -> None:
    """Handle 'sendMessage' event.

    1. Insert message in DB
    2. Update last_message_id + unread_count for participants
    3. Invalidate chat-list cache for both participants
    4. Emit newMessage back to sender immediately
    5. Publish to QStash for async delivery to recipient
    """
    msg = repo.create_message(
        db,
        chat_id=chat_id,
        sender_id=user_id,
        text=payload.text,
        reply_to_id=payload.reply_to_message_id,
    )
    repo.update_last_message(db, chat_id, msg.message_id)
    repo.increment_unread_for_recipient(db, chat_id, user_id)
    db.commit()
    db.refresh(msg)

    msg_out = _msg_to_out(msg)

    # Echo back to sender with SENT status
    await ws.send_json({
        "event": "newMessage",
        "data": {"message": msg_out.model_dump(mode="json")},
    })

    # Get the other participant to invalidate their cache + dispatch push
    other_uc = repo.get_other_participant_user_chat(db, chat_id, user_id)
    recipient_id = str(other_uc.user_id) if other_uc else None

    # Invalidate both users' chat list caches
    await invalidate_chat_list_cache(user_id)
    if recipient_id:
        await invalidate_chat_list_cache(recipient_id)

    # Publish async delivery event to QStash
    if recipient_id:
        await _publish_to_qstash(
            QStashMessagePayload(
                message_id=msg.message_id,
                chat_id=chat_id,
                sender_id=user_id,
                recipient_user_id=recipient_id,
            ),
            msg_out,
        )

    logger.info(f"sendMessage: sender={user_id} chat={chat_id} msg_id={msg.message_id}")


# ── QStash dispatch ──────────────────────────────────────────────────────────

async def _publish_to_qstash(
    event: QStashMessagePayload, msg_out: MessageOut
) -> None:
    """Publish a message event to QStash.

    QStash will call our /qstash-webhook endpoint, which then decides
    whether to send via WebSocket (online) or FCM (offline).
    The full MessageOut is embedded so the webhook handler doesn't need a DB lookup.
    """
    if not settings.QSTASH_TOKEN or not settings.QSTASH_URL:
        logger.warning("QStash not configured — skipping async dispatch")
        return

    # The backend's public URL for the QStash callback
    # On render.com this should be the live server URL
    base_url = settings.QSTASH_URL.rstrip("/")
    target_url = f"{base_url}/api/v1/messaging/qstash-webhook"

    body = {
        **event.model_dump(mode="json"),
        "message": msg_out.model_dump(mode="json"),
    }

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"https://qstash.upstash.io/v2/publish/{target_url}",
                headers={
                    "Authorization": f"Bearer {settings.QSTASH_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=5.0,
            )
            if resp.status_code not in (200, 201, 202):
                logger.warning(f"QStash publish failed: {resp.status_code} {resp.text}")
        except Exception as exc:
            logger.warning(f"QStash publish error: {exc}")


# ── QStash webhook handler ────────────────────────────────────────────────────

async def handle_qstash_webhook(body: dict, db: Session) -> None:
    """Called by the /qstash-webhook endpoint after signature verification.

    Decides: deliver via WebSocket if recipient is online, else FCM push.
    """
    recipient_id = body.get("recipient_user_id")
    msg_data = body.get("message")

    if not recipient_id or not msg_data:
        logger.warning("QStash webhook: missing recipient_user_id or message")
        return

    # Try in-memory WS delivery first (same process)
    if manager.is_online(recipient_id):
        delivered = await manager.send_to_user(
            recipient_id,
            {"event": "newMessage", "data": {"message": msg_data}},
        )
        if delivered:
            logger.info(f"QStash→WS delivery: recipient={recipient_id}")
            return

    # Check Redis presence (cross-process)
    online = await is_online_in_redis(recipient_id)
    if online:
        # They're online in another process/pod — ideally use a pub/sub here.
        # For now, still attempt FCM as a fallback; the mobile app can debounce duplicates.
        logger.info(f"Recipient {recipient_id} online in Redis but not local — sending FCM anyway")

    # Send FCM push notification
    fcm_token = repo.get_fcm_token(db, recipient_id)
    if fcm_token:
        # Resolve the sender's display name for the notification title
        sender_id = body.get("sender_id", "")
        sender_user = repo.get_user_by_id(db, sender_id) if sender_id else None
        sender_name = sender_user.name if sender_user else "New message"

        await _send_fcm_push(
            fcm_token=fcm_token,
            sender_name=sender_name,
            text=msg_data.get("text", "New message"),
            chat_id=msg_data.get("chat_id", ""),
        )
    else:
        logger.info(f"No FCM token for recipient={recipient_id} — push skipped")


# ── Firebase Cloud Messaging ─────────────────────────────────────────────────

async def _send_fcm_push(
    fcm_token: str, sender_name: str, text: str, chat_id: str
) -> None:
    """Send a push notification via Firebase Admin SDK (HTTP v1 API)."""
    await send_push_notification(
        fcm_token=fcm_token,
        title=sender_name,
        body=text,
        data={"chat_id": chat_id, "type": "new_message"},
    )
