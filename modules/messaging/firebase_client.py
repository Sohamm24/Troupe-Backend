"""
modules/messaging/firebase_client.py
--------------------------------------
Firebase Admin SDK initialisation and FCM messaging helper.

Supports two credential loading strategies:
  1. File path (local dev / Docker volume): FIREBASE_CREDENTIALS_PATH env var
  2. Raw JSON string (Render.com secrets): FIREBASE_CREDENTIALS_JSON env var

Only one Firebase App instance is created (singleton pattern).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("travel_platform")

# We import firebase_admin lazily so the module loads even if the package
# is missing in a minimal test environment.
_firebase_app = None
_messaging = None


def _get_app():
    """Return the initialised Firebase App (creates it on first call)."""
    global _firebase_app, _messaging

    if _firebase_app is not None:
        return _firebase_app

    try:
        import firebase_admin
        from firebase_admin import credentials as fb_credentials, messaging as fb_messaging
        from core.config import settings

        cred = None

        # ── Strategy 1: raw JSON string in env (good for Render.com secrets) ──
        if settings.FIREBASE_CREDENTIALS_JSON:
            try:
                cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
                cred = fb_credentials.Certificate(cred_dict)
                logger.info("Firebase: loaded credentials from FIREBASE_CREDENTIALS_JSON env var")
            except Exception as e:
                logger.warning(f"Firebase: failed to parse FIREBASE_CREDENTIALS_JSON: {e}")

        # ── Strategy 2: credentials file path ────────────────────────────────
        if cred is None and settings.FIREBASE_CREDENTIALS_PATH:
            cred_path = settings.FIREBASE_CREDENTIALS_PATH
            # Resolve relative paths against the backend root directory
            if not os.path.isabs(cred_path):
                backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                cred_path = os.path.join(backend_dir, cred_path)

            if os.path.exists(cred_path):
                cred = fb_credentials.Certificate(cred_path)
                logger.info(f"Firebase: loaded credentials from file: {cred_path}")
            else:
                logger.warning(f"Firebase: credentials file not found at {cred_path}")

        if cred is None:
            logger.warning("Firebase: no valid credentials found — FCM push disabled")
            return None

        # Avoid re-initialising if already done (e.g. hot-reload in dev)
        if not firebase_admin._apps:
            _firebase_app = firebase_admin.initialize_app(cred)
        else:
            _firebase_app = firebase_admin.get_app()

        _messaging = fb_messaging
        logger.info("Firebase Admin SDK initialised successfully")
        return _firebase_app

    except ImportError:
        logger.error("firebase-admin package not installed — run: pip install firebase-admin")
        return None
    except Exception as e:
        logger.error(f"Firebase Admin SDK init failed: {e}")
        return None


async def send_push_notification(
    fcm_token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    """Send a push notification via FCM HTTP v1 API using the Admin SDK.

    Returns True on success, False on failure.
    This is an async-friendly wrapper — the firebase-admin SDK is synchronous
    internally, but the call is fast (single HTTP request) so it's fine.
    """
    app = _get_app()
    if app is None:
        logger.warning("FCM push skipped — Firebase Admin SDK not initialised")
        return False

    try:
        from firebase_admin import messaging as fb_messaging

        message = fb_messaging.Message(
            notification=fb_messaging.Notification(
                title=title,
                body=body,
            ),
            data={k: str(v) for k, v in (data or {}).items()},
            android=fb_messaging.AndroidConfig(
                priority="high",
                notification=fb_messaging.AndroidNotification(
                    sound="default",
                    channel_id="messages",
                ),
            ),
            apns=fb_messaging.APNSConfig(
                payload=fb_messaging.APNSPayload(
                    aps=fb_messaging.Aps(sound="default"),
                ),
            ),
            token=fcm_token,
        )

        message_id = fb_messaging.send(message)
        logger.info(f"FCM push sent: message_id={message_id} token={fcm_token[:20]}...")
        return True

    except Exception as e:
        logger.warning(f"FCM push failed: {e}")
        return False
