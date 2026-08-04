from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime

CATEGORIES = ["Fashion", "Food", "Tech", "Beauty", "Tutoring", "Events", "Other"]


class SellerSummary(BaseModel):
    id: str
    username: str
    full_name: str
    avatar_url: Optional[str] = None
    is_verified: bool = False

    class Config:
        from_attributes = True


class ListingResponse(BaseModel):
    id: str
    title: str
    description: str
    price: float
    currency: str
    category: str
    photos: List[str] = []
    school_name: Optional[str] = None
    status: str
    is_featured: bool = False
    created_at: datetime
    seller: SellerSummary

    class Config:
        from_attributes = True


class ListingCreate(BaseModel):
    title: str
    description: str
    price: float
    category: str

    @field_validator("title")
    @classmethod
    def title_length(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title is required")
        if len(v) > 80:
            raise ValueError("Title must be 80 characters or fewer")
        return v

    @field_validator("description")
    @classmethod
    def description_length(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description is required")
        if len(v) > 500:
            raise ValueError("Description must be 500 characters or fewer")
        return v

    @field_validator("price")
    @classmethod
    def price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Price must be greater than 0")
        if v > 1_000_000:
            raise ValueError("Price is unreasonably high")
        return v

    @field_validator("category")
    @classmethod
    def category_valid(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(CATEGORIES)}")
        return v


class SellerStatusResponse(BaseModel):
    is_seller: bool
    source: Optional[str] = None  # "trial" | "admin_free" | "paid" | None
    trial_ends_at: Optional[datetime] = None
    days_left: Optional[int] = None