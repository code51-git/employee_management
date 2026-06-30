# app/services/notification.py
import firebase_admin
from firebase_admin import credentials, messaging
from app.core.config import settings

# Initialize Firebase Admin app safely
try:
    # Looks for your google service account credential file path in environment config
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"⚠️ Firebase initialization skipped or already configured: {e}")

def send_multicast_meeting_notification(tokens: list[str], title: str, details: str):
    """
    Fires push notification payloads directly to list of target device notification tokens.
    """
    if not tokens:
        return

    # Construct the base message pack
    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title=f"📅 New Meeting: {title}",
            body=details
        ),
        data={
            "click_action": "FLUTTER_NOTIFICATION_CLICK",
            "category": "MEETING_INVITE"
        },
        tokens=tokens,
    )

    try:
        response = messaging.send_multicast(message)
        print(f"🔔 FCM Success: Dispatched {response.success_count} notifications. Failures: {response.failure_count}")
    except Exception as e:
        print(f"❌ FCM Operational Failure: {str(e)}")