from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Literal
from app.database import get_db
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.reel import Report, Reel
from datetime import datetime, timezone

router = APIRouter(prefix="/moderation", tags=["Moderation"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ReportCreate(BaseModel):
    reel_id: Optional[str] = None
    reported_user_id: Optional[str] = None
    reason: Literal["spam", "inappropriate", "harassment", "misinformation", "other"]
    details: Optional[str] = None

class ReviewAction(BaseModel):
    status: Literal["reviewed", "actioned", "dismissed"]


# ── Helper ───────────────────────────────────────────────────────────────────

def require_admin(current_user: User):
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


# ── User-facing: submit a report ─────────────────────────────────────────────

@router.post("/report", status_code=201)
def submit_report(
    body: ReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not body.reel_id and not body.reported_user_id:
        raise HTTPException(status_code=400, detail="Must report a reel or a user")

    # Prevent duplicate pending reports from the same user on the same content
    existing = db.query(Report).filter(
        Report.reporter_id == current_user.id,
        Report.reel_id == body.reel_id,
        Report.reported_user_id == body.reported_user_id,
        Report.status == "pending"
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="You already reported this")

    report = Report(
        reporter_id=current_user.id,
        reel_id=body.reel_id,
        reported_user_id=body.reported_user_id,
        reason=body.reason,
        details=body.details,
    )
    db.add(report)
    db.commit()
    return {"message": "Report submitted. Our team will review it."}


# ── Admin: list reports ───────────────────────────────────────────────────────

@router.get("/reports")
def list_reports(
    status: Optional[str] = "pending",
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    query = db.query(Report)
    if status and status != "all":
        query = query.filter(Report.status == status)

    reports = query.order_by(Report.created_at.desc()).offset(skip).limit(limit).all()
    if not reports:
        return []

    reporter_ids = {r.reporter_id for r in reports}
    reel_ids = {r.reel_id for r in reports if r.reel_id}
    reported_user_ids = {r.reported_user_id for r in reports if r.reported_user_id}

    users = {u.id: u for u in db.query(User).filter(User.id.in_(reporter_ids | reported_user_ids)).all()}
    reels = {r.id: r for r in db.query(Reel).filter(Reel.id.in_(reel_ids)).all()}

    result = []
    for r in reports:
        reporter = users.get(r.reporter_id)
        reel = reels.get(r.reel_id) if r.reel_id else None
        reported_user = users.get(r.reported_user_id) if r.reported_user_id else None

        result.append({
            "id": r.id,
            "reason": r.reason,
            "details": r.details,
            "status": r.status,
            "created_at": r.created_at,
            "reviewed_at": r.reviewed_at,
            "reporter_username": reporter.username if reporter else None,
            "reel_id": r.reel_id,
            "reel_caption": reel.caption if reel else None,
            "reel_video_url": reel.video_url if reel else None,
            "reported_user_id": r.reported_user_id,
            "reported_username": reported_user.username if reported_user else None,
        })

    return result


# ── Admin: review / action a report ──────────────────────────────────────────

@router.patch("/reports/{report_id}")
def review_report(
    report_id: str,
    body: ReviewAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    require_admin(current_user)

    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.status = body.status
    report.reviewed_at = datetime.now(timezone.utc)

    # If actioned — hide the reel automatically
    if body.status == "actioned" and report.reel_id:
        reel = db.query(Reel).filter(Reel.id == report.reel_id).first()
        if reel:
            reel.is_active = False

    # If actioned on a user — deactivate their account
    if body.status == "actioned" and report.reported_user_id:
        user = db.query(User).filter(User.id == report.reported_user_id).first()
        if user:
            user.is_active = False

    db.commit()
    return {"message": f"Report marked as {body.status}"}