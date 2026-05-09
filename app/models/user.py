from sqlalchemy import Column, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base
fcm_token = Column(String, nullable=True)
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

    avatar_url = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Using lazy="dynamic" string references so SQLAlchemy resolves
    # them at runtime after ALL models are loaded — avoids circular import
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

class FCMTokenRequest(BaseModel):
    fcm_token: str

@router.post("/fcm-token")
def save_fcm_token(
    body: FCMTokenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Save the user's FCM device token for push notifications."""
    current_user.fcm_token = body.fcm_token
    db.commit()
    return {"message": "Token saved"}