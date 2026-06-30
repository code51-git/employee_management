# app/core/notifications.py
import os
import logging
import firebase_admin
from firebase_admin import credentials, messaging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Path to your service account credential JSON file
cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-service-account.json")

if os.path.exists(cred_path):
    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        logger.info("🔥 Firebase Admin SDK initialized successfully.")
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
    """
    Sends a push notification to multiple device tokens at once using Firebase Multicast.
    Handles dead/invalid tokens gracefully.
    """
    if not tokens:
        return {"success_count": 0, "failure_count": 0, "cleaned_tokens_needed": []}

    # Construct the base notification message mapping layout
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=data or {}, # Custom key-value pairs (e.g., {"room_id": "123"})
        tokens=tokens,
    )

    try:
        # Send the batch payloads across FCM core pipes
        response = messaging.send_multicast(message)
        
        # Collect tokens that failed because they are expired or uninstalled
        invalid_tokens = []
        if response.failure_count > 0:
            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    # Clean up these tokens from your database later
                    invalid_tokens.append(tokens[idx])
                    logger.warning(f"FCM Token failure detail: {resp.exception.code} - {resp.exception.message}")

        logger.info(f"🚀 FCM Multicast Sent: {response.success_count} success, {response.failure_count} failures.")
        
        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "invalid_tokens": invalid_tokens
        }

    except Exception as e:
        logger.error(f"❌ Critical exception during FCM multicast routing: {e}")
        return {"success_count": 0, "failure_count": len(tokens), "invalid_tokens": []}