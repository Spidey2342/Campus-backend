import os
import json

firebase_initialized = False

def init_firebase():
    global firebase_initialized
    try:
        cred_json = os.getenv("FIREBASE_CREDENTIALS")
        if not cred_json:
            print("FIREBASE_CREDENTIALS not set — push notifications disabled")
            return

        # Import INSIDE the function so it only fails here, not on module load
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred_dict = json.loads(cred_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)

        firebase_initialized = True
        print("Firebase initialized successfully")

    except Exception as e:
        print(f"Firebase init skipped: {str(e)}")
        firebase_initialized = False

# Only attempt init if env var exists
if os.getenv("FIREBASE_CREDENTIALS"):
    init_firebase()

def send_push_notification(fcm_token: str, title: str, body: str, url: str = "/"):
    if not firebase_initialized or not fcm_token:
        return

    try:
        # Import inside function — safe even if firebase_admin not available
        from firebase_admin import messaging
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={"url": str(url)},
            token=fcm_token,
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    icon="/icons/icon-192.png",
                )
            )
        )
        messaging.send(message)
    except Exception as e:
        print(f"Push notification failed: {str(e)}")