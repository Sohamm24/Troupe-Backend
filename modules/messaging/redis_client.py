"""
modules/messaging/redis_client.py
----------------------------------
Async Upstash Redis REST client using httpx.
Upstash Redis exposes a simple REST API, so no native redis library is needed.
"""

from typing import Optional
import httpx
from core.config import settings


class UpstashRedis:
    """Minimal async wrapper around the Upstash Redis REST API."""

    def __init__(self):
        self._url = settings.UPSTASH_REDIS_REST_URL.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.UPSTASH_REDIS_REST_TOKEN}",
            "Content-Type": "application/json",
        }

    async def get(self, key: str) -> Optional[str]:
        """Return the value for *key*, or None if not found / error."""
        if not self._url:
            return None
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self._url}/get/{key}", headers=self._headers)
                data = resp.json()
                return data.get("result")  # None when key missing
            except Exception:
                return None

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set *key* to *value* with optional TTL in seconds. Returns True on success."""
        if not self._url:
            return False
        # Upstash REST: POST /set/<key>/<value>?EX=<seconds>
        url = f"{self._url}/set/{key}/{value}"
        params = {}
        if ex is not None:
            params["EX"] = ex
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, headers=self._headers, params=params)
                data = resp.json()
                return data.get("result") == "OK"
            except Exception:
                return False

    async def delete(self, key: str) -> bool:
        """Delete *key*. Returns True on success."""
        if not self._url:
            return False
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self._url}/del/{key}", headers=self._headers)
                return resp.status_code == 200
            except Exception:
                return False

    async def setex(self, key: str, ex: int, value: str) -> bool:
        """Convenience alias matching redis-py's setex signature."""
        return await self.set(key, value, ex=ex)


# Singleton instance shared across the module
redis = UpstashRedis()
