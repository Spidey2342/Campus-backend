import firebase_admin
from firebase_admin import credentials, messaging
import os
import json

firebase_initialized = False

def init_firebase():
    global firebase_initialized
    try:
        if firebase_admin._apps:
            firebase_initialized = True
            return

        cred_json = os.getenv("FIREBASE_CREDENTIALS")
        if not cred_json:
            print("FIREBASE_CREDENTIALS not set — push notifications disabled")
            return

        cred_dict = json.loads(cred_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        firebase_initialized = True
        print("Firebase initialized successfully")

    except Exception as e:
        print(f"Firebase init failed: {str(e)}")
        firebase_initialized = False

init_firebase()

def send_push_notification(fcm_token: str, title: str, body: str, url: str = "/") -> bool:
    if not firebase_initialized or not fcm_token:
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={"url": str(url)},
            token=fcm_token,
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                    icon="/icons/icon-192.png",
                    badge="/icons/icon-192.png",
                )
            )
        )
        messaging.send(message)
        return True
    except Exception as e:
        print(f"Push notification failed: {str(e)}")
        return False