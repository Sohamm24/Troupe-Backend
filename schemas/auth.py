"""
schemas/auth.py
---------------
Authentication request/response models.
"""

from typing import Optional
from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str

class RefreshAuthRequest(BaseModel):
    refresh_token: str     


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """Returned on successful registration or login."""
    user_id: str
    token: str
    refresh_token: Optional[str] = None

    model_config = {"from_attributes": True}

class RefreshAuthResponse(BaseModel):
    """Returned on token refresh rotation"""
    access_token: str
    refresh_token: str
 
