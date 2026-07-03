from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from core.database import get_db
from modules.auth.schemas import RefreshAuthRequest, RefreshAuthResponse, RegisterRequest, AuthResponse, LoginRequest
from modules.auth.service import process_refresh, process_register, process_login, process_logout

router = APIRouter()

@router.post(
    "/refresh",
    response_model=RefreshAuthResponse,
    status_code=status.HTTP_200_OK,
)
def refresh(payload: RefreshAuthRequest, db: Session = Depends(get_db)):
    return process_refresh(payload, db)

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    return process_register(payload, db)

@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    return process_login(payload, db)

@router.post("/logout")
def logout(payload: RefreshAuthRequest, db: Session = Depends(get_db)):
    return process_logout(payload, db)
