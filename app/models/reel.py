from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base

class Reel(Base):
    __tablename__ = "reels"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # ForeignKey links this reel to the user who posted it
    # "users.id" means: look in the users table, match the id column
    # ondelete="CASCADE" means: if user is deleted, delete their reels too
    owner_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # The actual video lives on Cloudinary
    # We just store the URL here
    video_url = Column(String, nullable=False)
    thumbnail_url = Column(String, nullable=True)

    # Content
    caption = Column(Text, nullable=True)
    school_tag = Column(String(200), nullable=True)  # which school this reel rep's

    # Counters — we store these for fast reads
    # Instead of counting likes every time, we keep a running total
    likes_count = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    views_count = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to the User who posted this
    owner = relationship("User", back_populates="reels")
    likes = relationship("Like", back_populates="reel")
    comments = relationship("Comment", back_populates="reel")

class Follow(Base):
    __tablename__ = "follows"

    follower_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    following_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    follower = relationship("User", foreign_keys=[follower_id], back_populates="following")
    following = relationship("User", foreign_keys=[following_id], back_populates="followers")

class Like(Base):
    __tablename__ = "likes"

    # Again composite key — one user can only like a reel once
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    reel_id = Column(String, ForeignKey("reels.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    reel = relationship("Reel", back_populates="likes")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reel_id = Column(String, ForeignKey("reels.id", ondelete="CASCADE"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    reel = relationship("Reel", back_populates="comments")
    
class VideoView(Base):
    __tablename__ = "video_views"

    # Composite primary key — one user can only count once per reel
    # Same pattern as Like — prevents duplicate counting
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    reel_id = Column(String, ForeignKey("reels.id", ondelete="CASCADE"), primary_key=True)
    viewed_at = Column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Who receives the notification
    recipient_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Who triggered it
    sender_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Type: "like", "comment", "follow"
    type = Column(String(50), nullable=False)
    
    # Optional — which reel triggered it
    reel_id = Column(String, ForeignKey("reels.id", ondelete="CASCADE"), nullable=True)
    
    # The message shown to the user
    message = Column(String, nullable=False)
    
    # Has the user seen this notification
    is_read = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())