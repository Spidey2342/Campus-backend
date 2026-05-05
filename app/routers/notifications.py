from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.services.notification_service import (
    get_notifications,
    get_unread_count,
    mark_all_read
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/")
def fetch_notifications(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return get_notifications(db, current_user.id, skip, limit)


@router.get("/unread-count")
def fetch_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    count = get_unread_count(db, current_user.id)
    return {"unread_count": count}


@router.post("/mark-read")
def mark_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    mark_all_read(db, current_user.id)
    return {"message": "All notifications marked as read"}