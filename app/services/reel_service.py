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
import hashlib
from datetime import date
from sqlalchemy import func
import re
import urllib.parse

load_dotenv()

# Configure Cloudinary with our credentials from .env
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

# Cloudinary's l_text overlay renders using an actual font (Arial here),
# and standard fonts like Arial have no emoji glyphs. Cloudinary validates
# this server-side and returns a hard 400 for the WHOLE transformation
# chain if the text contains one — meaning one emoji in a caption breaks
# the entire video/photo, not just the missing character. We strip emoji
# out of overlay text before it's ever sent, so worst case an overlay
# loses an emoji rather than the whole post failing to load.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)


def _sanitize_overlay_text(raw: str) -> str:
    stripped = _EMOJI_PATTERN.sub("", raw or "")
    return re.sub(r"\s{2,}", " ", stripped).strip()

def upload_video_to_cloudinary(
    file_bytes: bytes,
    filename: str,
    trim_start: float = 0,
    trim_end: float = None,
    text_overlays: list = []
) -> dict:
    try:
        # Upload the raw video — NO transformations at upload time
        # Large videos can't be transformed synchronously on Cloudinary's free tier
        # Instead we bake trim + overlays into the delivery URL below
        upload_params = {
            "resource_type": "video",
            "folder": "campusvibe/reels",
            "quality": "auto:low",
        }

        result = cloudinary.uploader.upload(file_bytes, **upload_params)

        public_id  = result.get("public_id")
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")

        # Build transformation string for delivery URL
        # Cloudinary applies these on-the-fly when the video is served
        transforms = []

        if trim_start and float(trim_start) > 0:
            transforms.append(f"so_{trim_start}")
        if trim_end and float(trim_end) > 0:
            transforms.append(f"eo_{trim_end}")

        for overlay in text_overlays:
            clean_text = _sanitize_overlay_text(overlay.get("text", ""))
            if not clean_text:
                continue  # e.g. the whole overlay was just an emoji — skip it rather than bake a broken layer
            text_encoded = urllib.parse.quote(clean_text, safe="")
            size  = overlay.get("size", 24)
            color = overlay.get("color", "white").lstrip("#")
            transforms.append(f"l_text:Arial_{size}_bold:{text_encoded},co_rgb:{color},g_center")

        transform_str = "/".join(transforms)
        if transform_str:
            video_url = (
                f"https://res.cloudinary.com/{cloud_name}"
                f"/video/upload/{transform_str}/{public_id}.mp4"
            )
        else:
            video_url = (
                f"https://res.cloudinary.com/{cloud_name}"
                f"/video/upload/{public_id}.mp4"
            )

        # Thumbnail — grab frame at 1 second
        thumbnail_url = (
            f"https://res.cloudinary.com/{cloud_name}"
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
            clean_text = _sanitize_overlay_text(overlay.get("text", ""))
            if not clean_text:
                continue  # e.g. the whole overlay was just an emoji — skip it rather than bake a broken layer
            overlay_transformations.append({
                "overlay": {
                    "font_family": "Arial",
                    "font_size": overlay.get("size", 24),
                    "font_weight": "bold",
                    "text": clean_text,
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

    # One query for which of these owners the current user already follows
    # — drives whether the "+" quick-follow badge shows on their avatar.
    followed_owner_ids = {
        f.following_id
        for f in db.query(Follow).filter(
            Follow.follower_id == current_user_id,
            Follow.following_id.in_(owner_ids)
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
            "is_following_owner": reel.owner_id == current_user_id or reel.owner_id in followed_owner_ids,
        })

    return result

def _rotating_query(base_query, seed: float, limit: int, offset: int = 0):
    """Page through random_rank starting at `seed`, wrapping around circularly.
    `offset` advances through the *already-seeded* window — without it, every
    page request (regardless of skip) returns the same starting slice."""
    first_q = base_query.filter(Reel.random_rank >= seed).order_by(Reel.random_rank.asc())
    first_count = first_q.count()

    if offset < first_count:
        first = first_q.offset(offset).limit(limit).all()
        if len(first) < limit:
            remaining = limit - len(first)
            wrapped = base_query.filter(Reel.random_rank < seed) \
                                 .order_by(Reel.random_rank.asc()) \
                                 .limit(remaining).all()
            first += wrapped
        return first

    # Offset has moved past the >= seed window entirely — continue into
    # the wrapped (< seed) portion, adjusted for how far past we are.
    wrapped_offset = offset - first_count
    return base_query.filter(Reel.random_rank < seed) \
                      .order_by(Reel.random_rank.asc()) \
                      .offset(wrapped_offset).limit(limit).all()


def get_feed(db: Session, current_user_id: str, feed_type: str = "foryou", skip: int = 0, limit: int = 10, loop: int = 0, session_seed: str = None):
    if feed_type == "following":
        following_subq = (
            db.query(Follow.following_id)
            .filter(Follow.follower_id == current_user_id)
            .subquery()
        )
        reels = (
            db.query(Reel)
            .filter(Reel.owner_id.in_(following_subq), Reel.is_active == True)
            .order_by(desc(Reel.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _build_feed_response(db, reels, current_user_id)

    # The shuffle seed determines the whole ordering below. session_seed is
    # a random value the frontend generates once per page load/refresh and
    # sends on every request during that visit — so scrolling further
    # (skip increasing) keeps a stable order within one sitting, but a
    # fresh refresh gets a genuinely different shuffle, the way TikTok
    # does. If the caller doesn't send one (older client, or a direct API
    # call), we fall back to the old date-based seed so the feed still
    # works, just without the per-refresh variety.
    seed_source = session_seed or date.today().isoformat()
    seed_str = f"{current_user_id}{seed_source}{skip // 200}{loop}"
    seed_hash = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)
    seed_val = (seed_hash % 1000) / 1000.0  # float in [0, 1)

    current_user = db.query(User).filter(User.id == current_user_id).first()
    user_school = current_user.school_name if current_user else None

    base = db.query(Reel).join(User, Reel.owner_id == User.id).filter(
        Reel.is_active == True,
        Reel.owner_id != current_user_id,
    )

    if user_school:
        same_school = _rotating_query(
            base.filter(User.school_name == user_school), seed_val,
            int(limit * 0.65), offset=int(skip * 0.65)
        )
        other_school = _rotating_query(
            base.filter(User.school_name != user_school), seed_val,
            int(limit * 0.35), offset=int(skip * 0.35)
        )
        reels, s, o = [], 0, 0
        for i in range(limit):
            if i % 3 == 2 and o < len(other_school):
                reels.append(other_school[o]); o += 1
            elif s < len(same_school):
                reels.append(same_school[s]); s += 1
            elif o < len(other_school):
                reels.append(other_school[o]); o += 1
    else:
        reels = _rotating_query(base, seed_val, limit, offset=skip)

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