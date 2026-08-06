from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.reel import Reel, Follow, Like
from app.schemas.user import UserResponse
import cloudinary
import cloudinary.uploader
import os
from pydantic import BaseModel

class FCMTokenRequest(BaseModel):
    fcm_token: str

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

    # Count followers and following
    followers_count = db.query(Follow).filter(
        Follow.following_id == user.id
    ).count()

    following_count = db.query(Follow).filter(
        Follow.follower_id == user.id
    ).count()

    # Use aggregates — never load all reels into memory just to count them
    from sqlalchemy import func as sqlfunc
    stats = db.query(
        sqlfunc.count(Reel.id).label("reels_count"),
        sqlfunc.coalesce(sqlfunc.sum(Reel.likes_count), 0).label("total_likes")
    ).filter(
        Reel.owner_id == user.id,
        Reel.is_active == True
    ).first()

    reels_count = stats.reels_count if stats else 0
    total_likes = stats.total_likes if stats else 0

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
        "is_admin": user.is_admin,
        "is_founding_member": user.is_founding_member,
        "followers_count": followers_count,
        "following_count": following_count,
        "total_likes": total_likes,
        "reels_count": reels_count,
        "is_following": is_following,
        "is_own_profile": current_user.id == user.id,
    }


@router.get("/profile/{username}/reels")
def get_user_reels(
    username: str,
    skip: int = 0,
    limit: int = 21,  # 7 rows of 3 — clean grid increments
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Find the user first
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Paginated — never load a user's entire reel history at once
    reels = (
        db.query(Reel)
        .filter(Reel.owner_id == user.id, Reel.is_active == True)
        .order_by(Reel.created_at.desc())
        .offset(skip)
        .limit(min(limit, 30))  # hard cap to prevent abuse
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
    if school_name: current_user.school_name = " ".join(school_name.split())
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

# class FCMTokenRequest(BaseModel):
#     fcm_token: str

@router.post("/fcm-token")
def save_fcm_token(
    body: FCMTokenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.fcm_token = body.fcm_token
    db.commit()
    return {"message": "Token saved"}

@router.get("/founding-members")
def get_founding_members(
    db: Session = Depends(get_db),
):
    """
    Returns the first 100 users (founding members) for the homepage feature strip.
    Public endpoint — no auth required so it works on the welcome page too.
    """
    members = (
        db.query(User)
        .filter(
            User.is_active == True,
            User.is_founding_member == True,
        )
        .order_by(User.created_at.asc())
        .limit(100)
        .all()
    )
    return [
        {
            "id":         m.id,
            "username":   m.username,
            "avatar_url": m.avatar_url,
            "school_name": m.school_name,
        }
        for m in members
    ]


@router.post("/grant-founding/{username}")
def grant_founding_member(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Admin only — mark a user as a founding member."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_founding_member = True
    db.commit()
    return {"message": f"@{username} is now a founding member"}


# --- ONBOARDING ---
# Runs once, right after signup: confirm school (reuses the existing
# /profile/edit endpoint below, since school_name is already a field on
# it — no new endpoint needed for that part) + suggest people to follow.

@router.get("/onboarding/suggestions")
def get_onboarding_suggestions(
    limit: int = 12,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    already_following_ids = {
        f.following_id for f in
        db.query(Follow).filter(Follow.follower_id == current_user.id).all()
    }
    exclude_ids = already_following_ids | {current_user.id}

    suggestions = []

    # Prioritize people at the same school — most relevant, most likely to
    # actually be recognized/followed back.
    if current_user.school_name:
        same_school = (
            db.query(User)
            .filter(
                User.school_name == current_user.school_name,
                User.id.notin_(exclude_ids),
                User.is_active == True,
            )
            .order_by(desc(User.is_founding_member), desc(User.created_at))
            .limit(limit)
            .all()
        )
        suggestions.extend(same_school)

    # Fill any remaining slots with active users from anywhere — keeps the
    # screen from looking sparse for early adopters at a new/small school.
    if len(suggestions) < limit:
        exclude_ids |= {u.id for u in suggestions}
        fill = (
            db.query(User)
            .filter(User.id.notin_(exclude_ids), User.is_active == True)
            .order_by(desc(User.is_founding_member), desc(User.created_at))
            .limit(limit - len(suggestions))
            .all()
        )
        suggestions.extend(fill)

    return [
        {
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name,
            "avatar_url": u.avatar_url,
            "school_name": u.school_name,
            "is_verified": u.is_verified,
            "is_founding_member": u.is_founding_member,
        }
        for u in suggestions
    ]


@router.post("/onboarding/complete")
def complete_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.has_completed_onboarding = True
    db.commit()
    return {"has_completed_onboarding": True}