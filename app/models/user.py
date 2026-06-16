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