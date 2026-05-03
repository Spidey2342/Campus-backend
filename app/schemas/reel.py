from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# Response shape for a single reel
class ReelResponse(BaseModel):
    id: str
    caption: Optional[str] = None
    video_url: str
    thumbnail_url: Optional[str] = None
    school_tag: Optional[str] = None
    likes_count: int
    comments_count: int
    views_count: int
    created_at: datetime

    # Owner info nested inside the reel response
    # So the feed knows who posted each reel
    owner_id: str
    owner_username: Optional[str] = None
    owner_avatar: Optional[str] = None
    owner_school: Optional[str] = None

    # Whether the current logged-in user liked this reel
    # Useful for showing a filled/empty heart on the frontend
    is_liked: bool = False

    class Config:
        from_attributes = True

class CommentCreate(BaseModel):
    text: str

class CommentResponse(BaseModel):
    id: str
    text: str
    user_id: str
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True