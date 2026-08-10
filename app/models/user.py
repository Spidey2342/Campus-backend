from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base



class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name = Column(String(100), nullable=False)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    school_name = Column(String(200), nullable=True)
    school_email = Column(String(255), nullable=True)
    programme = Column(String(200), nullable=True)
    year_of_study = Column(String(10), nullable=True)
    bio = Column(Text, nullable=True)
    is_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    is_founding_member = Column(Boolean, default=False)

    # --- Marketplace seller status ---
    # "trial"      — self-serve 7-day free trial, anyone can start it
    # "admin_free" — hand-picked by an admin, free permanently, no trial clock
    # "paid"       — subscribed after their trial ended (payment not wired yet)
    # NULL         — not a seller; can browse/buy but "+" routes to become-seller
    seller_source = Column(String(20), nullable=True)
    seller_trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    # Shown to buyers as a "Chat on WhatsApp" shortcut on listing pages.
    # Stored as entered (digits, optionally with a leading +) — normalized
    # into wa.me link format on read, not on write, so we never lose
    # whatever format the vendor actually typed.
    whatsapp_number = Column(String(20), nullable=True)

    # Drives the one-time post-signup flow (school confirm + follow
    # suggestions). Defaults False for new signups; existing users get
    # backfilled to True in the migration so they're never sent through it.
    has_completed_onboarding = Column(Boolean, default=False)

    # --- Campus Market Pro storefront ---
    # All bundled under one status: being an active seller (trial, paid,
    # or admin-comped) IS "Pro" — verified badge, storefront, analytics.
    # No separate tier to track; see is_pro_seller below.
    store_name = Column(String(100), nullable=True)      # falls back to full_name if unset
    store_banner_url = Column(String(500), nullable=True)
    store_bio = Column(Text, nullable=True)
    store_hours = Column(String(200), nullable=True)      # free text, e.g. "Mon-Fri 9am-6pm"

    @property
    def is_pro_seller(self) -> bool:
        """True while this user's seller status (trial/paid/admin_free) is
        currently active — this IS Campus Market Pro status, since the
        badge/storefront/analytics bundle isn't sold separately from
        being a seller at all. Import is deferred to avoid a circular
        import (marketplace_service imports User)."""
        from app.services.marketplace_service import get_seller_status
        return get_seller_status(self)["is_seller"]

    avatar_url = Column(String, nullable=True)
    fcm_token = Column(String, nullable=True)  # 👈 just the column, no route
    reset_token = Column(String, nullable=True)
    reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    reels = relationship("Reel", back_populates="owner")
    followers = relationship(
        "Follow",
        primaryjoin="Follow.following_id == User.id",
        back_populates="following",
        lazy="select"
    )
    following = relationship(
        "Follow",
        primaryjoin="Follow.follower_id == User.id",
        back_populates="follower",
        lazy="select"
    )