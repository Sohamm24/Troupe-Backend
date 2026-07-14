from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from core.database import get_db
from core.dependencies import get_current_user
from modules.users.models import User
from modules.uploads.schemas import PresignRequest, ConfirmUploadRequest, ReplaceImageRequest
from modules.uploads.service import process_create_signed_upload, process_confirm_upload, process_replace_image

router = APIRouter()

@router.post("/presign")
async def create_signed_upload(body: PresignRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return process_create_signed_upload(body, current_user, db)

@router.post("/confirm", status_code=status.HTTP_200_OK)
async def confirm_upload(payload: ConfirmUploadRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return process_confirm_upload(payload, current_user, db)

@router.post("/upload/replace", status_code=status.HTTP_200_OK)
@router.post("/replace", status_code=status.HTTP_200_OK)
async def replace_image(payload: ReplaceImageRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return process_replace_image(payload, current_user, db)
