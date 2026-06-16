from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

# BaseModel comes from Pydantic — it validates data automatically
# If someone sends the wrong type, FastAPI rejects it before it hits your code

# --- REQUEST schemas (data coming IN) ---

class UserRegister(BaseModel):
    full_name: str
    username: str
    email: EmailStr        # EmailStr validates it's a real email format
    password: str
    school_name: Optional[str] = None
    programme: Optional[str] = None
    year_of_study: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

# --- RESPONSE schemas (data going OUT) ---
# Notice: no password field — we never send that back

class UserResponse(BaseModel):
    id: str
    full_name: str
    username: str
    email: str
    school_name: Optional[str] = None
    programme: Optional[str] = None
    year_of_study: Optional[str] = None
    avatar_url: Optional[str] = None
    is_verified: bool
    is_admin: bool = False
    is_founding_member: bool = False
    created_at: datetime

    # This tells Pydantic to read data from SQLAlchemy objects
    # Without this it only reads plain dictionaries
    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse