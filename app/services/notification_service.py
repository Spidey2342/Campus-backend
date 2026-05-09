from sqlalchemy.orm import Session
from app.models.reel import Notification
from app.models.user import User
from app.services.push_service import send_push_notification
from app.models.user import User

def create_notification(
    db: Session,
    recipient_id: str,
    sender_id: str,
    type: str,
    message: str,
    reel_id: str = None
):
    if recipient_id == sender_id:
        return

    notification = Notification(
        recipient_id=recipient_id,
        sender_id=sender_id,
        type=type,
        message=message,
        reel_id=reel_id,
    )
    db.add(notification)
    db.commit()

    # Send push notification to recipient's device
    recipient = db.query(User).filter(User.id == recipient_id).first()
    if recipient and recipient.fcm_token:
        # Build the URL to open when notification is tapped
        url = f"/reel/{reel_id}" if reel_id else "/notifications"

        send_push_notification(
            fcm_token=recipient.fcm_token,
            title="CampusVibe",
            body=message,
            url=url
        )

    return notification


def get_notifications(db: Session, user_id: str, skip: int = 0, limit: int = 20):
    """Returns all notifications for a user newest first."""
    notifications = (
        db.query(Notification)
        .filter(Notification.recipient_id == user_id)
        .order_by(Notification.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = []
    for n in notifications:
        sender = db.query(User).filter(User.id == n.sender_id).first()
        result.append({
            "id": n.id,
            "type": n.type,
            "message": n.message,
            "is_read": n.is_read,
            "reel_id": n.reel_id,
            "created_at": n.created_at,
            "sender_username": sender.username if sender else None,
            "sender_avatar": sender.avatar_url if sender else None,
        })

    return result


def get_unread_count(db: Session, user_id: str) -> int:
    """Returns count of unread notifications."""
    return (
        db.query(Notification)
        .filter(
            Notification.recipient_id == user_id,
            Notification.is_read == False
        )
        .count()
    )


def mark_all_read(db: Session, user_id: str):
    """Marks all notifications as read."""
    db.query(Notification).filter(
        Notification.recipient_id == user_id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()