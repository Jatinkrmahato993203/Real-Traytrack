"""
main.py — TrayTrack API (FastAPI)

Covers every screen that used to live in the Streamlit app:
  - Google Sign-In                (student identity)
  - Submit Complaint (+ photo)    (public-facing, requires sign-in)
  - My Reports                   (student's own history + resolve button)
  - Public Dashboard              (open, no auth)
  - History / Trends             (open, no auth)
  - Inspector Entry               (password-protected)
  - Admin Panel                   (password-protected)
"""

import os
import io
import re
import json
import uuid
import asyncio
import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError

import database as db
import alert_engine
import fssai_rules as rules
import auth

load_dotenv()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

# Every activity_log write is also mirrored to the console and to a
# rotating file, so there's a plain-text backend log even without the DB.
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_DIR / "traytrack.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
    ],
)

UPLOAD_DIR = Path(__file__).parent / "uploads" / "complaints"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="TrayTrack API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

# First start with staff accounts: seed one all-colleges admin from the old
# shared password, so an existing setup can still log in — then create real
# per-person accounts and change this one's password in Admin Panel → Staff.
if db.count_staff() == 0:
    db.create_staff("Administrator", auth.ADMIN_EMAIL, "admin", None, auth.hash_password(auth.ADMIN_PASSWORD))
    logging.getLogger("traytrack").warning(
        "Created bootstrap admin account %s (password = MESS_ADMIN_PASSWORD). "
        "Change it in Admin Panel -> Staff.", auth.ADMIN_EMAIL,
    )


def _escalation_loop():
    """Runs the 7-day auto-escalation check every hour in the background,
    so alerts don't sit stale just because nobody happens to load a page."""
    while True:
        try:
            count = alert_engine.escalate_stale_alerts(days=7)
            if count:
                print(f"[escalation] Auto-escalated {count} stale alert(s).")
        except Exception as e:
            print(f"[escalation] Check failed: {e}")
        time.sleep(60 * 60)  # 1 hour


threading.Thread(target=_escalation_loop, daemon=True).start()


STAFF_ROLES = ("admin", "inspector")


def _bearer(authorization: Optional[str]):
    if authorization and authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return None


def require_staff(authorization: Optional[str], roles=STAFF_ROLES) -> dict:
    """Returns the signed-in staff account. Role, college scope and the
    active flag come from the database on every call, so a deactivated or
    re-roled account loses access immediately, not when its token expires."""
    token = _bearer(authorization)
    staff_id = auth.verify_staff_token(token) if token else None
    staff = db.get_staff(staff_id) if staff_id else None
    if not staff or not staff["active"]:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please log in again.")
    if staff["role"] not in roles:
        raise HTTPException(status_code=403, detail="This needs an admin account.")
    return staff


def require_admin(authorization: Optional[str]) -> dict:
    return require_staff(authorization, roles=("admin",))


def require_global_admin(authorization: Optional[str]) -> dict:
    staff = require_admin(authorization)
    if staff["college_id"]:
        raise HTTPException(status_code=403, detail="Only an all-colleges admin can do this.")
    return staff


def scoped_college(staff: dict, college_id: Optional[int]) -> Optional[int]:
    """The college a request may see. College-scoped staff are pinned to
    their own college; asking for another one is refused, not ignored."""
    if staff["college_id"]:
        if college_id and int(college_id) != staff["college_id"]:
            raise HTTPException(status_code=403, detail="Your account is limited to another college.")
        return staff["college_id"]
    return college_id


def require_mess_in_scope(staff: dict, mess_id: int) -> dict:
    mess = db.get_mess_hall(mess_id)
    if not mess:
        raise HTTPException(status_code=404, detail="Mess hall not found.")
    scoped_college(staff, mess["college_id"])
    return mess


def require_user(authorization: Optional[str] = Header(None)) -> str:
    """Returns the student's Google-verified email, read from the signed
    session token issued at /auth/google — never from a client-supplied
    email, which anyone could forge."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):]
    email = auth.verify_student_token(token) if token else None
    if not email:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please sign in again.")
    return email


# ==================== AUTH ====================

class GoogleLoginRequest(BaseModel):
    credential: str


@app.post("/auth/google")
def google_login(payload: GoogleLoginRequest):
    try:
        info = id_token.verify_oauth2_token(
            payload.credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    if not info.get("email_verified"):
        raise HTTPException(status_code=401, detail="Email not verified by Google")

    return {
        "email": info["email"],
        "name": info.get("name", ""),
        "hd": info.get("hd", ""),
        "token": auth.create_student_token(info["email"]),
    }


class StaffLoginRequest(BaseModel):
    email: str
    password: str


def _staff_view(staff: dict) -> dict:
    return {k: staff[k] for k in ("id", "name", "email", "role", "college_id", "college_name", "active")}


@app.post("/staff/login")
def staff_login(payload: StaffLoginRequest, request: Request):
    """Admins and inspectors each log in with their own email + password."""
    client_ip = request.client.host if request.client else "unknown"

    locked_seconds = auth.check_lockout(client_ip)
    if locked_seconds is not None:
        hours = locked_seconds // 3600
        minutes = (locked_seconds % 3600) // 60
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {hours}h {minutes}m.",
        )

    account = db.get_staff_login(payload.email)
    # Always run one password check, even for unknown emails, so the
    # response time doesn't reveal which emails have accounts.
    password_ok = auth.verify_password(
        payload.password, account["password_hash"] if account else auth.DUMMY_PASSWORD_HASH
    )
    if not account or not password_ok or not account["active"]:
        auth.record_failed_attempt(client_ip)
        remaining = auth.MAX_ATTEMPTS - auth._attempts.get(client_ip, {}).get("count", 0)
        if remaining > 0:
            raise HTTPException(status_code=401, detail=f"Incorrect email or password. {remaining} attempt(s) left.")
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 6 hours.")

    auth.reset_attempts(client_ip)
    staff = db.get_staff(account["id"])
    return {"token": auth.create_staff_token(staff["id"]), "staff": _staff_view(staff)}


@app.get("/staff/me")
def staff_me(authorization: str = Header(None)):
    return _staff_view(require_staff(authorization))


# ==================== COLLEGES / MESS HALLS (public reference data) ====================

@app.get("/colleges")
def list_colleges():
    return db.list_colleges()


@app.get("/mess-halls")
def list_mess_halls(college_id: int):
    return db.list_mess_halls(college_id)


@app.get("/categories")
def list_categories():
    return list(rules.COMPLAINT_CATEGORIES.keys())


@app.get("/checklist")
def list_checklist():
    return rules.CHECKLIST


# ==================== COMPLAINTS ====================

MAX_PHOTO_SIZE_BYTES = 4 * 1024 * 1024  # 4 MB
ALLOWED_PHOTO_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PHOTO_PIXELS = 40_000_000   # refuse decompression bombs before decoding
MAX_PHOTO_SIDE = 4000           # larger photos are scaled down to this
PHOTO_ERROR = "Photo must be a JPEG, PNG, or WEBP image."


def _reencode_photo(contents: bytes) -> bytes:
    """Returns the upload re-encoded as a fresh JPEG. The client's
    content-type and filename are never trusted: the bytes must decode as a
    real image, and re-encoding means whatever we store is pixels only — no
    smuggled HTML/SVG, and no EXIF (so no GPS location of the student)."""
    try:
        with Image.open(io.BytesIO(contents)) as probe:
            if probe.format not in ALLOWED_PHOTO_FORMATS:
                raise HTTPException(status_code=400, detail=PHOTO_ERROR)
            width, height = probe.size
            if width * height > MAX_PHOTO_PIXELS:
                raise HTTPException(status_code=400, detail="Photo resolution is too large.")
            probe.verify()
        # verify() leaves the image unusable, so decode again for real.
        with Image.open(io.BytesIO(contents)) as img:
            # Apply the EXIF rotation before EXIF is dropped, or phone
            # photos would come out sideways.
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE))
            rgba = img.convert("RGBA")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail=PHOTO_ERROR)

    # Paste onto a brand-new image so no metadata from the upload can carry
    # over; transparent areas become white instead of black.
    clean = Image.new("RGB", rgba.size, (255, 255, 255))
    clean.paste(rgba, mask=rgba.getchannel("A"))
    out = io.BytesIO()
    clean.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


@app.post("/complaints")
async def submit_complaint(
    college_id: int = Form(...),
    mess_id: int = Form(...),
    student_name: str = Form(...),
    category: str = Form(...),
    description: str = Form(""),
    photo: Optional[UploadFile] = File(None),
    authorization: Optional[str] = Header(None),
):
    student_email = require_user(authorization)

    photo_path = None
    if photo is not None:
        contents = await photo.read(MAX_PHOTO_SIZE_BYTES + 1)
        if len(contents) > MAX_PHOTO_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="Photo must be 4MB or smaller.")

        jpeg = await asyncio.to_thread(_reencode_photo, contents)
        # The extension is always ours — never taken from the upload.
        dest = UPLOAD_DIR / f"{uuid.uuid4().hex}.jpg"
        with open(dest, "wb") as f:
            f.write(jpeg)
        photo_path = str(dest)

    alert_id, level, reason, category_count, mess_count = alert_engine.create_complaint_alert(
        college_id, mess_id, student_email, student_name, category, description, photo_path
    )

    if reason in ("unauthorized", "rate_limited"):
        if photo_path:
            Path(photo_path).unlink(missing_ok=True)
        mess = db.get_mess_hall(mess_id)
        db.log_activity(
            "complaint_rejected",
            f"Complaint rejected ({'rate limit' if reason == 'rate_limited' else 'domain/college mismatch'}) — "
            f"{mess['name'] if mess else f'mess #{mess_id}'}",
            mess_id=mess_id if mess else None, college_id=college_id if db.get_college(college_id) else None,
            details={"reason": reason, "category": category, "masked_email": auth.mask_email(student_email)},
        )
    if reason == "unauthorized":
        raise HTTPException(status_code=403, detail="Your email doesn't match this college's registered domain.")
    if reason == "rate_limited":
        raise HTTPException(
            status_code=429,
            detail=f"You've already filed {alert_engine.MAX_COMPLAINTS_PER_STUDENT_PER_MESS_PER_DAY} "
                   f"complaints about this mess in the last 24 hours. Please try again tomorrow.",
        )

    return {
        "alert_created": alert_id is not None,
        "level": level,
        "reason": reason,
        "category_count": category_count,
        "mess_count": mess_count,
        "category_threshold": alert_engine.CATEGORY_THRESHOLD,
        "mess_threshold": alert_engine.MESS_THRESHOLD,
        "window_days": alert_engine.PATTERN_WINDOW_DAYS,
    }


# ==================== MY REPORTS ====================

RESOLVE_VOTES_NEEDED = 3      # distinct contributing students must agree it's fixed
RESOLVE_MIN_AGE_DAYS = 2      # ...and the alert must have been escalating this long


@app.get("/my-complaints")
def my_complaints(authorization: Optional[str] = Header(None)):
    email = require_user(authorization)
    complaints = db.get_my_complaints(email)
    result = []
    for c in complaints:
        alert = db.get_alert_for_complaint(c["id"], alert_engine.PATTERN_WINDOW_DAYS)
        if alert:
            votes, voted = db.get_resolution_vote_state(alert["id"], email)
            alert = {**alert, "resolve_votes": votes, "resolve_votes_needed": RESOLVE_VOTES_NEEDED, "you_voted": voted}
        result.append({**c, "alert": alert})
    return result


class ResolveByStudentRequest(BaseModel):
    alert_id: int


@app.post("/my-complaints/resolve")
def resolve_my_alert(payload: ResolveByStudentRequest, authorization: Optional[str] = Header(None)):
    """Records the signed-in student's vote that an alert is fixed. Only
    students who actually reported the problem can vote, and the alert
    only closes once RESOLVE_VOTES_NEEDED different reporters agree — so no
    single account (or anyone with an incentive to hide the alert) can
    close it alone."""
    email = require_user(authorization)

    alerts = db.get_alerts()
    alert = next((a for a in alerts if a["id"] == payload.alert_id), None)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert["resolved"]:
        raise HTTPException(status_code=400, detail="Already resolved")
    if alert["source"] != "complaint_pattern" or not db.student_contributed_to_alert(
        email, alert, alert_engine.PATTERN_WINDOW_DAYS
    ):
        raise HTTPException(status_code=403, detail="Only students who reported this issue can vote to resolve it.")

    last_escalated = alert["last_escalated_at"]
    if isinstance(last_escalated, str):
        last_escalated = datetime.strptime(last_escalated, "%Y-%m-%d %H:%M:%S")
    if datetime.utcnow() - last_escalated < timedelta(days=RESOLVE_MIN_AGE_DAYS):
        raise HTTPException(status_code=400, detail="Too early — must be escalating for 2+ days first")

    votes, is_new_vote = db.add_resolution_vote(payload.alert_id, email)
    if is_new_vote:
        db.log_activity(
        "resolution_vote",
            f"Student voted alert #{payload.alert_id} fixed ({votes}/{RESOLVE_VOTES_NEEDED}) — {alert['mess_name']}",
            mess_id=alert["mess_id"], ref_id=payload.alert_id,
            details={"votes": votes, "votes_needed": RESOLVE_VOTES_NEEDED, "masked_email": auth.mask_email(email)},
        )
    resolved = votes >= RESOLVE_VOTES_NEEDED
    if resolved:
        db.mark_alert_resolved_by_students(payload.alert_id, votes)
    return {"ok": True, "resolved": resolved, "votes": votes, "votes_needed": RESOLVE_VOTES_NEEDED}


# ==================== PUBLIC DASHBOARD ====================

@app.get("/dashboard-status")
def dashboard_status(college_id: int):
    mess_halls = db.list_mess_halls(college_id)
    result = []
    for mess in mess_halls:
        open_alerts = db.get_alerts(mess_id=mess["id"], resolved=False)
        if not open_alerts:
            result.append({"mess": mess, "status": "clear", "open_count": 0, "worst_level": None})
        else:
            worst = max(open_alerts, key=lambda a: rules.LEVELS.index(a["level"]))
            result.append({
                "mess": mess,
                "status": "alert",
                "open_count": len(open_alerts),
                "worst_level": worst["level"],
                "authority": rules.get_authority(worst["level"]),
            })
    return result


@app.get("/alerts")
def open_alerts(college_id: Optional[int] = None, mess_id: Optional[int] = None):
    return db.get_alerts(college_id=college_id, mess_id=mess_id, resolved=False)


@app.get("/analytics")
def analytics(college_id: int):
    """Auto-updating chart data for the public dashboard — category counts
    only. Complaint text is free-form and can name or identify people, so
    it stays behind staff login (Admin Panel → All complaints)."""
    now = datetime.utcnow()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    month_start = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    weekly_complaints = db.get_complaints_since(college_id, week_start)
    monthly_complaints = db.get_complaints_since(college_id, month_start)

    def category_counts(complaints):
        counts = {}
        for c in complaints:
            counts[c["category"]] = counts.get(c["category"], 0) + 1
        return [{"category": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]

    return {
        "weekly_chart": category_counts(weekly_complaints),
        "weekly_total": len(weekly_complaints),
        "monthly_chart": category_counts(monthly_complaints),
        "monthly_total": len(monthly_complaints),
    }


# ==================== HISTORY / TRENDS ====================

@app.get("/trends")
def trends(college_id: Optional[int] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
    return db.get_alerts_with_details(college_id=college_id, start_date=start_date, end_date=end_date)


# ==================== INSPECTOR ====================

class InspectionRequest(BaseModel):
    mess_id: int
    responses: dict  # {checklist_item_id: bool}


@app.post("/inspections")
def submit_inspection(payload: InspectionRequest, authorization: str = Header(None)):
    """Recorded under the signed-in inspector's (or admin's) own account —
    the name can't be typed in, so every inspection is attributable."""
    staff = require_staff(authorization)
    require_mess_in_scope(staff, payload.mess_id)
    alert_id, level, score, reason = alert_engine.create_inspection_alert(
        payload.mess_id, staff["name"], payload.responses, inspector_id=staff["id"]
    )
    return {"alert_id": alert_id, "level": level, "score": score, "reason": reason}


# ==================== ADMIN ====================

class AddCollegeRequest(BaseModel):
    name: str
    email_domain: str
    mess_head_email: Optional[str] = None
    principal_email: Optional[str] = None
    fssai_contact_email: Optional[str] = None


@app.post("/admin/colleges")
def admin_add_college(payload: AddCollegeRequest, authorization: str = Header(None)):
    staff = require_global_admin(authorization)
    try:
        db.add_college(
            payload.name, payload.email_domain,
            payload.mess_head_email, payload.principal_email, payload.fssai_contact_email,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't add college — it may already exist. ({e})")
    db.log_activity("admin_college_added", f"{staff['name']} added college {payload.name} (@{payload.email_domain})",
                    details={"actor": staff["name"]})
    return {"ok": True}


class UpdateContactsRequest(BaseModel):
    mess_head_email: Optional[str] = None
    principal_email: Optional[str] = None
    fssai_contact_email: Optional[str] = None


@app.patch("/admin/colleges/{college_id}/contacts")
def admin_update_college_contacts(college_id: int, payload: UpdateContactsRequest, authorization: str = Header(None)):
    staff = require_admin(authorization)
    scoped_college(staff, college_id)
    db.update_college_contacts(
        college_id, payload.mess_head_email, payload.principal_email, payload.fssai_contact_email
    )
    college = db.get_college(college_id)
    db.log_activity(
        "admin_contacts_updated",
        f"{staff['name']} updated alert contacts — {college['name'] if college else f'college #{college_id}'}",
        college_id=college_id if college else None, details={"actor": staff["name"]},
    )
    return {"ok": True}


class AddMessHallRequest(BaseModel):
    college_id: int
    name: str


@app.post("/admin/mess-halls")
def admin_add_mess_hall(payload: AddMessHallRequest, authorization: str = Header(None)):
    staff = require_admin(authorization)
    scoped_college(staff, payload.college_id)
    try:
        db.add_mess_hall(payload.college_id, payload.name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Couldn't add mess hall — it may already exist. ({e})")
    db.log_activity("admin_mess_added", f"{staff['name']} added mess hall {payload.name.strip()}",
                    college_id=payload.college_id, details={"actor": staff["name"]})
    return {"ok": True}


@app.delete("/admin/mess-halls/{mess_id}")
def admin_delete_mess_hall(mess_id: int, authorization: str = Header(None)):
    staff = require_admin(authorization)
    mess = require_mess_in_scope(staff, mess_id)
    try:
        db.delete_mess_hall(mess_id)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail="Couldn't delete — this mess hall still has complaints, inspections, or alerts linked to it.",
        )
    db.log_activity("admin_mess_deleted", f"{staff['name']} deleted mess hall {mess['name']}",
                    college_id=mess["college_id"], details={"actor": staff["name"]})
    return {"ok": True}


@app.delete("/admin/colleges/{college_id}")
def admin_delete_college(college_id: int, authorization: str = Header(None)):
    staff = require_global_admin(authorization)
    college = db.get_college(college_id)
    try:
        db.delete_college(college_id)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail="Couldn't delete — remove all of this college's mess halls first.",
        )
    if college:
        db.log_activity("admin_college_deleted", f"{staff['name']} deleted college {college['name']}",
                        details={"actor": staff["name"]})
    return {"ok": True}


@app.get("/admin/alerts")
def admin_list_alerts(resolved: Optional[bool] = False, authorization: str = Header(None)):
    staff = require_admin(authorization)
    alerts = db.get_alerts(resolved=resolved, college_id=scoped_college(staff, None))
    result = []
    for a in alerts:
        detail = dict(a)
        if a["source"] in ("complaint", "complaint_pattern") and a["source_id"]:
            complaint = db.get_complaint_private(a["source_id"])
            if complaint:
                detail["complaint"] = {
                    "masked_email": auth.mask_email(complaint["student_email"]),
                    "category": complaint["category"],
                    "description": complaint["description"],
                    "photo_url": db.complaint_photo_url(complaint.get("photo_path")),
                }
        result.append(detail)
    return result


@app.get("/admin/complaints")
def admin_list_complaints(
    college_id: Optional[int] = None,
    mess_id: Optional[int] = None,
    days: Optional[int] = 30,
    authorization: str = Header(None),
):
    """Every individual complaint, including ones that haven't (yet) formed
    an alert pattern — so admins and inspectors can see what students are
    reporting long before a threshold is reached. Emails are masked.
    Open to inspectors too (they see complaints for the hall they inspect)."""
    staff = require_staff(authorization)
    college_id = scoped_college(staff, college_id)
    if mess_id:
        require_mess_in_scope(staff, mess_id)
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days else None
    complaints = db.get_complaints_for_review(college_id=college_id, mess_id=mess_id, since=since)
    return [
        {
            "id": c["id"],
            "college_name": c["college_name"],
            "mess_id": c["mess_id"],
            "mess_name": c["mess_name"],
            "category": c["category"],
            "description": c["description"],
            "masked_email": auth.mask_email(c["student_email"]),
            "created_at": c["created_at"],
            "photo_url": db.complaint_photo_url(c.get("photo_path")),
        }
        for c in complaints
    ]


# Only names we generate (uuid hex + extension) are accepted, so the path
# can't escape UPLOAD_DIR. Older uploads may still be .png/.webp.
PHOTO_FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|webp)$")
PHOTO_MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


@app.get("/admin/complaint-photos/{filename}")
def admin_complaint_photo(filename: str, authorization: str = Header(None)):
    """Complaint photos for signed-in staff only, and only for complaints in
    their own college. The content type comes from the server, and nosniff
    stops a browser from ever treating the bytes as HTML or script."""
    staff = require_staff(authorization)
    match = PHOTO_FILENAME_RE.match(filename)
    complaint = db.get_complaint_by_photo(filename) if match else None
    path = UPLOAD_DIR / filename
    if not complaint or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found.")
    scoped_college(staff, complaint["college_id"])
    return FileResponse(
        path,
        media_type=PHOTO_MEDIA_TYPES[match.group(1)],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


class ResolveAlertRequest(BaseModel):
    notes: str = ""


@app.post("/admin/alerts/{alert_id}/resolve")
def admin_resolve_alert(alert_id: int, payload: ResolveAlertRequest, authorization: str = Header(None)):
    staff = require_admin(authorization)
    alert = db.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    scoped_college(staff, alert["college_id"])
    if not db.resolve_alert(alert_id, payload.notes, staff=staff):
        raise HTTPException(status_code=400, detail="Alert not found or already resolved.")
    return {"ok": True}


# ==================== ACTIVITY LOG (admin, live) ====================

ACTIVITY_POLL_SECONDS = 1
# Inspectors get the complaint + inspection part of the feed (so their
# complaint list can update live), not alert handling or admin changes.
INSPECTOR_ACTIVITY_PREFIXES = ("complaint_submitted", "inspection_")


def _activity_scope(staff: dict, college_id: Optional[int]):
    prefixes = INSPECTOR_ACTIVITY_PREFIXES if staff["role"] == "inspector" else None
    return scoped_college(staff, college_id), prefixes


@app.get("/admin/activity")
def admin_activity(
    college_id: Optional[int] = None,
    event_type: Optional[str] = None,
    before_id: Optional[int] = None,
    limit: int = 100,
    authorization: str = Header(None),
):
    """The activity history, newest first — page back with before_id."""
    staff = require_staff(authorization)
    college_id, prefixes = _activity_scope(staff, college_id)
    return db.get_activity(
        before_id=before_id, college_id=college_id, event_type=event_type,
        limit=max(1, min(limit, 500)), only_prefixes=prefixes,
    )


@app.get("/admin/activity/stream")
async def admin_activity_stream(
    request: Request,
    after_id: int = 0,
    college_id: Optional[int] = None,
    authorization: str = Header(None),
):
    """Server-Sent Events: pushes every new activity row (id > after_id) the
    moment it's committed, from any worker or process, because it reads the
    shared activity_log table rather than in-memory state. Auth is the
    normal Bearer header (the frontend streams via fetch, not EventSource,
    so the token never goes in the URL)."""
    staff = require_staff(authorization)
    college_id, prefixes = _activity_scope(staff, college_id)

    async def events():
        last_id = after_id
        quiet_ticks = 0
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            # Re-check every tick: an expired token or a deactivated
            # account stops the stream straight away.
            try:
                await asyncio.to_thread(require_staff, authorization)
            except HTTPException:
                yield "event: expired\ndata: {}\n\n"
                return
            rows = await asyncio.to_thread(
                db.get_activity, after_id=last_id, college_id=college_id, limit=200, only_prefixes=prefixes
            )
            for row in rows:
                last_id = row["id"]
                yield f"id: {row['id']}\nevent: activity\ndata: {json.dumps(row, default=str)}\n\n"
            quiet_ticks = 0 if rows else quiet_ticks + 1
            if quiet_ticks >= 15:
                yield ": keep-alive\n\n"
                quiet_ticks = 0
            await asyncio.sleep(ACTIVITY_POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ==================== STAFF ACCOUNTS (admin) ====================

class CreateStaffRequest(BaseModel):
    name: str
    email: str
    role: str
    college_id: Optional[int] = None
    password: str


class UpdateStaffRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None


def _check_password(password: str):
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters.")


@app.get("/admin/staff")
def admin_list_staff(authorization: str = Header(None)):
    staff = require_admin(authorization)
    return db.list_staff(college_id=staff["college_id"])


@app.post("/admin/staff")
def admin_create_staff(payload: CreateStaffRequest, authorization: str = Header(None)):
    """College-scoped admins can only create accounts for their own college;
    only an all-colleges admin can create another all-colleges account."""
    staff = require_admin(authorization)
    if payload.role not in STAFF_ROLES:
        raise HTTPException(status_code=400, detail="Role must be admin or inspector.")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    _check_password(payload.password)
    college_id = payload.college_id
    if staff["college_id"]:
        college_id = scoped_college(staff, college_id) if college_id else staff["college_id"]
    if college_id and not db.get_college(college_id):
        raise HTTPException(status_code=400, detail="College not found.")
    if db.get_staff_login(email):
        raise HTTPException(status_code=400, detail="An account with that email already exists.")
    new_id = db.create_staff(payload.name, email, payload.role, college_id, auth.hash_password(payload.password))
    db.log_activity(
        "admin_staff_added", f"{staff['name']} added {payload.role} account {payload.name.strip()}",
        college_id=college_id, details={"actor": staff["name"], "role": payload.role, "email": email},
    )
    return db.get_staff(new_id)


@app.patch("/admin/staff/{staff_id}")
def admin_update_staff(staff_id: int, payload: UpdateStaffRequest, authorization: str = Header(None)):
    staff = require_admin(authorization)
    target = db.get_staff(staff_id)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found.")
    if staff["college_id"] and target["college_id"] != staff["college_id"]:
        raise HTTPException(status_code=403, detail="You can only manage your own college's staff.")
    if payload.role is not None and payload.role not in STAFF_ROLES:
        raise HTTPException(status_code=400, detail="Role must be admin or inspector.")
    if payload.password is not None:
        _check_password(payload.password)
    if target["id"] == staff["id"] and (payload.active is False or payload.role == "inspector"):
        raise HTTPException(status_code=400, detail="You can't deactivate or demote your own account.")
    removes_global_admin = (
        target["role"] == "admin" and not target["college_id"] and target["active"]
        and (payload.active is False or payload.role == "inspector")
    )
    if removes_global_admin and db.count_active_global_admins() <= 1:
        raise HTTPException(status_code=400, detail="That's the last active all-colleges admin — add another first.")

    db.update_staff(
        staff_id, name=payload.name, role=payload.role, active=payload.active,
        password_hash=auth.hash_password(payload.password) if payload.password else None,
    )
    changes = [k for k in ("name", "role", "active") if getattr(payload, k) is not None]
    if payload.password:
        changes.append("password")
    db.log_activity(
        "admin_staff_updated", f"{staff['name']} updated {target['name']}'s account ({', '.join(changes) or 'no changes'})",
        college_id=target["college_id"],
        details={"actor": staff["name"], "changes": changes,
                 **({"active": payload.active} if payload.active is not None else {}),
                 **({"role": payload.role} if payload.role else {})},
    )
    return db.get_staff(staff_id)
