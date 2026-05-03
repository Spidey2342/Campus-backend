from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.user import User
from app.schemas.user import UserRegister
import os
import re
# CryptContext tells passlib to use bcrypt for hashing
# bcrypt is the industry standard — it's slow on purpose
# slow = harder for hackers to brute force stolen passwords
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- PASSWORD HELPERS ---

def hash_password(password: str) -> str:
    # Turns "mypassword123" into "$2b$12$xyz..." (unreadable hash)
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Checks if a plain password matches a stored hash
    # Returns True or False
    return pwd_context.verify(plain_password, hashed_password)

# --- JWT TOKEN HELPERS ---

def create_access_token(user_id: str) -> str:
    # JWT payload — the data baked into the token
    # "sub" is short for "subject" — standard JWT convention
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(
            minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
        )
    }

    # jwt.encode signs the payload with our SECRET_KEY
    # If anyone tampers with the token, the signature breaks
    token = jwt.encode(
        payload,
        os.getenv("SECRET_KEY"),
        algorithm=os.getenv("ALGORITHM")
    )
    return token



def decode_access_token(token: str) -> str:
    # Decodes the token and returns the user_id
    # Raises an error if token is expired or tampered with
    try:
        payload = jwt.decode(
            token,
            os.getenv("SECRET_KEY"),
            algorithms=[os.getenv("ALGORITHM")]
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired"
        )

# --- DATABASE OPERATIONS ---

def get_user_by_email(db: Session, email: str):
    # Session.query() is how we read from the database
    # .filter() is like SQL WHERE
    # .first() returns one result or None
    return db.query(User).filter(User.email == email).first()

def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def create_user(db: Session, user_data: UserRegister):
    # Validate username first — before any database checks
    if not re.match(r'^[a-zA-Z0-9._]+$', user_data.username):
        raise HTTPException(
            status_code=400,
            detail="Username can only contain letters, numbers, dots and underscores. No spaces allowed."
        )

    # Check if email already exists
    if get_user_by_email(db, user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check if username already taken
    if get_user_by_username(db, user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )

    new_user = User(
        full_name=user_data.full_name,
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        school_name=user_data.school_name,
        programme=user_data.programme,
        year_of_study=user_data.year_of_study,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user