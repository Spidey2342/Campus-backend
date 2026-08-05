from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc, case, and_
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from slowapi import Limiter
from slowapi.util import get_remote_address
from pydantic import BaseModel
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.reel import Listing, Conversation, ConversationMember, Message, FeatureOrder
from app.schemas.listing import ListingResponse, SellerStatusResponse, CATEGORIES
from app.services.marketplace_service import (
    upload_listing_photo, encode_photo_urls, decode_photo_urls,
    get_seller_status, start_seller_trial,
    MAX_LISTING_PHOTOS, MAX_PHOTO_SIZE_BYTES,
)
from app.services import paystack_service
from app.routers.messages import get_conversation_detail
import os

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])
limiter = Limiter(key_func=get_remote_address)

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://campus-loop-peach.vercel.app")


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
        "is_featured": listing.is_currently_featured(),
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


# --- WHATSAPP CONTACT ---
# Lets a vendor add a WhatsApp number buyers can reach them on directly from
# a listing page, as an alternative to the in-app chat.

class WhatsappUpdateRequest(BaseModel):
    whatsapp_number: Optional[str] = None  # None/"" clears it


@router.get("/whatsapp")
def get_my_whatsapp(current_user: User = Depends(get_current_user)):
    return {"whatsapp_number": current_user.whatsapp_number}


@router.put("/whatsapp")
def set_my_whatsapp(
    body: WhatsappUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    number = (body.whatsapp_number or "").strip()
    if number:
        digits_only = number.replace("+", "").replace(" ", "").replace("-", "")
        if not digits_only.isdigit() or not (9 <= len(digits_only) <= 15):
            raise HTTPException(status_code=400, detail="That doesn't look like a valid phone number")
        current_user.whatsapp_number = number
    else:
        current_user.whatsapp_number = None

    db.commit()
    return {"whatsapp_number": current_user.whatsapp_number}


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

    now = datetime.now(timezone.utc)
    featured_rank = case(
        (and_(Listing.is_featured == True, Listing.featured_until > now), 0),
        else_=1,
    )

    listings = (
        query.order_by(featured_rank, desc(Listing.created_at))
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


class ListingStatusUpdate(BaseModel):
    status: str  # "active" | "sold"


@router.patch("/listings/{listing_id}/status", response_model=ListingResponse)
def update_listing_status(
    listing_id: str,
    body: ListingStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.status not in ("active", "sold"):
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'sold'")

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not your listing")

    listing.status = body.status
    db.commit()
    db.refresh(listing)
    return _serialize(listing)


@router.patch("/listings/{listing_id}", response_model=ListingResponse)
async def edit_listing(
    listing_id: str,
    title: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    category: str = Form(...),
    keep_photo_urls: List[str] = Form(default=[]),  # existing Cloudinary URLs the seller kept
    new_photos: List[UploadFile] = File(default=[]),  # newly added photos
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not your listing")

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

    total_photos = len(keep_photo_urls) + len(new_photos)
    if total_photos > MAX_LISTING_PHOTOS:
        raise HTTPException(status_code=400, detail=f"Max {MAX_LISTING_PHOTOS} photos")

    photo_urls = list(keep_photo_urls)
    for photo in new_photos:
        if not photo.content_type or not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Photos must be images")
        file_bytes = await photo.read()
        if len(file_bytes) > MAX_PHOTO_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="Each photo must be under 8MB")
        photo_urls.append(upload_listing_photo(file_bytes))

    listing.title = title
    listing.description = description
    listing.price = price
    listing.category = category
    listing.photo_urls = encode_photo_urls(photo_urls)
    db.commit()
    db.refresh(listing)
    return _serialize(listing)

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


# --- FEATURED LISTINGS (Paystack) ---
# Pin a listing to the top of the marketplace feed for a paid, fixed number
# of days. Flow: frontend calls /feature/initialize -> gets a Paystack
# hosted checkout URL -> redirects the browser there -> Paystack redirects
# back to the frontend's callback page with ?reference=... -> frontend calls
# /payments/verify/{reference}. The /payments/webhook endpoint is a second,
# independent path to the same result, in case the user closes the tab
# before the frontend gets to call verify.

@router.get("/feature-pricing")
def feature_pricing():
    return {
        "currency": "GHS",
        "options": [
            {"duration_days": days, "amount": amount}
            for days, amount in paystack_service.FEATURE_PRICING.items()
        ],
    }


class FeatureInitRequest(BaseModel):
    duration_days: int


@router.post("/listings/{listing_id}/feature/initialize")
def initialize_feature_payment(
    listing_id: str,
    body: FeatureInitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.seller_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not your listing")
    if listing.status != "active":
        raise HTTPException(status_code=400, detail="Only active listings can be featured")

    amount = paystack_service.FEATURE_PRICING.get(body.duration_days)
    if amount is None:
        raise HTTPException(
            status_code=400,
            detail=f"Duration must be one of: {', '.join(str(d) for d in paystack_service.FEATURE_PRICING)} days",
        )

    order = FeatureOrder(
        listing_id=listing.id,
        seller_id=current_user.id,
        duration_days=body.duration_days,
        amount=amount,
        paystack_reference=f"feat_{listing.id[:8]}_{int(datetime.now(timezone.utc).timestamp())}",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    try:
        paystack_data = paystack_service.initialize_transaction(
            email=current_user.email,
            amount_ghs=amount,
            reference=order.paystack_reference,
            callback_url=f"{FRONTEND_URL}/marketplace/payment/callback",
            metadata={"listing_id": listing.id, "feature_order_id": order.id},
        )
    except Exception as e:
        order.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"Could not start payment: {str(e)}")

    return {
        "authorization_url": paystack_data["authorization_url"],
        "reference": order.paystack_reference,
        "amount": amount,
        "duration_days": body.duration_days,
    }


def _apply_successful_feature_order(db: Session, order: FeatureOrder) -> None:
    """Shared by both the frontend-triggered verify call and the webhook —
    idempotent, safe to call twice for the same order."""
    if order.status == "success":
        return  # already applied — avoid double-extending featured_until

    order.status = "success"
    order.verified_at = datetime.now(timezone.utc)

    listing = db.query(Listing).filter(Listing.id == order.listing_id).first()
    if listing:
        # If it's already featured (e.g. a top-up before the old boost
        # expired), extend from whichever is later — now, or the existing
        # expiry — rather than overwriting a still-active boost.
        base = listing.featured_until if (listing.featured_until and listing.featured_until > datetime.now(timezone.utc)) else datetime.now(timezone.utc)
        listing.is_featured = True
        listing.featured_until = base + timedelta(days=order.duration_days)

    db.commit()


@router.post("/payments/verify/{reference}")
def verify_feature_payment(
    reference: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = db.query(FeatureOrder).filter(FeatureOrder.paystack_reference == reference).first()
    if not order:
        raise HTTPException(status_code=404, detail="Payment not found")
    if order.seller_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not your payment")

    if order.status == "success":
        listing = db.query(Listing).filter(Listing.id == order.listing_id).first()
        return {"status": "success", "listing": _serialize(listing) if listing else None}

    try:
        result = paystack_service.verify_transaction(reference)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not verify payment: {str(e)}")

    if result.get("status") == "success":
        # Cross-check the amount actually charged matches what we expected
        # (Paystack amounts are in pesewas) before trusting it.
        expected_pesewas = int(round(order.amount * 100))
        if result.get("amount") != expected_pesewas:
            order.status = "failed"
            db.commit()
            raise HTTPException(status_code=400, detail="Payment amount mismatch")

        _apply_successful_feature_order(db, order)
        listing = db.query(Listing).filter(Listing.id == order.listing_id).first()
        return {"status": "success", "listing": _serialize(listing) if listing else None}

    order.status = "failed"
    db.commit()
    return {"status": order.status}


@router.post("/payments/webhook")
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Public endpoint (no auth — Paystack calls this, not the app). Protected
    instead by verifying the HMAC signature Paystack sends. This is a
    backup confirmation path: the frontend's own verify call after redirect
    is the primary one, but a user closing the tab mid-payment would
    otherwise leave a successful charge un-applied without this.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not paystack_service.verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    if payload.get("event") == "charge.success":
        reference = payload.get("data", {}).get("reference")
        order = db.query(FeatureOrder).filter(FeatureOrder.paystack_reference == reference).first()
        if order:
            _apply_successful_feature_order(db, order)

    return {"received": True}