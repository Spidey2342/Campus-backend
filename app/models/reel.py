import random
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey, Float
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
    is_photo  = Column(Boolean, default=False)  # True for image posts
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to the User who posted this
    owner = relationship("User", back_populates="reels")
    likes = relationship("Like", back_populates="reel")
    comments = relationship("Comment", back_populates="reel")
    random_rank = Column(Float, default=random.random, index=True)

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

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # "dm" or "group"
    type = Column(String(10), nullable=False, default="dm")
    name = Column(String(100), nullable=True)  # group name
    avatar_url = Column(String, nullable=True)  # group avatar
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    messages = relationship("Message", back_populates="conversation")
    members = relationship("ConversationMember", back_populates="conversation")


class ConversationMember(Base):
    __tablename__ = "conversation_members"

    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    # Last time this user read the conversation
    last_read_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="members")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    text = Column(Text, nullable=True)
    # "text", "system" (joined/left), "reel" (shared reel)
    message_type = Column(String(20), default="text")
    # If sharing a reel
    reel_id = Column(String, ForeignKey("reels.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Who filed the report
    reporter_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # What's being reported — reel or user (at least one must be set)
    reel_id = Column(String, ForeignKey("reels.id", ondelete="CASCADE"), nullable=True)
    reported_user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    # "spam" | "inappropriate" | "harassment" | "misinformation" | "other"
    reason = Column(String(50), nullable=False)
    details = Column(Text, nullable=True)

    # "pending" | "reviewed" | "actioned" | "dismissed"
    status = Column(String(20), default="pending", nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)