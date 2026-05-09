import firebase_admin
from firebase_admin import credentials, messaging
import os
import json

# Initialize Firebase Admin SDK
# Download service account key from Firebase Console
# Project Settings → Service Accounts → Generate new private key
def init_firebase():
    if not firebase_admin._apps:
        # On Render set FIREBASE_CREDENTIALS as env variable
        # containing the JSON content of the service account key
        cred_json = os.getenv("FIREBASE_CREDENTIALS")
        if cred_json:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)

init_firebase()

def send_push_notification(
    fcm_token: str,
    title: str,
    body: str,
    url: str = "/"
):
    """
    Sends a push notification to a specific device.
    fcm_token — the device token saved when user logged in
    """
    if not fcm_token:
        return

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data={"url": url},  # where to go when tapped
            token=fcm_token,
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    icon="/icons/icon-192.png",
                    badge="/icons/icon-96.png",
                    vibrate=[200, 100, 200],
                )
            )
        )
        messaging.send(message)
    except Exception as e:
        # Don't crash the main request if push fails
        print(f"Push notification failed: {str(e)}")