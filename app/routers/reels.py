from fastapi import APIRouter, Depends, UploadFile, File, Form, Query, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional, List
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.reel import Reel, Like, Comment
from app.schemas.reel import ReelResponse, CommentCreate, CommentResponse
from app.services.reel_service import (
    upload_video_to_cloudinary,
    create_reel,
    get_feed,
    toggle_like,
    add_comment,
    increment_views
)
import json

router = APIRouter(prefix="/reels", tags=["Reels"])
limiter = Limiter(key_func=get_remote_address)


# 10 uploads per hour — prevents spam
@router.post("/upload", status_code=201)
@limiter.limit("10/hour")
async def upload_reel(
    request: Request,
    video: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    school_tag: Optional[str] = Form(None),
    trim_start: Optional[float] = Form(0),
    trim_end: Optional[float] = Form(None),
    text_overlays: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Validate file type
        if not video.content_type.startswith("video/"):
            raise HTTPException(
                status_code=400,
                detail="File must be a video"
            )

        # Validate file size — 100MB max
        file_bytes = await video.read()
        if len(file_bytes) > 100 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="Video must be under 100MB"
            )

        overlays = []
        if text_overlays:
            try:
                overlays = json.loads(text_overlays)
            except:
                overlays = []

        upload_result = upload_video_to_cloudinary(
            file_bytes,
            video.filename,
            trim_start=trim_start,
            trim_end=trim_end,
            text_overlays=overlays
        )

        reel = create_reel(
            db=db,
            owner_id=current_user.id,
            video_url=upload_result["video_url"],
            thumbnail_url=upload_result["thumbnail_url"],
            caption=caption,
            school_tag=school_tag or current_user.school_name,
        )

        return {
            "message": "Reel uploaded successfully",
            "reel_id": reel.id,
            "video_url": reel.video_url
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# 60 feed requests per minute — generous for scrolling
@router.get("/feed")
@limiter.limit("60/minute")
async def get_reel_feed(
    request: Request,
    type: str = Query(default="foryou"),
    skip: int = Query(default=0, ge=0),       # ge=0 means >= 0
    limit: int = Query(default=10, le=20),    # le=20 means <= 20
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        return get_feed(db, current_user.id, type, skip, limit)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# 30 likes per minute — prevents like bombing
@router.post("/{reel_id}/like")
@limiter.limit("30/minute")
async def like_reel(
    request: Request,
    reel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        result = toggle_like(db, reel_id, current_user.id)

        # Send notification to reel owner when liked
        if result["liked"]:
            from app.models.reel import Reel
            from app.services.notification_service import create_notification
            reel = db.query(Reel).filter(Reel.id == reel_id).first()
            if reel:
                create_notification(
                    db=db,
                    recipient_id=reel.owner_id,
                    sender_id=current_user.id,
                    type="like",
                    message=f"@{current_user.username} liked your reel",
                    reel_id=reel_id
                )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# 20 comments per minute
@router.post("/{reel_id}/comment", status_code=201)
@limiter.limit("20/minute")
async def comment_on_reel(
    request: Request,
    reel_id: str,
    comment_data: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Validate comment length
        if len(comment_data.text.strip()) == 0:
            raise HTTPException(
                status_code=400,
                detail="Comment cannot be empty"
            )
        if len(comment_data.text) > 300:
            raise HTTPException(
                status_code=400,
                detail="Comment cannot exceed 300 characters"
            )
        return add_comment(db, reel_id, current_user.id, comment_data.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{reel_id}/comment", status_code=201)
@limiter.limit("20/minute")
async def comment_on_reel(
    request: Request,
    reel_id: str,
    comment_data: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        if len(comment_data.text.strip()) == 0:
            raise HTTPException(status_code=400, detail="Comment cannot be empty")
        if len(comment_data.text) > 300:
            raise HTTPException(status_code=400, detail="Comment cannot exceed 300 characters")

        result = add_comment(db, reel_id, current_user.id, comment_data.text)

        # Notify reel owner
        from app.models.reel import Reel
        from app.services.notification_service import create_notification
        reel = db.query(Reel).filter(Reel.id == reel_id).first()
        if reel:
            create_notification(
                db=db,
                recipient_id=reel.owner_id,
                sender_id=current_user.id,
                type="comment",
                message=f"@{current_user.username} commented: {comment_data.text[:50]}",
                reel_id=reel_id
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{reel_id}/view")
async def view_reel(
    reel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        return increment_views(db, reel_id, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{reel_id}")
async def delete_reel(
    reel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        reel = db.query(Reel).filter(Reel.id == reel_id).first()
        if not reel:
            raise HTTPException(status_code=404, detail="Reel not found")
        if reel.owner_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You can only delete your own reels"
            )
        reel.is_active = False
        db.commit()
        return {"message": "Reel deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/{reel_id}")
async def get_single_reel(
    reel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        reel = db.query(Reel).filter(
            Reel.id == reel_id,
            Reel.is_active == True
        ).first()
        if not reel:
            raise HTTPException(status_code=404, detail="Reel not found")

        owner = db.query(User).filter(User.id == reel.owner_id).first()
        is_liked = db.query(Like).filter(
            Like.reel_id == reel.id,
            Like.user_id == current_user.id
        ).first() is not None

        return {
            "id": reel.id,
            "caption": reel.caption,
            "video_url": reel.video_url,
            "thumbnail_url": reel.thumbnail_url,
            "school_tag": reel.school_tag,
            "likes_count": reel.likes_count,
            "comments_count": reel.comments_count,
            "views_count": reel.views_count,
            "created_at": reel.created_at,
            "owner_id": reel.owner_id,
            "owner_username": owner.username if owner else None,
            "owner_avatar": owner.avatar_url if owner else None,
            "owner_school": owner.school_name if owner else None,
            "is_liked": is_liked,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))