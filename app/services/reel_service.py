import cloudinary
import cloudinary.uploader
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, text
from fastapi import HTTPException, status
from app.models.reel import Reel, Like, Comment, Follow
from app.models.user import User
import os
from dotenv import load_dotenv
import random
from sqlalchemy import func

load_dotenv()

# Configure Cloudinary with our credentials from .env
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

def upload_video_to_cloudinary(
    file_bytes: bytes,
    filename: str,
    trim_start: float = 0,
    trim_end: float = None,
    text_overlays: list = []
) -> dict:
    try:
        transformation = []

        if trim_start is not None or trim_end is not None:
            trim = {}
            if trim_start: trim["start_offset"] = str(trim_start)
            if trim_end: trim["end_offset"] = str(trim_end)
            transformation.append(trim)

        for overlay in text_overlays:
            transformation.append({
                "overlay": {
                    "font_family": "Arial",
                    "font_size": overlay.get("size", 24),
                    "font_weight": "bold",
                    "text": overlay.get("text", ""),
                },
                "color": overlay.get("color", "#ffffff"),
                "gravity": "center",
                "y": 0,
            })

        # Upload params
        upload_params = {
    "resource_type": "video",
    "folder": "campusvibe/reels",
    "quality": "auto:low",    # 👈 compress aggressively
    "fetch_format": "auto",   # 👈 serve best format (mp4/webm)
}

        # If we have transformations use eager_async
        # This means Cloudinary processes them in the background
        # instead of making the user wait
        if transformation:
            upload_params["eager"] = transformation
            upload_params["eager_async"] = True  # 👈 process in background
        
        result = cloudinary.uploader.upload(
            file_bytes,
            **upload_params
        )

        video_url = result.get("secure_url")
        public_id = result.get("public_id")

        # Thumbnail generated from the raw uploaded video
        # not from the transformation — so it's always available immediately
        thumbnail_url = (
            f"https://res.cloudinary.com/"
            f"{os.getenv('CLOUDINARY_CLOUD_NAME')}"
            f"/video/upload/so_1,w_400,h_600,c_fill/{public_id}.jpg"
        )

        return {
            "video_url": video_url,
            "thumbnail_url": thumbnail_url
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Video upload failed: {str(e)}"
        )
            
def upload_image_to_cloudinary(file_bytes: bytes, filename: str, text_overlays: list = []) -> dict:
    """
    Uploads an image to Cloudinary as a video resource so it plays in the feed
    exactly like a reel. We use resource_type='video' with a still-image source
    — Cloudinary handles the conversion to a 5-second looping video.
    """
    try:
        # Build text overlay transformations
        overlay_transformations = []
        for overlay in text_overlays:
            overlay_transformations.append({
                "overlay": {
                    "font_family": "Arial",
                    "font_size": overlay.get("size", 24),
                    "font_weight": "bold",
                    "text": overlay.get("text", ""),
                },
                "color": overlay.get("color", "#ffffff"),
                "gravity": "center",
            })

        upload_params = {
            "resource_type": "image",
            "folder": "campusvibe/photos",
            "quality": "auto:good",
            "transformation": [
                # Crop to 9:16 portrait with blurred background fill
                {"width": 720, "height": 1280, "crop": "pad", "background": "gen_fill"},
                *overlay_transformations,
            ],
        }

        result = cloudinary.uploader.upload(file_bytes, **upload_params)

        public_id  = result.get("public_id")
        secure_url = result.get("secure_url")
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")

        # The image URL IS the video_url — the feed VideoCard handles both
        # images and videos. We serve the transformed image directly.
        video_url = secure_url

        thumbnail_url = (
            f"https://res.cloudinary.com/{cloud_name}"
            f"/image/upload/w_400,h_600,c_fill/{public_id}.jpg"
        )

        return {
            "video_url": video_url,
            "thumbnail_url": thumbnail_url,
            "is_photo": True,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Image upload failed: {str(e)}"
        )


def create_reel(
    db: Session,
    owner_id: str,
    video_url: str,
    thumbnail_url: str,
    caption: str,
    school_tag: str,
    is_photo: bool = False,
):
    """Creates a new reel record in the database."""
    new_reel = Reel(
        owner_id=owner_id,
        video_url=video_url,
        thumbnail_url=thumbnail_url,
        caption=caption,
        school_tag=school_tag,
        is_photo=is_photo,
    )
    db.add(new_reel)
    db.commit()
    db.refresh(new_reel)
    return new_reel

# def get_feed(db: Session, current_user_id: str, feed_type: str = "foryou", skip: int = 0, limit: int = 10):
#     """
#     For You feed logic:
#     - 70% same school as the logged in user
#     - 30% from other schools
#     - ordered by newest first

#     Following feed:
#     - only reels from people the user follows
#     """

#     if feed_type == "following":
#         # Get IDs of everyone the current user follows
#         following_ids = [
#             f.following_id for f in
#             db.query(Follow).filter(Follow.follower_id == current_user_id).all()
#         ]

#         if not following_ids:
#             return []  # Following no one — empty feed

#         reels = (
#             db.query(Reel)
#             .filter(Reel.owner_id.in_(following_ids), Reel.is_active == True)
#             .order_by(desc(Reel.created_at))
#             .offset(skip)
#             .limit(limit)
#             .all()
#         )

#     else:
#         # FOR YOU — smart school-weighted feed
#         # Get current user's school
#         current_user = db.query(User).filter(User.id == current_user_id).first()
#         user_school = current_user.school_name if current_user else None

#         same_school_reels = []
#         other_school_reels = []

#         if user_school:
#             # 70% — same school reels
#             same_school_reels = (
#                 db.query(Reel)
#                 .join(User, Reel.owner_id == User.id)
#                 .filter(
#                     Reel.is_active == True,
#                     Reel.owner_id != current_user_id,  # exclude own reels
#                     User.school_name == user_school
#                 )
#                 .order_by(desc(Reel.created_at))
#                 .limit(int(limit * 0.7))  # 70% of feed
#                 .all()
#             )

#             # 30% — other schools
#             other_school_reels = (
#                 db.query(Reel)
#                 .join(User, Reel.owner_id == User.id)
#                 .filter(
#                     Reel.is_active == True,
#                     Reel.owner_id != current_user_id,
#                     User.school_name != user_school
#                 )
#                 .order_by(desc(Reel.created_at))
#                 .limit(int(limit * 0.3))  # 30% of feed
#                 .all()
#             )

#             # Interleave them — don't just dump all same school then all others
#             # Pattern: same, same, other, same, same, other...
#             reels = []
#             s, o = 0, 0
#             for i in range(limit):
#                 if i % 3 == 2 and o < len(other_school_reels):
#                     reels.append(other_school_reels[o]); o += 1
#                 elif s < len(same_school_reels):
#                     reels.append(same_school_reels[s]); s += 1
#                 elif o < len(other_school_reels):
#                     reels.append(other_school_reels[o]); o += 1
#         else:
#             # No school set — just show all reels
#             reels = (
#                 db.query(Reel)
#                 .filter(Reel.is_active == True)
#                 .order_by(desc(Reel.created_at))
#                 .offset(skip)
#                 .limit(limit)
#                 .all()
#             )

#     # Build response with owner info and like status
#     result = []
#     for reel in reels:
#         owner = db.query(User).filter(User.id == reel.owner_id).first()
#         is_liked = db.query(Like).filter(
#             Like.reel_id == reel.id,
#             Like.user_id == current_user_id
#         ).first() is not None

#         result.append({
#             "id": reel.id,
#             "caption": reel.caption,
#             "video_url": reel.video_url,
#             "thumbnail_url": reel.thumbnail_url,
#             "school_tag": reel.school_tag,
#             "likes_count": reel.likes_count,
#             "comments_count": reel.comments_count,
#             "views_count": reel.views_count,
#             "created_at": reel.created_at,
#             "owner_id": reel.owner_id,
#             "owner_username": owner.username if owner else None,
#             "owner_avatar": owner.avatar_url if owner else None,
#             "owner_school": owner.school_name if owner else None,
#             "is_liked": is_liked,
#         })

#     return result

def _build_feed_response(db: Session, reels: list, current_user_id: str) -> list:
    """
    Single helper that resolves owner info + like status for a list of reels
    using bulk queries instead of N+1 individual lookups.

    Before: 10 reels = 21 DB queries (1 feed + 10 owner lookups + 10 like checks)
    After:  10 reels = 3 DB queries  (1 feed + 1 bulk owner + 1 bulk like check)
    """
    if not reels:
        return []

    reel_ids    = [r.id for r in reels]
    owner_ids   = list({r.owner_id for r in reels})

    # One query for all owners
    owners = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(owner_ids)).all()
    }

    # One query for all likes by this user across all returned reels
    liked_reel_ids = {
        like.reel_id
        for like in db.query(Like).filter(
            Like.reel_id.in_(reel_ids),
            Like.user_id == current_user_id
        ).all()
    }

    result = []
    for reel in reels:
        owner = owners.get(reel.owner_id)
        result.append({
            "id":              reel.id,
            "caption":         reel.caption,
            "video_url":       reel.video_url,
            "thumbnail_url":   reel.thumbnail_url,
            "school_tag":      reel.school_tag,
            "is_photo":        reel.is_photo,
            "likes_count":     reel.likes_count,
            "comments_count":  reel.comments_count,
            "views_count":     reel.views_count,
            "created_at":      reel.created_at,
            "owner_id":        reel.owner_id,
            "owner_username":  owner.username   if owner else None,
            "owner_avatar":    owner.avatar_url if owner else None,
            "owner_school":    owner.school_name if owner else None,
            "is_liked":        reel.id in liked_reel_ids,
        })

    return result


def get_feed(db: Session, current_user_id: str, feed_type: str = "foryou", skip: int = 0, limit: int = 10):

    if feed_type == "following":
        following_subq = (
            db.query(Follow.following_id)
            .filter(Follow.follower_id == current_user_id)
            .subquery()
        )
        reels = (
            db.query(Reel)
            .filter(
                Reel.owner_id.in_(following_subq),
                Reel.is_active == True
            )
            .order_by(desc(Reel.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _build_feed_response(db, reels, current_user_id)

    # ── FOR YOU ──────────────────────────────────────────────────────────────
    # Strategy:
    # - Never show your own reels
    # - 5% chance of showing your reel to others (handled on their feeds)
    # - Use a per-user daily seed so ordering feels consistent within a session
    #   but changes the next day — no repeats within one scroll session
    # - When skip >= total reels (feed exhausted), loop back from 0 with a
    #   new seed so the feed never actually ends
    # - 65% same school, 35% other schools for a good mix

    import hashlib
    from datetime import date

    # Seed = user_id + today's date — stable within a day, different tomorrow
    seed_str = f"{current_user_id}{date.today().isoformat()}"
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % 999983

    total_active = db.query(func.count(Reel.id)).filter(
        Reel.is_active == True,
        Reel.owner_id != current_user_id,
    ).scalar() or 0

    # If we've scrolled past all reels, loop back with a shifted seed
    # so content reshuffles instead of stopping
    effective_skip = skip
    loop_offset = 0
    if total_active > 0 and skip >= total_active:
        loop_offset = (skip // total_active) * 7  # shift seed each loop
        effective_skip = skip % total_active

    seed_expr = text("MD5(reels.id || CAST(:seed AS TEXT))")
    seed_val = seed_hash + loop_offset

    current_user = db.query(User).filter(User.id == current_user_id).first()
    user_school  = current_user.school_name if current_user else None

    if user_school:
        same_school_reels = (
            db.query(Reel)
            .join(User, Reel.owner_id == User.id)
            .filter(
                Reel.is_active == True,
                Reel.owner_id != current_user_id,
                User.school_name == user_school
            )
            .order_by(seed_expr)
            .params(seed=seed_val)
            .limit(int(limit * 0.65))
            .offset(effective_skip)
            .all()
        )

        other_school_reels = (
            db.query(Reel)
            .join(User, Reel.owner_id == User.id)
            .filter(
                Reel.is_active == True,
                Reel.owner_id != current_user_id,
                User.school_name != user_school
            )
            .order_by(seed_expr)
            .params(seed=seed_val)
            .limit(int(limit * 0.35))
            .offset(effective_skip)
            .all()
        )

        # Interleave: ~2 same-school then 1 other, repeat
        reels, s, o = [], 0, 0
        for i in range(limit):
            if i % 3 == 2 and o < len(other_school_reels):
                reels.append(other_school_reels[o]); o += 1
            elif s < len(same_school_reels):
                reels.append(same_school_reels[s]); s += 1
            elif o < len(other_school_reels):
                reels.append(other_school_reels[o]); o += 1

    else:
        reels = (
            db.query(Reel)
            .filter(
                Reel.is_active == True,
                Reel.owner_id != current_user_id,
            )
            .order_by(seed_expr)
            .params(seed=seed_val)
            .offset(effective_skip)
            .limit(limit)
            .all()
        )

    return _build_feed_response(db, reels, current_user_id)

def toggle_like(db: Session, reel_id: str, user_id: str):
    """
    Likes a reel if not liked, unlikes if already liked.
    Returns whether the reel is now liked or not.
    """
    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    # Check if already liked
    existing_like = db.query(Like).filter(
        Like.reel_id == reel_id,
        Like.user_id == user_id
    ).first()

    if existing_like:
        # Already liked — remove the like (unlike)
        db.delete(existing_like)
        reel.likes_count = max(0, reel.likes_count - 1)
        db.commit()
        return {"liked": False, "likes_count": reel.likes_count}
    else:
        # Not liked yet — add the like
        new_like = Like(reel_id=reel_id, user_id=user_id)
        db.add(new_like)
        reel.likes_count += 1
        db.commit()
        return {"liked": True, "likes_count": reel.likes_count}


def add_comment(db: Session, reel_id: str, user_id: str, text: str):
    """Adds a comment to a reel."""
    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    comment = Comment(
        reel_id=reel_id,
        user_id=user_id,
        text=text
    )
    db.add(comment)
    reel.comments_count += 1
    db.commit()
    db.refresh(comment)
    return comment

def increment_views(db: Session, reel_id: str, user_id: str):
    """
    Counts a view only once per user per reel.
    Same user watching the same reel 100 times = still 1 view.
    Different users watching = 1 view each.
    """
    from app.models.reel import VideoView

    # Check if this user already viewed this reel
    already_viewed = db.query(VideoView).filter(
        VideoView.reel_id == reel_id,
        VideoView.user_id == user_id
    ).first()

    if already_viewed:
        # Already watched — don't count again
        return {"counted": False}

    # First time watching — record it and increment
    new_view = VideoView(reel_id=reel_id, user_id=user_id)
    db.add(new_view)

    reel = db.query(Reel).filter(Reel.id == reel_id).first()
    if reel:
        reel.views_count += 1

    db.commit()
    return {"counted": True}