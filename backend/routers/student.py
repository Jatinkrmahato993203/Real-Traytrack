"""
routers/student.py — everything a signed-in student does: sign in, accept
the privacy notice, report problems, rate meals, follow up on their own
reports, and export or erase their data.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel, Field

import alert_engine
import auth
import config
import db
import fssai_rules as rules
import photos
from deps import current_student

router = APIRouter(tags=["student"])

RESOLVE_VOTES_NEEDED = 3      # distinct contributing students must agree it's fixed
RESOLVE_MIN_AGE_DAYS = 2      # ...and the alert must have been open this long


def _college_for(email):
    domain = email.split("@")[-1] if "@" in email else ""
    return db.get_college_by_domain(domain) if domain else None


def _me(student):
    college = _college_for(student["email"])
    consent = db.get_consent(student["email"])
    return {
        "email": student["email"],
        "name": student["name"],
        "college": {"id": college["id"], "name": college["name"]} if college else None,
        "consent_needed": not consent or consent["notice_version"] != config.PRIVACY_NOTICE_VERSION,
        "privacy_version": config.PRIVACY_NOTICE_VERSION,
    }


class GoogleLoginRequest(BaseModel):
    credential: str


@router.post("/auth/google")
def google_login(payload: GoogleLoginRequest):
    try:
        info = id_token.verify_oauth2_token(payload.credential, google_requests.Request(), config.GOOGLE_CLIENT_ID)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    if not info.get("email_verified"):
        raise HTTPException(status_code=401, detail="Email not verified by Google")
    student = {"email": info["email"].lower(), "name": info.get("name", "")}
    return {**_me(student), "token": auth.create_student_token(student["email"], student["name"])}


@router.get("/me")
def me(student=Depends(current_student)):
    return _me(student)


class ConsentRequest(BaseModel):
    version: str


@router.post("/me/consent")
def accept_privacy_notice(payload: ConsentRequest, student=Depends(current_student)):
    if payload.version != config.PRIVACY_NOTICE_VERSION:
        raise HTTPException(status_code=400, detail="The privacy notice has changed — please reload and read it again.")
    db.record_consent(student["email"], payload.version)
    return _me(student)


def _require_consent(student):
    consent = db.get_consent(student["email"])
    if not consent or consent["notice_version"] != config.PRIVACY_NOTICE_VERSION:
        raise HTTPException(status_code=428, detail="Please read and accept the privacy notice first.")


@router.post("/complaints")
async def submit_complaint(
    mess_id: int = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    meal: Optional[str] = Form(None),
    dish: Optional[str] = Form(None),
    anonymous: bool = Form(False),
    college_id: Optional[int] = Form(None),  # optional: worked out from the student's email
    photo: Optional[UploadFile] = File(None),
    student=Depends(current_student),
):
    _require_consent(student)
    if category not in rules.COMPLAINT_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown category.")
    if meal and meal not in rules.MEALS:
        raise HTTPException(status_code=400, detail="Unknown meal.")
    if len(description) > 2000:
        raise HTTPException(status_code=400, detail="Description must be under 2,000 characters.")
    college = _college_for(student["email"])
    if not college:
        raise HTTPException(status_code=403, detail="Your college isn't on TrayTrack yet — ask your mess committee to add it.")
    if college_id and college_id != college["id"]:
        raise HTTPException(status_code=403, detail="Your email doesn't match this college's registered domain.")

    problem = alert_engine.check_complaint_allowed(college["id"], mess_id, student["email"])
    if problem:
        mess = db.get_mess_hall(mess_id)
        db.log_activity(
            "complaint_rejected",
            f"Complaint rejected ({'rate limit' if problem == 'rate_limited' else 'wrong college / mess'}) — "
            f"{mess['name'] if mess else f'mess #{mess_id}'}",
            mess_id=mess["id"] if mess else None, college_id=college["id"],
            details={"reason": problem, "category": category, "masked_email": auth.mask_email(student["email"])},
        )
        if problem == "rate_limited":
            raise HTTPException(
                status_code=429,
                detail=f"You've already filed {alert_engine.MAX_COMPLAINTS_PER_STUDENT_PER_MESS_PER_DAY} complaints "
                       "about this mess in the last 24 hours. Please try again tomorrow.",
            )
        raise HTTPException(status_code=403, detail="That mess hall isn't part of your college.")

    photo_path = await photos.save_upload(photo, "complaints") if photo is not None else None
    try:
        complaint_id = db.insert_complaint(
            college["id"], mess_id, student["email"], student["name"] or None, category, description.strip(),
            photo_path, meal, (dish or "").strip()[:120] or None, anonymous,
        )
    except Exception:
        if photo_path:
            Path(photo_path).unlink(missing_ok=True)
        raise
    result = alert_engine.evaluate_complaint(complaint_id, mess_id, category)
    return {"complaint_id": complaint_id, "alert_created": result["alert_id"] is not None, **result}


@router.get("/my-complaints")
def my_complaints(student=Depends(current_student)):
    out = []
    for c in db.get_my_complaints(student["email"]):
        alert = db.get_alert_for_complaint(c["id"], rules.PATTERN_WINDOW_DAYS)
        if alert:
            votes, voted = db.get_resolution_vote_state(alert["id"], student["email"])
            alert = {k: alert[k] for k in ("id", "level", "status", "reason", "resolved", "resolved_at",
                                           "created_at", "last_escalated_at")}
            alert.update(resolve_votes=votes, resolve_votes_needed=RESOLVE_VOTES_NEEDED, you_voted=voted)
        out.append({
            "id": c["id"], "mess_id": c["mess_id"], "mess_name": c["mess_name"], "category": c["category"],
            "description": c["description"], "meal": c["meal"], "dish": c["dish"], "anonymous": bool(c["anonymous"]),
            "status": c["status"], "staff_response": c["staff_response"], "responded_at": c["responded_at"],
            "created_at": c["created_at"], "has_photo": bool(c["photo_path"]), "alert": alert,
        })
    return out


class VoteRequest(BaseModel):
    alert_id: int


@router.post("/my-complaints/resolve")
def vote_alert_fixed(payload: VoteRequest, student=Depends(current_student)):
    """A reporting student's vote that a pattern alert is fixed. The alert
    closes once RESOLVE_VOTES_NEEDED different reporters agree — no single
    account (or anyone wanting to hide it) can close it alone."""
    alert = db.get_alert(payload.alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert["resolved"]:
        raise HTTPException(status_code=400, detail="Already resolved")
    if alert["source"] != "complaint_pattern" or not db.student_contributed_to_alert(
            student["email"], alert, rules.PATTERN_WINDOW_DAYS):
        raise HTTPException(status_code=403, detail="Only students who reported this issue can vote to resolve it.")
    if db.utcnow() - alert["last_escalated_at"] < timedelta(days=RESOLVE_MIN_AGE_DAYS):
        raise HTTPException(status_code=400, detail="Too early — the alert must have been open for 2+ days first")

    votes, is_new = db.add_resolution_vote(alert["id"], student["email"])
    if is_new:
        db.log_activity(
            "resolution_vote",
            f"Student voted alert #{alert['id']} fixed ({votes}/{RESOLVE_VOTES_NEEDED}) — {alert['mess_name']}",
            mess_id=alert["mess_id"], ref_id=alert["id"],
            details={"votes": votes, "votes_needed": RESOLVE_VOTES_NEEDED, "masked_email": auth.mask_email(student["email"])},
        )
    resolved = votes >= RESOLVE_VOTES_NEEDED
    if resolved:
        db.set_status(alert["id"], "resolved", f"Confirmed fixed by {votes} reporting students", None,
                      expected_from=db.OPEN_STATUSES)
    return {"ok": True, "resolved": resolved, "votes": votes, "votes_needed": RESOLVE_VOTES_NEEDED}


# ---------- Meal ratings ----------

class RatingRequest(BaseModel):
    mess_id: int
    meal: str
    stars: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=280)


def _today_local() -> date:
    return datetime.now(timezone.utc).astimezone(ZoneInfo(config.LOCAL_TZ)).date()


@router.post("/ratings")
def rate_meal(payload: RatingRequest, student=Depends(current_student)):
    """One rating per student, hall, meal and day (re-rating overwrites)."""
    _require_consent(student)
    if payload.meal not in rules.MEALS:
        raise HTTPException(status_code=400, detail="Unknown meal.")
    college = _college_for(student["email"])
    mess = db.get_mess_hall(payload.mess_id)
    if not college or not mess or mess["college_id"] != college["id"]:
        raise HTTPException(status_code=403, detail="That mess hall isn't part of your college.")
    db.upsert_rating(college["id"], mess["id"], student["email"], _today_local(), payload.meal, payload.stars,
                     (payload.comment or "").strip() or None)
    return {"ok": True}


@router.get("/my-ratings")
def my_ratings(student=Depends(current_student)):
    return db.my_ratings(student["email"], _today_local() - timedelta(days=14))


# ---------- Privacy: export & erase ----------

@router.get("/me/data")
def export_my_data(student=Depends(current_student)):
    data = db.export_student_data(student["email"])
    return JSONResponse(
        jsonable_encoder({"email": student["email"], "exported_at": db.now_iso(), **data}),
        headers={"Content-Disposition": 'attachment; filename="traytrack-my-data.json"'},
    )


@router.delete("/me/data")
def erase_my_data(student=Depends(current_student)):
    """Removes the student's identity, text and photos from everything they
    submitted. Counts by category/hall/time remain so history stays honest."""
    photos_deleted = db.erase_student(student["email"])
    return {"ok": True, "photos_deleted": photos_deleted}
