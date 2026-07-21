from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address
from datetime import datetime, timedelta, timezone
import secrets
from app.database import get_db
from app.schemas.user import (
    UserRegister, UserLogin, UserResponse, TokenResponse,
    ForgotPasswordRequest, ResetPasswordRequest
)
from app.services.auth_service import (
    create_user, get_user_by_email,
    verify_password, create_access_token, decode_access_token, hash_password
)
from app.services.email_service import send_password_reset_email
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Each router has its own limiter instance
limiter = Limiter(key_func=get_remote_address)

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user_id = decode_access_token(token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )
    return user


# 5 registration attempts per hour per IP
@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit("5/hour")
def register(
    request: Request,  # required for rate limiting
    user_data: UserRegister,
    db: Session = Depends(get_db)
):
    try:
        user = create_user(db, user_data)
        token = create_access_token(user.id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user
        }
    except HTTPException:
        raise  # re-raise our own HTTP exceptions as-is
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Registration failed. Please try again."
        )


# 10 login attempts per minute per IP — prevents brute force
@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    credentials: UserLogin,
    db: Session = Depends(get_db)
):
    try:
        user = get_user_by_email(db, credentials.email)
        if not user or not verify_password(credentials.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        token = create_access_token(user.id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Login failed. Please try again."
        )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

# 3 forgot-password requests per hour per IP — prevents email bombing
@router.post("/forgot-password")
@limiter.limit("3/hour")
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Always returns the same success message whether or not the email exists.
    This prevents attackers from using this endpoint to discover which
    emails are registered on the platform.
    """
    user = get_user_by_email(db, body.email)

    if user:
        # Generate a secure random token, valid for 30 minutes
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        db.commit()

        send_password_reset_email(user.email, user.username, token)

    return {"message": "If an account exists with that email, a reset link has been sent."}


@router.post("/reset-password")
@limiter.limit("5/hour")
def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.reset_token == body.token).first()

    if not user or not user.reset_token_expires:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    # Compare timezone-aware datetimes
    expires = user.reset_token_expires
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.hashed_password = hash_password(body.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.commit()

    return {"message": "Password reset successfully. You can now log in."}