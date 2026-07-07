import json

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy.orm import Session

from modules.auth.service import get_user_from_token
from core.database import get_db
from core.dependencies import get_current_user
from modules.users.models import User
from modules.discussions.schemas import (
    MessageCreateRequest, MessageUpdateRequest, MessageResponse, MessageListResponse
)
from modules.discussions.service import (
    get_traveller_discussions,
    get_organizer_discussions,
    save_message,
    process_get_messages,
    edit_message,
    remove_message,
    leave_discussion,
)
from modules.discussions.websocket import manager


router = APIRouter()


@router.get("/trips", response_model=None)
async def traveller_discussions(
    trip_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_traveller_discussions(trip_id, current_user, db)


@router.get("/organizer", response_model=None)
async def organizer_discussions(
    trip_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_organizer_discussions(trip_id, current_user, db)


@router.delete("/{discussion_id}")
async def leave_discussion_route(
    discussion_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    leave_discussion(discussion_id, current_user, db)
    return {"success": True, "message": "Left discussion"}


@router.websocket("/{discussion_id}")
async def join_discussion(
    discussion_id: str,
    websocket: WebSocket,
    access_token: str = Query(None),
    db: Session = Depends(get_db),
):
    current_user = get_user_from_token(access_token, db)
    if not current_user:
        await websocket.close(code=4001)
        return

    await manager.connect(websocket, room_id=discussion_id)
    try:
        while True:
            raw = await websocket.receive_text()

            # Parse the incoming JSON payload into a MessageCreateRequest.
            try:
                payload = MessageCreateRequest(**json.loads(raw))
            except Exception:
                await websocket.send_text(
                    json.dumps({"error": "Invalid message payload"})
                )
                continue

            message = save_message(discussion_id, payload, current_user, db)
            # Broadcast the serialised MessageResponse to everyone in the room.
            await manager.broadcast(message.model_dump_json(), room_id=discussion_id)

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.get("/{discussion_id}/messages", response_model=MessageListResponse)
async def get_messages(
    discussion_id: str,
    page: int = Query(1, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return process_get_messages(discussion_id, page, db)


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def edit(
    message_id: str,
    body: MessageUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return edit_message(message_id, body, current_user, db)


@router.delete("/messages/{message_id}")
async def delete(
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    remove_message(message_id, current_user, db)
    return {"success": True, "message": "Message deleted"}