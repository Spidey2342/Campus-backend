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
    Uploads an image to Cloudinary and converts it into a 5-second looping
    video (using Cloudinary's video generation), so images play in the feed
    exactly like reels. Text overlays are burned in server-side.
    """
    try:
        transformation = [
            # Pad to 9:16 portrait — fills empty space with blurred version of the image
            {"width": 720, "height": 1280, "crop": "pad", "background": "blurred"},
        ]

        for overlay in text_overlays:
            transformation.append({
                "overlay": {
                    "font_family": "Arial",
                    "font_size": overlay.get("size", 24),
                    "font_weight": "bold",
                    "text": overlay.get("text", ""),
                },
                "color": overlay.get("color", "#ffffff"),
                # Use percentage gravity so position matches frontend (x/y as %)
                "gravity": "north_west",
                "x": f"{overlay.get('x', 50)}p",
                "y": f"{overlay.get('y', 50)}p",
            })

        result = cloudinary.uploader.upload(
            file_bytes,
            resource_type="image",
            folder="campusvibe/photos",
            transformation=transformation,
            quality="auto:good",
        )

        public_id = result.get("public_id")
        image_url = result.get("secure_url")

        # Cloudinary can serve an image as a looping video using /video/upload
        # with fl_loop and du_ (duration). This means no separate video encoding —
        # the image just loops as a 5-second slideshow in the player.
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
        video_url = (
            f"https://res.cloudinary.com/{cloud_name}"
            f"/video/upload/du_5,fl_loop,q_auto/campusvibe/photos/{public_id.split('/')[-1]}.mp4"
        )

        # Thumbnail is just the image itself resized
        thumbnail_url = (
            f"https://res.cloudinary.com/{cloud_name}"
            f"/image/upload/w_400,h_600,c_fill/{public_id}.jpg"
        )

        return {
            "video_url": video_url,
            "thumbnail_url": thumbnail_url
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
    school_tag: str
):
    """Creates a new reel record in the database."""
    new_reel = Reel(
        owner_id=owner_id,
        video_url=video_url,
        thumbnail_url=thumbnail_url,
        caption=caption,
        school_tag=school_tag,
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
        # Subquery — never loads follow IDs into Python memory
        # Scales to 100k follows without issue
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

    else:
        current_user = db.query(User).filter(User.id == current_user_id).first()
        user_school  = current_user.school_name if current_user else None

        if user_school:
            seed_expr = text("MD5(reels.id || CAST(:skip AS TEXT))")

            same_school_reels = (
                db.query(Reel)
                .join(User, Reel.owner_id == User.id)
                .filter(
                    Reel.is_active == True,
                    Reel.owner_id != current_user_id,  # never show your own reels in For You
                    User.school_name == user_school
                )
                .order_by(seed_expr)
                .params(skip=skip)
                .limit(int(limit * 0.6))  # 60% same school (was 70% — too heavy)
                .all()
            )

            other_school_reels = (
                db.query(Reel)
                .join(User, Reel.owner_id == User.id)
                .filter(
                    Reel.is_active == True,
                    Reel.owner_id != current_user_id,  # never show your own reels
                    User.school_name != user_school
                )
                .order_by(seed_expr)
                .params(skip=skip)
                .limit(int(limit * 0.4))  # 40% other schools (was 30%)
                .all()
            )

            # Interleave: 2 same-school, 1 other, repeat
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
                    Reel.owner_id != current_user_id,  # never show your own reels
                )
                .order_by(text("MD5(reels.id || CAST(:skip AS TEXT))"))
                .params(skip=skip)
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