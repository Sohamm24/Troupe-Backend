"""
schemas/common.py
-----------------
Standard response envelopes matching the SRS specification.
"""

from typing import Any, List, Optional
from pydantic import BaseModel


class SuccessResponse(BaseModel):
    """Standard success wrapper."""
    success: bool = True
    data: Any = None
    message: str = ""


class ErrorResponse(BaseModel):
    """Standard error wrapper."""
    success: bool = False
    message: str = ""
    errors: List[dict] = []


class PaginatedMeta(BaseModel):
    """Pagination metadata."""
    page: int
    per_page: int
    total: int
    total_pages: int
