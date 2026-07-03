from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from core.database import get_db
from core.dependencies import get_current_user
from modules.users.models import User
from modules.discussions.schemas import (
    DiscussionResponse, MessageCreateRequest, MessageUpdateRequest, MessageResponse, MessageListResponse
)
from modules.discussions.service import (
    process_create_discussion, process_get_trip_discussions, process_send_message, process_get_messages,
    process_edit_message, process_delete_message
)

router = APIRouter()

@router.post("/trips/{trip_id}/discussions", status_code=status.HTTP_201_CREATED)
def create_discussion(trip_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return process_create_discussion(trip_id, current_user, db)

@router.get("/trips/{trip_id}/discussions", response_model=DiscussionResponse)
def get_trip_discussions(trip_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return process_get_trip_discussions(trip_id, current_user, db)

@router.post("/discussions/{discussion_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def send_message(discussion_id: str, payload: MessageCreateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return process_send_message(discussion_id, payload, current_user, db)

@router.get("/discussions/{discussion_id}/messages", response_model=MessageListResponse)
def get_messages(discussion_id: str, page: int = Query(1, ge=1), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return process_get_messages(discussion_id, page, db)

@router.patch("/messages/{message_id}", response_model=MessageResponse)
def edit_message(message_id: str, payload: MessageUpdateRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return process_edit_message(message_id, payload, current_user, db)

@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(message_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    process_delete_message(message_id, current_user, db)
