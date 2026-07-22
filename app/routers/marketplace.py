from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.reel import Listing, Conversation, ConversationMember, Message
from app.schemas.listing import ListingResponse, SellerStatusResponse, CATEGORIES
from app.services.marketplace_service import (
    upload_listing_photo, encode_photo_urls, decode_photo_urls,
    get_seller_status, start_seller_trial,
    MAX_LISTING_PHOTOS, MAX_PHOTO_SIZE_BYTES,
)
from app.routers.messages import get_conversation_detail

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])
limiter = Limiter(key_func=get_remote_address)


def require_admin(current_user: User):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


def _serialize(listing: Listing) -> dict:
    return {
        "id": listing.id,
        "title": listing.title,
        "description": listing.description,
        "price": listing.price,
        "currency": listing.currency,
        "category": listing.category,
        "photos": decode_photo_urls(listing.photo_urls),
        "school_name": listing.school_name,
        "status": listing.status,
        "created_at": listing.created_at,
        "seller": listing.seller,
    }


# --- SELLER STATUS ---

@router.get("/seller-status", response_model=SellerStatusResponse)
def seller_status(current_user: User = Depends(get_current_user)):
    status = get_seller_status(current_user)
    return {
        "is_seller": status["is_seller"],
        "source": status["source"],
        "trial_ends_at": status["trial_ends_at"],
        "days_left": status["days_left"],
    }


@router.post("/become-seller", response_model=SellerStatusResponse)
def become_seller(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Already a seller (trial, admin_free, or paid) — don't reset an active trial
    existing = get_seller_status(current_user)
    if existing["is_seller"]:
        return existing

    status = start_seller_trial(current_user)
    db.commit()
    return status


# --- ADMIN: grant free seller status by hand ---

@router.post("/admin/grant-seller/{username}", response_model=SellerStatusResponse)
def admin_grant_seller(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.seller_source = "admin_free"
    target.seller_trial_ends_at = None
    db.commit()
    return get_seller_status(target)


@router.post("/admin/revoke-seller/{username}", status_code=200)
def admin_revoke_seller(
    username: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.seller_source = None
    target.seller_trial_ends_at = None
    db.commit()
    return {"message": f"{username} is no longer a seller"}


# --- LISTINGS ---

@router.get("/listings", response_model=List[ListingResponse])
def get_listings(
    category: Optional[str] = None,
    school: Optional[str] = None,
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Listing).filter(Listing.status == "active")

    if category and category != "All":
        query = query.filter(Listing.category == category)
    if school:
        query = query.filter(Listing.school_name == school)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Listing.title.ilike(like)) | (Listing.description.ilike(like))
        )

    listings = (
        query.order_by(desc(Listing.created_at))
        .offset(skip).limit(min(limit, 50))
        .all()
    )
    return [_serialize(l) for l in listings]


@router.get("/listings/mine", response_model=List[ListingResponse])
def get_my_listings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listings = (
        db.query(Listing)
        .filter(Listing.seller_id == current_user.id)
        .order_by(desc(Listing.created_at))
        .all()
    )
    return [_serialize(l) for l in listings]


@router.get("/listings/{listing_id}", response_model=ListingResponse)
def get_listing(
    listing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return _serialize(listing)


# 10 new listings per hour — generous for a real seller, blocks spam
@router.post("/listings", response_model=ListingResponse, status_code=201)
@limiter.limit("10/hour")
async def create_listing(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    photos: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    seller_status_now = get_seller_status(current_user)
    if not seller_status_now["is_seller"]:
        raise HTTPException(
            status_code=403,
            detail="You need to become a seller before posting a listing.",
        )

    title = title.strip()
    description = description.strip()
    if not title or len(title) > 80:
        raise HTTPException(status_code=400, detail="Title must be 1-80 characters")
    if not description or len(description) > 500:
        raise HTTPException(status_code=400, detail="Description must be 1-500 characters")
    if price <= 0 or price > 1_000_000:
        raise HTTPException(status_code=400, detail="Enter a valid price")
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Category must be one of: {', '.join(CATEGORIES)}")
    if len(photos) > MAX_LISTING_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Max {MAX_LISTING_PHOTOS} photos")

    photo_urls = []
    for photo in photos:
        if not photo.content_type or not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Photos must be images")
        file_bytes = await photo.read()
        if len(file_bytes) > MAX_PHOTO_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="Each photo must be under 8MB")
        photo_urls.append(upload_listing_photo(file_bytes))

    listing = Listing(
        seller_id=current_user.id,
        title=title,
        description=description,
        price=price,
        category=category,
        photo_urls=encode_photo_urls(photo_urls),
        school_name=current_user.school_name,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return _serialize(listing)


@router.delete("/listings/{listing_id}", status_code=200)
def delete_listing(
    listing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not your listing")

    listing.status = "removed"
    db.commit()
    return {"message": "Listing removed"}


# --- LISTING CHAT ---
# Reuses the exact same Conversation/ConversationMember/Message models as
# regular DMs (see routers/messages.py) — just tags the conversation with
# listing_id so the chat UI can show a pinned listing card. Everything else
# (get_conversations, get_messages, send_message, the /ws websocket) already
# works unmodified for these threads once created here.

@router.post("/listings/{listing_id}/chat")
def start_listing_chat(
    listing_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't message yourself about your own listing")

    # Reuse an existing conversation about this exact listing between these
    # two people, if one already exists, instead of creating duplicates.
    my_convs = db.query(ConversationMember).filter(
        ConversationMember.user_id == current_user.id
    ).all()
    my_conv_ids = [m.conversation_id for m in my_convs]

    existing = (
        db.query(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .filter(
            Conversation.id.in_(my_conv_ids),
            Conversation.listing_id == listing_id,
            ConversationMember.user_id == listing.seller_id,
        )
        .first()
    )
    if existing:
        return get_conversation_detail(db, existing, current_user.id)

    conv = Conversation(type="dm", listing_id=listing_id)
    db.add(conv)
    db.flush()
    db.add(ConversationMember(conversation_id=conv.id, user_id=current_user.id))
    db.add(ConversationMember(conversation_id=conv.id, user_id=listing.seller_id))
    db.commit()

    return get_conversation_detail(db, conv, current_user.id)