from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.reel import Reel, Follow, Like
from app.schemas.user import UserResponse
import cloudinary
import cloudinary.uploader
import os

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/profile/{username}")
def get_profile(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Find the user by username
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Count followers — how many people follow this user
    followers_count = db.query(Follow).filter(
        Follow.following_id == user.id
    ).count()

    # Count following — how many people this user follows
    following_count = db.query(Follow).filter(
        Follow.follower_id == user.id
    ).count()

    # Count total likes across all their reels
    reels = db.query(Reel).filter(Reel.owner_id == user.id).all()
    total_likes = sum(r.likes_count for r in reels)

    # Check if the current logged in user follows this profile
    is_following = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == user.id
    ).first() is not None

    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "bio": user.bio,
        "avatar_url": user.avatar_url,
        "school_name": user.school_name,
        "programme": user.programme,
        "year_of_study": user.year_of_study,
        "is_verified": user.is_verified,
        "followers_count": followers_count,
        "following_count": following_count,
        "total_likes": total_likes,
        "reels_count": len(reels),
        "is_following": is_following,
        "is_own_profile": current_user.id == user.id,
    }


@router.get("/profile/{username}/reels")
def get_user_reels(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Find the user first
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get all their reels newest first
    reels = (
        db.query(Reel)
        .filter(Reel.owner_id == user.id, Reel.is_active == True)
        .order_by(Reel.created_at.desc())
        .all()
    )

    return [
        {
            "id": r.id,
            "video_url": r.video_url,
            "thumbnail_url": r.thumbnail_url,
            "caption": r.caption,
            "likes_count": r.likes_count,
            "views_count": r.views_count,
            "created_at": r.created_at,
        }
        for r in reels
    ]

@router.put("/profile/edit")
async def edit_profile(
    full_name: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    school_name: Optional[str] = Form(None),
    programme: Optional[str] = Form(None),
    year_of_study: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if full_name: current_user.full_name = full_name
    if bio: current_user.bio = bio
    if school_name: current_user.school_name = school_name
    if programme: current_user.programme = programme
    if year_of_study: current_user.year_of_study = year_of_study

    # Handle avatar upload to Cloudinary
    if avatar:
        file_bytes = await avatar.read()
        result = cloudinary.uploader.upload(
            file_bytes,
            folder="campusvibe/avatars",
            transformation={"width": 400, "height": 400, "crop": "fill"}
        )
        current_user.avatar_url = result.get("secure_url")

    db.commit()
    db.refresh(current_user)

    return {
        "message": "Profile updated",
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "full_name": current_user.full_name,
            "bio": current_user.bio,
            "avatar_url": current_user.avatar_url,
            "school_name": current_user.school_name,
            "programme": current_user.programme,
            "year_of_study": current_user.year_of_study,
        }
    }


@router.post("/follow/{username}")
def follow_user(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    user_to_follow = db.query(User).filter(User.username == username).first()
    if not user_to_follow:
        raise HTTPException(status_code=404, detail="User not found")
    if user_to_follow.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself")

    existing = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == user_to_follow.id
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"following": False, "message": f"Unfollowed {username}"}
    else:
        new_follow = Follow(
            follower_id=current_user.id,
            following_id=user_to_follow.id
        )
        db.add(new_follow)
        db.commit()

        # Notify the followed user
        from app.services.notification_service import create_notification
        create_notification(
            db=db,
            recipient_id=user_to_follow.id,
            sender_id=current_user.id,
            type="follow",
            message=f"@{current_user.username} started following you",
        )
        return {"following": True, "message": f"Now following {username}"}