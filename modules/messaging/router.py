"""
modules/messaging/router.py
-----------------------------
REST + WebSocket endpoints for the messaging module.

Endpoints:
  GET  /chats            — list user's chats
  POST /fcm-token        — register FCM device token
  POST /qstash-webhook   — QStash async event callback (signature verified)
  WS   /ws               — WebSocket connection (auth via ?token= query param)

WebSocket events (client → server):
  joinUserChat    { organizer_user_id, last_received_sequence }
  sendMessage     { text, reply_to_message_id? }
  deleteMessage   { message_id }
  editMessage     { message_id, new_text }
  markRead        { chat_id }
  presenceQuery   { target_user_id }
  heartbeat       {}

WebSocket events (server → client):
  connected             { user_id }
  userChatJoined        { user_chat_id, chat_id, messages, participant }
  newMessage            { message }
  messageDeleted        { message_id, chat_id }
  messageEdited         { message }
  messageStatusUpdate   { chat_id, message_ids, status }
  presenceResult        { user_id, is_online }
  heartbeat_ack         {}
  error                 { error }
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.dependencies import get_current_user
from core.security import decode_token
from modules.messaging.connection_manager import manager
from modules.messaging.schemas import (
    DeleteMessagePayload,
    EditMessagePayload,
    GetUserChatsResponse,
    JoinUserChatPayload,
    MarkReadPayload,
    PresenceQueryPayload,
    RegisterFCMTokenRequest,
    SendMessagePayload,
)
from modules.messaging import service

logger = logging.getLogger("travel_platform")

router = APIRouter()


# ── REST: Chat list ──────────────────────────────────────────────────────────

@router.get("/chats", status_code=status.HTTP_200_OK)
async def get_chats(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the authenticated user's chat list, sorted by last message."""
    user_id = str(current_user.user_id)
    chats = await service.get_user_chats(user_id, db)
    return {"data": chats}


# ── REST: FCM token registration ─────────────────────────────────────────────

@router.post("/fcm-token", status_code=status.HTTP_200_OK)
async def register_fcm_token(
    payload: RegisterFCMTokenRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store the device's FCM token for push notification delivery."""
    await service.register_fcm_token(str(current_user.user_id), payload.fcm_token, db)
    return {"message": "FCM token registered"}


# ── REST: QStash webhook ─────────────────────────────────────────────────────

def _verify_qstash_signature(request_body: bytes, signature: str) -> bool:
    """Verify that the webhook is genuinely from QStash using HMAC-SHA256."""
    import base64
    import hashlib as _hashlib
    import hmac as _hmac

    for key in [settings.QSTASH_CURRENT_SIGNING_KEY, settings.QSTASH_NEXT_SIGNING_KEY]:
        if not key:
            continue
        try:
            parts = signature.split(".")
            if len(parts) == 3:
                header_payload = f"{parts[0]}.{parts[1]}".encode()
                padding = "=" * (4 - len(parts[2]) % 4)
                expected_sig = base64.urlsafe_b64decode(parts[2] + padding)
                computed = _hmac.new(
                    key.encode(), header_payload, _hashlib.sha256
                ).digest()
                if _hmac.compare_digest(computed, expected_sig):
                    return True
        except Exception:
            continue
    return False


@router.post("/qstash-webhook", status_code=status.HTTP_200_OK)
async def qstash_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Receive async message events from QStash and dispatch to recipients."""
    body = await request.body()
    signature = request.headers.get("upstash-signature", "")

    if settings.QSTASH_CURRENT_SIGNING_KEY:
        if not _verify_qstash_signature(body, signature):
            raise HTTPException(status_code=403, detail="Invalid QStash signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    await service.handle_qstash_webhook(payload, db)
    return {"ok": True}


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """WebSocket connection authenticated via ?token=<JWT> query param."""
    # ── 1. Authenticate ────────────────────────────────────────────────────
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    user_id: str = payload.get("sub", "")
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    # ── 2. Accept connection ──────────────────────────────────────────────
    await websocket.accept()
    manager.connect(user_id, websocket)
    await service.set_online(user_id)
    await websocket.send_json({"event": "connected", "data": {"user_id": user_id}})

    # Track the current chat_id — set once joinUserChat is handled
    current_chat_id: Optional[str] = None

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except Exception:
                break  # Connection closed

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"event": "error", "data": {"error": "Invalid JSON"}})
                continue

            event_type = msg.get("event")
            data = msg.get("data", {})

            # ── joinUserChat ─────────────────────────────────────────────
            if event_type == "joinUserChat":
                try:
                    join_payload = JoinUserChatPayload(**data)
                except Exception as e:
                    await websocket.send_json({"event": "error", "data": {"error": str(e)}})
                    continue

                try:
                    # handle_join returns chat_id — no redundant second DB call
                    current_chat_id = await service.handle_join(
                        websocket, user_id, join_payload, db
                    )
                except Exception as exc:
                    logger.error(f"joinUserChat handler error: {exc}")
                    # Error response already sent inside handle_join

            # ── sendMessage ──────────────────────────────────────────────
            elif event_type == "sendMessage":
                if not current_chat_id:
                    await websocket.send_json({
                        "event": "error",
                        "data": {"error": "Must join a chat before sending messages"},
                    })
                    continue

                try:
                    send_payload = SendMessagePayload(**data)
                except Exception as e:
                    await websocket.send_json({"event": "error", "data": {"error": str(e)}})
                    continue

                try:
                    await service.handle_send_message(
                        websocket, user_id, current_chat_id, send_payload, db
                    )
                except Exception as exc:
                    logger.error(f"sendMessage handler error: {exc}")

            # ── deleteMessage ─────────────────────────────────────────────
            elif event_type == "deleteMessage":
                if not current_chat_id:
                    await websocket.send_json({
                        "event": "error",
                        "data": {"error": "Must join a chat first"},
                    })
                    continue

                try:
                    del_payload = DeleteMessagePayload(**data)
                except Exception as e:
                    await websocket.send_json({"event": "error", "data": {"error": str(e)}})
                    continue

                try:
                    await service.handle_delete_message(
                        websocket, user_id, current_chat_id, del_payload, db
                    )
                except Exception as exc:
                    logger.error(f"deleteMessage handler error: {exc}")

            # ── editMessage ───────────────────────────────────────────────
            elif event_type == "editMessage":
                if not current_chat_id:
                    await websocket.send_json({
                        "event": "error",
                        "data": {"error": "Must join a chat first"},
                    })
                    continue

                try:
                    edit_payload = EditMessagePayload(**data)
                except Exception as e:
                    await websocket.send_json({"event": "error", "data": {"error": str(e)}})
                    continue

                try:
                    await service.handle_edit_message(
                        websocket, user_id, current_chat_id, edit_payload, db
                    )
                except Exception as exc:
                    logger.error(f"editMessage handler error: {exc}")

            # ── markRead ──────────────────────────────────────────────────
            elif event_type == "markRead":
                try:
                    mark_payload = MarkReadPayload(**data)
                except Exception as e:
                    await websocket.send_json({"event": "error", "data": {"error": str(e)}})
                    continue

                try:
                    await service.handle_mark_read(websocket, user_id, mark_payload, db)
                except Exception as exc:
                    logger.error(f"markRead handler error: {exc}")

            # ── presenceQuery ─────────────────────────────────────────────
            elif event_type == "presenceQuery":
                try:
                    presence_payload = PresenceQueryPayload(**data)
                except Exception as e:
                    await websocket.send_json({"event": "error", "data": {"error": str(e)}})
                    continue

                try:
                    await service.handle_presence_query(websocket, user_id, presence_payload)
                except Exception as exc:
                    logger.error(f"presenceQuery handler error: {exc}")

            # ── heartbeat ────────────────────────────────────────────────
            elif event_type == "heartbeat":
                try:
                    await service.renew_presence(user_id)
                    await websocket.send_json({"event": "heartbeat_ack", "data": {}})
                except Exception as exc:
                    logger.warning(f"heartbeat error: {exc}")

            else:
                await websocket.send_json({
                    "event": "error",
                    "data": {"error": f"Unknown event: {event_type}"},
                })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: user_id={user_id}")
    except Exception as exc:
        logger.error(f"WebSocket error for user_id={user_id}: {exc}")
    finally:
        manager.disconnect(user_id)
        await service.set_offline(user_id)
