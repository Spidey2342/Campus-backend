import cloudinary
import cloudinary.uploader
import os
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from app.models.user import User

load_dotenv()

# Reuses the same Cloudinary account as reels — configure() is idempotent,
# safe to call again here even though reel_service.py already does it.
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

TRIAL_DAYS = 7
MAX_LISTING_PHOTOS = 4
MAX_PHOTO_SIZE_BYTES = 8 * 1024 * 1024  # 8MB per photo


def upload_listing_photo(file_bytes: bytes) -> str:
    """Plain image upload — unlike reel photos, listing photos are just
    product/service photos, not turned into looping videos."""
    result = cloudinary.uploader.upload(
        file_bytes,
        resource_type="image",
        folder="campusvibe/marketplace",
        quality="auto:good",
    )
    return result.get("secure_url")


def encode_photo_urls(urls: list) -> str:
    return json.dumps(urls or [])


def decode_photo_urls(raw: str) -> list:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def get_seller_status(user: User) -> dict:
    """Single source of truth for whether a user can post listings.
    Mirrors the shape the frontend's mock getSellerStatus() already expects."""
    if user.seller_source in ("admin_free", "paid"):
        return {
            "is_seller": True,
            "source": user.seller_source,
            "trial_ends_at": None,
            "days_left": None,
        }

    if user.seller_source == "trial" and user.seller_trial_ends_at:
        expires = user.seller_trial_ends_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        seconds_left = (expires - now).total_seconds()
        days_left = max(0, -(-int(seconds_left) // 86400))  # ceil division

        return {
            "is_seller": seconds_left > 0,
            "source": "trial",
            "trial_ends_at": user.seller_trial_ends_at,
            "days_left": days_left,
        }

    return {"is_seller": False, "source": None, "trial_ends_at": None, "days_left": None}


def start_seller_trial(user: User) -> dict:
    user.seller_source = "trial"
    user.seller_trial_ends_at = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)
    return get_seller_status(user)