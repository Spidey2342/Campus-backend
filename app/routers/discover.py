from fastapi import APIRouter, Depends, Query, Request, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.reel import Reel, Follow

router = APIRouter(prefix="/discover", tags=["Discover"])


limiter = Limiter(key_func=get_remote_address)
@router.get("/search")
@limiter.limit("30/minute")
def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Split query into individual words
        # So "ho tech" matches "Ho Technical University"
        words = q.strip().split()

        # Build a filter that matches ANY word in the query
        # against username, full_name, or school_name
        user_filters = []
        for word in words:
            pattern = f"%{word}%"
            user_filters.append(User.username.ilike(pattern))
            user_filters.append(User.full_name.ilike(pattern))
            user_filters.append(User.school_name.ilike(pattern))

        from sqlalchemy import or_
        users = (
            db.query(User)
            .filter(User.is_active == True, or_(*user_filters))
            .limit(15)
            .all()
        )

        # Search reels by caption or school tag
        reel_filters = []
        for word in words:
            pattern = f"%{word}%"
            reel_filters.append(Reel.caption.ilike(pattern))
            reel_filters.append(Reel.school_tag.ilike(pattern))

        reels = (
            db.query(Reel)
            .filter(Reel.is_active == True, or_(*reel_filters))
            .order_by(desc(Reel.views_count))
            .limit(10)
            .all()
        )

        # Get unique schools from user results
        schools = {}
        for u in users:
            if u.school_name and u.school_name not in schools:
                member_count = db.query(User).filter(
                    User.school_name == u.school_name
                ).count()
                schools[u.school_name] = member_count

        return {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "full_name": u.full_name,
                    "avatar_url": u.avatar_url,
                    "school_name": u.school_name,
                    "is_verified": u.is_verified,
                }
                for u in users
            ],
            "schools": [
                {"school_name": name, "members": count}
                for name, count in schools.items()
            ],
            "reels": [
                {
                    "id": r.id,
                    "caption": r.caption,
                    "thumbnail_url": r.thumbnail_url,
                    "video_url": r.video_url,
                    "views_count": r.views_count,
                    "likes_count": r.likes_count,
                    "school_tag": r.school_tag,
                }
                for r in reels
            ]
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    


@router.get("/schools")
def top_schools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    rows = (
        db.query(
            User.school_name,
            func.count(func.distinct(User.id)).label("members"),
            func.count(Reel.id).label("reels_count"),
            func.coalesce(func.sum(Reel.views_count), 0).label("total_views"),
        )
        .outerjoin(Reel, (Reel.owner_id == User.id) & (Reel.is_active == True))
        .filter(User.school_name != None, User.is_active == True)
        .group_by(User.school_name)
        .order_by(desc("total_views"))
        .limit(10)
        .all()
    )
    return [
        {
            "school_name": r.school_name,
            "members": r.members,
            "reels_count": r.reels_count,
            "total_views": r.total_views,
        }
        for r in rows
    ]



@router.get("/school/{school_name}")
def get_school_detail(
    school_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        from sqlalchemy import or_
        # Fuzzy match — "HTU" matches "Ho Technical University"
        words = school_name.strip().split()
        filters = []
        for word in words:
            filters.append(User.school_name.ilike(f"%{word}%"))

        members = (
            db.query(User)
            .filter(User.is_active == True, or_(*filters))
            .all()
        )

        # Get reels from this school
        member_ids = [m.id for m in members]
        reels = (
            db.query(Reel)
            .filter(
                Reel.owner_id.in_(member_ids),
                Reel.is_active == True
            )
            .order_by(desc(Reel.views_count))
            .limit(12)
            .all()
        )

        return {
            "school_name": school_name,
            "members_count": len(members),
            "members": [
                {
                    "id": m.id,
                    "username": m.username,
                    "full_name": m.full_name,
                    "avatar_url": m.avatar_url,
                    "is_verified": m.is_verified,
                }
                for m in members
            ],
            "reels": [
                {
                    "id": r.id,
                    "thumbnail_url": r.thumbnail_url,
                    "video_url": r.video_url,
                    "views_count": r.views_count,
                    "likes_count": r.likes_count,
                }
                for r in reels
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hashtag/{tag}")
def get_reels_by_hashtag(
    tag: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Search captions for this hashtag
        search_tag = tag if tag.startswith("#") else f"#{tag}"

        reels = (
            db.query(Reel)
            .filter(
                Reel.is_active == True,
                Reel.caption.ilike(f"%{search_tag}%")
            )
            .order_by(desc(Reel.views_count))
            .limit(20)
            .all()
        )

        return [
            {
                "id": r.id,
                "caption": r.caption,
                "thumbnail_url": r.thumbnail_url,
                "video_url": r.video_url,
                "views_count": r.views_count,
                "likes_count": r.likes_count,
                "owner_id": r.owner_id,
            }
            for r in reels
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

    

@router.get("/trending")
def trending_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Finds trending hashtags by scanning reel captions.
    Counts how many reels contain each hashtag.
    """
    # Get all active reel captions
    reels = db.query(Reel.caption).filter(
        Reel.is_active == True,
        Reel.caption != None
    ).all()

    # Count hashtag occurrences
    tag_counts = {}
    for (caption,) in reels:
        if not caption:
            continue
        # Split caption into words and find hashtags
        words = caption.split()
        for word in words:
            if word.startswith("#"):
                tag = word.lower()
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # Sort by count — most used first
    sorted_tags = sorted(
        tag_counts.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        {"tag": tag, "count": count}
        for tag, count in sorted_tags[:10]
    ]


@router.get("/reels/category/{category}")
def reels_by_category(
    category: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Returns reels filtered by category/school tag."""
    if category.lower() == "all":
        reels = (
            db.query(Reel)
            .filter(Reel.is_active == True)
            .order_by(desc(Reel.views_count))
            .limit(20)
            .all()
        )
    else:
        reels = (
            db.query(Reel)
            .filter(
                Reel.is_active == True,
                Reel.school_tag.ilike(f"%{category}%")
            )
            .order_by(desc(Reel.views_count))
            .limit(20)
            .all()
        )

    return [
        {
            "id": r.id,
            "thumbnail_url": r.thumbnail_url,
            "video_url": r.video_url,
            "caption": r.caption,
            "views_count": r.views_count,
            "likes_count": r.likes_count,
        }
        for r in reels
    ]

@router.get("/universities")
async def search_universities(
    q: str,
    current_user=Depends(get_current_user)
):
    """
    Proxy for Hipolabs university search — avoids CORS and service worker
    interception issues when calling from the browser directly.
    """
    import httpx
    if len(q.strip()) < 2:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://universities.hipolabs.com/search",
                params={"name": q.strip(), "limit": 8}
            )
            data = resp.json()
            return [
                {
                    "name": u.get("name"),
                    "country": u.get("country"),
                    "alpha_two_code": u.get("alpha_two_code"),
                    "domains": u.get("domains", []),
                }
                for u in data
                if u.get("name")
            ]
    except Exception:
        return []