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
from typing import List, Optional

import httpx
from fastapi import WebSocket
from sqlalchemy.orm import Session

from core.config import settings
from modules.messaging.connection_manager import manager
from modules.messaging.redis_client import redis
from modules.messaging.firebase_client import send_push_notification
from modules.messaging import repository as repo
from modules.messaging.models import MessageStatus
from modules.messaging.schemas import (
    DeleteMessagePayload,
    EditMessagePayload,
    JoinUserChatPayload,
    MarkReadPayload,
    MessageOut,
    MessageStatusSchema,
    PresenceQueryPayload,
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
            text=r.text if not r.is_deleted else "",
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
    profile_pic = user.profile_pic
    if organizer_profile:
        organizer_id = str(organizer_profile.organizer_id)
        is_verified = organizer_profile.verification_status
    return UserOut(
        user_id=str(user.user_id),
        name=user.name,
        profile_pic=profile_pic,
        organizer_id=organizer_id,
        is_verified=is_verified,
    )


def _uc_to_out(uc, current_user_id: str) -> UserChatOut:
    """Serialize a UserChat for the given current_user_id.

    Bug fix (B5): previously used uc.user which is the *current* user's own
    User row. We must find the OTHER participant's UserChat row and use their user.
    """
    other_user = None
    if uc.chat and uc.chat.userchats:
        for other_uc in uc.chat.userchats:
            if str(other_uc.user_id) != str(current_user_id):
                other_user = other_uc.user
                break

    # Fallback: if relationships aren't loaded, use uc.user (self) — shouldn't happen
    if other_user is None:
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
    result = [_uc_to_out(uc, user_id).model_dump(mode="json") for uc in rows]

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
) -> str:
    """Handle 'joinUserChat' event.

    1. Set Redis presence
    2. Get or create chat with organizer
    3. Fetch history + race-condition catch-up
    4. Mark as read (UserChat unread counter)
    5. Mark incoming messages as READ in Message table
    6. Emit 'userChatJoined' back to the connecting client
    7. Notify the other participant about read receipts

    Returns the chat_id string so the router can store it without a second DB call.
    """
    organizer_user_id = payload.organizer_user_id
    last_seq = payload.last_received_sequence

    await set_online(user_id)

    # Get/create chat
    try:
        chat, uc_me, uc_other = repo.get_or_create_chat(db, user_id, organizer_user_id)
        db.commit()
    except Exception as exc:
        logger.error(f"handle_join: get_or_create_chat failed: {exc}")
        await ws.send_json({"event": "error", "data": {"error": "Failed to initialise chat"}})
        raise

    # Refresh to load relationships after commit
    try:
        db.refresh(uc_me)
        if uc_other:
            db.refresh(uc_other)
    except Exception:
        pass  # non-fatal

    chat_id = str(chat.chat_id)

    # Fetch messages
    try:
        if last_seq > 0:
            catchup = repo.get_messages_after(db, chat_id, last_seq)
            history = repo.get_last_n_messages(db, chat_id)
            seen: set = set()
            merged: list = []
            for m in history + catchup:
                if m.message_id not in seen:
                    seen.add(m.message_id)
                    merged.append(m)
            merged.sort(key=lambda m: m.message_id)
            messages = merged
        else:
            messages = repo.get_last_n_messages(db, chat_id)
    except Exception as exc:
        logger.error(f"handle_join: message fetch failed: {exc}")
        messages = []

    # Mark UserChat unread counter as read
    try:
        repo.mark_as_read(db, str(uc_me.user_chat_id), user_id)
        db.commit()
    except Exception as exc:
        logger.warning(f"handle_join: mark_as_read failed: {exc}")

    # Mark individual messages as READ and notify the sender
    try:
        read_ids = repo.mark_messages_read(db, chat_id, user_id)
        db.commit()
        if read_ids and uc_other:
            # Notify the other participant (sender) that their messages were read
            await manager.send_to_user(
                str(uc_other.user_id),
                {
                    "event": "messageStatusUpdate",
                    "data": {
                        "chat_id": chat_id,
                        "message_ids": read_ids,
                        "status": "READ",
                    },
                },
            )
            # Invalidate sender's chat list cache so read state reflects
            await invalidate_chat_list_cache(str(uc_other.user_id))
    except Exception as exc:
        logger.warning(f"handle_join: mark_messages_read failed: {exc}")

    # Build other participant info
    try:
        other_user = repo.get_user_by_id(db, organizer_user_id)
        organizer_profile = getattr(other_user, "organizer_profile", None) if other_user else None
        participant_out = _user_to_out(other_user, organizer_profile) if other_user else None
    except Exception as exc:
        logger.warning(f"handle_join: participant lookup failed: {exc}")
        participant_out = None

    # Build response
    try:
        messages_out = [_msg_to_out(m).model_dump(mode="json") for m in messages]
    except Exception as exc:
        logger.error(f"handle_join: message serialization failed: {exc}")
        messages_out = []

    user_chat_id = str(uc_me.user_chat_id)

    await ws.send_json({
        "event": "userChatJoined",
        "data": {
            "user_chat_id": user_chat_id,
            "chat_id": chat_id,
            "messages": messages_out,
            "participant": participant_out.model_dump(mode="json") if participant_out else None,
        },
    })

    logger.info(f"userChatJoined: user={user_id} chat={chat_id} msgs={len(messages_out)}")
    return chat_id  # ← returned so router does NOT need a second DB call


async def handle_send_message(
    ws: WebSocket,
    user_id: str,
    chat_id: str,
    payload: SendMessagePayload,
    db: Session,
) -> None:
    """Handle 'sendMessage' event.

    1. Insert message in DB (status=SENT)
    2. Update last_message_id + unread_count for participants
    3. Invalidate chat-list cache for both participants
    4. Emit newMessage back to sender immediately
    5. Publish to QStash for async delivery to recipient
    """
    try:
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
    except Exception as exc:
        logger.error(f"handle_send_message: DB error: {exc}")
        await ws.send_json({"event": "error", "data": {"error": "Failed to save message"}})
        return

    try:
        msg_out = _msg_to_out(msg)
    except Exception as exc:
        logger.error(f"handle_send_message: serialization error: {exc}")
        await ws.send_json({"event": "error", "data": {"error": "Failed to serialize message"}})
        return

    # Echo back to sender with SENT status
    await ws.send_json({
        "event": "newMessage",
        "data": {"message": msg_out.model_dump(mode="json")},
    })

    # Get the other participant to invalidate their cache + dispatch push
    try:
        other_uc = repo.get_other_participant_user_chat(db, chat_id, user_id)
        recipient_id = str(other_uc.user_id) if other_uc else None
    except Exception as exc:
        logger.warning(f"handle_send_message: recipient lookup failed: {exc}")
        recipient_id = None

    # Invalidate both users' chat list caches
    await invalidate_chat_list_cache(user_id)
    if recipient_id:
        await invalidate_chat_list_cache(recipient_id)

    # Publish async delivery event to QStash
    if recipient_id:
        try:
            await _publish_to_qstash(
                QStashMessagePayload(
                    message_id=msg.message_id,
                    chat_id=chat_id,
                    sender_id=user_id,
                    recipient_user_id=recipient_id,
                ),
                msg_out,
            )
        except Exception as exc:
            logger.warning(f"handle_send_message: QStash publish failed: {exc}")

    logger.info(f"sendMessage: sender={user_id} chat={chat_id} msg_id={msg.message_id}")


async def handle_delete_message(
    ws: WebSocket,
    user_id: str,
    chat_id: str,
    payload: DeleteMessagePayload,
    db: Session,
) -> None:
    """Handle 'deleteMessage' event — soft-delete a message.

    Only the original sender can delete. Both participants are notified via
    the 'messageDeleted' event.
    """
    try:
        msg = repo.soft_delete_message(db, payload.message_id, user_id)
        if msg is None:
            await ws.send_json({
                "event": "error",
                "data": {"error": "Message not found or you are not the sender"},
            })
            return
        db.commit()
    except Exception as exc:
        logger.error(f"handle_delete_message: DB error: {exc}")
        await ws.send_json({"event": "error", "data": {"error": "Failed to delete message"}})
        return

    event_data = {
        "event": "messageDeleted",
        "data": {
            "message_id": payload.message_id,
            "chat_id": chat_id,
        },
    }

    # Notify sender (echo)
    await ws.send_json(event_data)

    # Notify other participant if online
    try:
        other_uc = repo.get_other_participant_user_chat(db, chat_id, user_id)
        if other_uc:
            await manager.send_to_user(str(other_uc.user_id), event_data)
    except Exception as exc:
        logger.warning(f"handle_delete_message: notify recipient failed: {exc}")

    # Invalidate both caches
    await invalidate_chat_list_cache(user_id)
    try:
        if other_uc:
            await invalidate_chat_list_cache(str(other_uc.user_id))
    except Exception:
        pass

    logger.info(f"deleteMessage: user={user_id} msg={payload.message_id}")


async def handle_edit_message(
    ws: WebSocket,
    user_id: str,
    chat_id: str,
    payload: EditMessagePayload,
    db: Session,
) -> None:
    """Handle 'editMessage' event — update message text.

    Only the original sender can edit. Both participants are notified via
    the 'messageEdited' event.
    """
    if not payload.new_text.strip():
        await ws.send_json({"event": "error", "data": {"error": "Message text cannot be empty"}})
        return

    try:
        msg = repo.edit_message(db, payload.message_id, user_id, payload.new_text)
        if msg is None:
            await ws.send_json({
                "event": "error",
                "data": {"error": "Message not found, already deleted, or you are not the sender"},
            })
            return
        db.commit()
        db.refresh(msg)
    except Exception as exc:
        logger.error(f"handle_edit_message: DB error: {exc}")
        await ws.send_json({"event": "error", "data": {"error": "Failed to edit message"}})
        return

    try:
        msg_out = _msg_to_out(msg)
    except Exception as exc:
        logger.error(f"handle_edit_message: serialization error: {exc}")
        return

    event_data = {
        "event": "messageEdited",
        "data": {"message": msg_out.model_dump(mode="json")},
    }

    # Notify sender (echo)
    await ws.send_json(event_data)

    # Notify other participant if online
    try:
        other_uc = repo.get_other_participant_user_chat(db, chat_id, user_id)
        if other_uc:
            await manager.send_to_user(str(other_uc.user_id), event_data)
    except Exception as exc:
        logger.warning(f"handle_edit_message: notify recipient failed: {exc}")

    logger.info(f"editMessage: user={user_id} msg={payload.message_id}")


async def handle_mark_read(
    ws: WebSocket,
    user_id: str,
    payload: MarkReadPayload,
    db: Session,
) -> None:
    """Handle 'markRead' event — mark incoming messages as READ.

    Updates message statuses and notifies the sender with a 'messageStatusUpdate'.
    Also resets the UserChat unread counter.
    """
    chat_id = payload.chat_id
    try:
        read_ids = repo.mark_messages_read(db, chat_id, user_id)
        repo.reset_unread_for_user(db, chat_id, user_id)
        db.commit()
    except Exception as exc:
        logger.error(f"handle_mark_read: DB error: {exc}")
        return

    if not read_ids:
        return  # Nothing to update

    # Notify the other participant (message sender) about the read receipts
    try:
        other_uc = repo.get_other_participant_user_chat(db, chat_id, user_id)
        if other_uc:
            await manager.send_to_user(
                str(other_uc.user_id),
                {
                    "event": "messageStatusUpdate",
                    "data": {
                        "chat_id": chat_id,
                        "message_ids": read_ids,
                        "status": "READ",
                    },
                },
            )
            await invalidate_chat_list_cache(str(other_uc.user_id))
    except Exception as exc:
        logger.warning(f"handle_mark_read: notify sender failed: {exc}")

    await invalidate_chat_list_cache(user_id)
    logger.info(f"markRead: user={user_id} chat={chat_id} count={len(read_ids)}")


async def handle_presence_query(
    ws: WebSocket,
    user_id: str,
    payload: PresenceQueryPayload,
) -> None:
    """Handle 'presenceQuery' event — check if another user is online.

    Checks in-memory registry first (same process), then Redis (cross-process).
    """
    target_id = payload.target_user_id
    try:
        in_memory = manager.is_online(target_id)
        in_redis = await is_online_in_redis(target_id) if not in_memory else True
        is_online = in_memory or in_redis
    except Exception as exc:
        logger.warning(f"handle_presence_query: error: {exc}")
        is_online = False

    await ws.send_json({
        "event": "presenceResult",
        "data": {
            "user_id": target_id,
            "is_online": is_online,
        },
    })


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
    After WS delivery, updates message status to DELIVERED and notifies the sender.
    """
    recipient_id = body.get("recipient_user_id")
    msg_data = body.get("message")
    message_id = body.get("message_id")
    sender_id = body.get("sender_id")
    chat_id = body.get("chat_id")

    if not recipient_id or not msg_data:
        logger.warning("QStash webhook: missing recipient_user_id or message")
        return

    delivered_via_ws = False

    # Try in-memory WS delivery first (same process)
    if manager.is_online(recipient_id):
        delivered = await manager.send_to_user(
            recipient_id,
            {"event": "newMessage", "data": {"message": msg_data}},
        )
        if delivered:
            logger.info(f"QStash→WS delivery: recipient={recipient_id}")
            delivered_via_ws = True

    if not delivered_via_ws:
        # Check Redis presence (cross-process)
        online = await is_online_in_redis(recipient_id)
        if online:
            logger.info(f"Recipient {recipient_id} online in Redis but not local — sending FCM anyway")

        # Send FCM push notification
        fcm_token = repo.get_fcm_token(db, recipient_id)
        if fcm_token:
            sender_user = repo.get_user_by_id(db, sender_id) if sender_id else None
            sender_name = sender_user.name if sender_user else "New message"
            try:
                await _send_fcm_push(
                    fcm_token=fcm_token,
                    sender_name=sender_name,
                    text=msg_data.get("text", "New message"),
                    chat_id=msg_data.get("chat_id", ""),
                )
            except Exception as exc:
                logger.warning(f"FCM send failed: {exc}")
        else:
            logger.info(f"No FCM token for recipient={recipient_id} — push skipped")

    # Update message status to DELIVERED and notify the sender
    if message_id and sender_id and chat_id:
        try:
            updated_msg = repo.update_message_status(db, message_id, MessageStatus.DELIVERED)
            db.commit()
            if updated_msg:
                # Notify the original sender via WS that message was delivered
                await manager.send_to_user(
                    sender_id,
                    {
                        "event": "messageStatusUpdate",
                        "data": {
                            "chat_id": chat_id,
                            "message_ids": [message_id],
                            "status": "DELIVERED",
                        },
                    },
                )
        except Exception as exc:
            logger.warning(f"QStash webhook: status update to DELIVERED failed: {exc}")


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
