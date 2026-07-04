# app/core/notifications.py
import os
import logging
import firebase_admin
from firebase_admin import credentials, messaging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-service-account.json")

if os.path.exists(cred_path):
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            logger.info("🔥 Firebase Admin SDK initialized successfully.")
        else:
            logger.info("🔄 Firebase Admin SDK already initialized. Skipping duplicate setup.")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Firebase Admin SDK: {e}")
else:
    logger.warning(f"⚠️ Firebase credential file not found at {cred_path}. Push notifications will fail.")


async def send_multicast_push(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None
) -> Dict:

    if not tokens:
        return {"success_count": 0, "failure_count": 0, "invalid_tokens": []}

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data or {},
        tokens=tokens,
    )

    try:
        response = messaging.send_each_for_multicast(message)

        invalid_tokens = []
        if response.failure_count > 0:
            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    invalid_tokens.append(tokens[idx])
                    logger.warning(f"FCM Token failure: {resp.exception}")

        logger.info(f"🚀 FCM Sent: {response.success_count} success, {response.failure_count} failures.")

        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "invalid_tokens": invalid_tokens
        }

    except Exception as e:
        logger.error(f"❌ Critical exception during FCM multicast routing: {e}")
        return {"success_count": 0, "failure_count": len(tokens), "invalid_tokens": []}