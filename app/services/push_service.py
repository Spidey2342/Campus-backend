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

# NOTE: intentionally NOT calling init_firebase() here at import time.
# Under cPanel/Passenger, this module gets imported once in a "preload"
# process which is then forked into worker processes to handle real
# traffic. Firebase Admin SDK uses gRPC internally, and gRPC connections
# do not survive being forked — a worker inheriting a pre-fork gRPC
# connection just hangs forever on first use instead of erroring. We
# defer init to the first actual call, which always happens inside an
# already-forked worker process, so it's safe everywhere (Render, local,
# cPanel alike).
_init_attempted = False

def send_push_notification(fcm_token: str, title: str, body: str, url: str = "/"):
    global _init_attempted
    if not _init_attempted:
        _init_attempted = True
        init_firebase()

    if not firebase_initialized:
        print("Push skipped — Firebase not initialized (check FIREBASE_CREDENTIALS)")
        return
    if not fcm_token:
        print("Push skipped — recipient has no saved FCM token")
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
        message_id = messaging.send(message)
        print(f"Push sent successfully — FCM message id: {message_id}")
    except Exception as e:
        print(f"Push notification failed: {str(e)}")