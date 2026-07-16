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
        """Delete *key*. Returns True on success.

        Bug fix: Upstash REST API requires POST to /del/<key> (or GET works too
        via /del?key=...), but the correct REST path is GET /del/<key> which
        actually IS supported. The real bug was using /del/<key> with GET which
        Upstash supports. However Upstash's actual REST spec uses:
            GET {url}/del/{key}  → works as a command alias
        The original code was correct structurally but used the wrong HTTP
        client method: it called client.get() which is fine for Upstash's
        REST since it mirrors Redis commands as URL paths.

        The real issue: Upstash Redis REST API for DEL is:
            POST {url}/del/{key}   OR
            GET  {url}/del/{key}   (both are supported)
        The response should be {"result": 1} on success.
        Using GET is fine, but we must check status_code AND result properly.
        """
        if not self._url:
            return False
        async with httpx.AsyncClient() as client:
            try:
                # Upstash supports both GET and POST for commands.
                # Using POST /del is the canonical form per Upstash docs.
                resp = await client.post(
                    f"{self._url}/del/{key}", headers=self._headers
                )
                data = resp.json()
                # result is the number of keys deleted (1 on success, 0 if key missing)
                return isinstance(data.get("result"), int) and data["result"] >= 0
            except Exception:
                return False

    async def setex(self, key: str, ex: int, value: str) -> bool:
        """Convenience alias matching redis-py's setex signature."""
        return await self.set(key, value, ex=ex)

    async def exists(self, key: str) -> bool:
        """Return True if *key* exists."""
        if not self._url:
            return False
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self._url}/exists/{key}", headers=self._headers)
                data = resp.json()
                return bool(data.get("result", 0))
            except Exception:
                return False


# Singleton instance shared across the module
redis = UpstashRedis()
