"""
deps.py — who is making this request, and what they may touch.

Every staff check re-reads the account from the database, so deactivating
someone or changing their role applies immediately. Scope rules:
  * college_id NULL on the account = all colleges, else that college only;
  * mess_id on the account = that one mess hall only (mess heads);
  * asking for something outside your scope is refused (403), never silently
    widened or narrowed.
"""

from typing import Optional

from fastapi import HTTPException, Request

import auth
import config
import db
from permissions import can


def bearer(authorization: Optional[str]):
    if authorization and authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return None


def session_token(request: Request, cookie_name: str):
    """A Bearer header wins (API clients, tests); browsers use the cookie."""
    return bearer(request.headers.get("authorization")) or request.cookies.get(cookie_name)


# ---------- Students ----------

def current_student(request: Request) -> dict:
    """{"email", "name", "token"} from the server-side session created at
    /auth/google — never a client-supplied email, which anyone could forge."""
    token = session_token(request, auth.STUDENT_COOKIE)
    session = auth.student_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please sign in again.")
    return {"email": session["student_email"], "name": session["student_name"] or "", "token": token}


# ---------- Staff ----------

def staff_for_token(token) -> dict:
    session = auth.staff_session(token)
    staff = db.get_staff(session["staff_id"]) if session else None
    if not staff or not staff["active"]:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please log in again.")
    staff["session_token"] = token
    return staff


def _allowed_before_two_factor(path):
    """What someone who must use 2FA but hasn't set it up may still reach:
    their own account pages and sign-out. Exact matching — a prefix test on
    "/staff/me" would also let through "/staff/mess-halls"."""
    return path in ("/staff/me", "/staff/logout") or path.startswith("/staff/me/")


def current_staff(request: Request) -> dict:
    """Re-reads the account on every request, so deactivating someone or
    changing their role applies immediately. Roles that require two-factor
    sign-in can do nothing but set it up until they have."""
    staff = staff_for_token(session_token(request, auth.STAFF_COOKIE))
    if (staff["role"] in config.REQUIRE_2FA_ROLES and not staff.get("two_factor_enabled")
            and not _allowed_before_two_factor(request.url.path)):
        raise HTTPException(status_code=403, detail={
            "code": "two_factor_setup_required",
            "message": "Your role requires two-factor sign-in. Set it up in My account first.",
        })
    return staff


# ---------- Rate limits ----------

def client_ip(request: Request):
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, name: str, limit: int, window_seconds: int, key: Optional[str] = None):
    """Shared (all processes) fixed-window limit; raises 429 with
    Retry-After when exceeded. `key` defaults to the client IP."""
    hits, reset_in = db.security.hit(f"{name}:{key or client_ip(request)}", window_seconds)
    if hits > limit * config.RATE_LIMIT_SCALE:
        raise HTTPException(status_code=429, detail="Too many requests — please slow down and try again shortly.",
                            headers={"Retry-After": str(max(1, reset_in))})


def require(staff: dict, capability: str):
    if not can(staff, capability):
        raise HTTPException(status_code=403, detail="Your role doesn't allow this.")
    return staff


def require_global_admin(staff: dict):
    require(staff, "manage_staff")
    if staff["college_id"]:
        raise HTTPException(status_code=403, detail="Only an all-colleges admin can do this.")
    return staff


def scoped_college(staff: dict, college_id) -> Optional[int]:
    """The college a request may look at."""
    if staff["college_id"]:
        if college_id and int(college_id) != staff["college_id"]:
            raise HTTPException(status_code=403, detail="Your account is limited to another college.")
        return staff["college_id"]
    return int(college_id) if college_id else None


def scoped_mess(staff: dict, mess_id) -> Optional[int]:
    """The mess hall filter a request must use (mess-limited accounts are
    pinned to theirs)."""
    if staff.get("mess_id"):
        if mess_id and int(mess_id) != staff["mess_id"]:
            raise HTTPException(status_code=403, detail="Your account is limited to another mess hall.")
        return staff["mess_id"]
    if mess_id:
        require_mess_in_scope(staff, mess_id)
    return int(mess_id) if mess_id else None


def require_mess_in_scope(staff: dict, mess_id) -> dict:
    mess = db.get_mess_hall(mess_id)
    if not mess:
        raise HTTPException(status_code=404, detail="Mess hall not found.")
    scoped_college(staff, mess["college_id"])
    if staff.get("mess_id") and staff["mess_id"] != mess["id"]:
        raise HTTPException(status_code=403, detail="Your account is limited to another mess hall.")
    return mess


def require_alert_in_scope(staff: dict, alert_id) -> dict:
    alert = db.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    scoped_college(staff, alert["college_id"])
    if staff.get("mess_id") and staff["mess_id"] != alert["mess_id"]:
        raise HTTPException(status_code=403, detail="Your account is limited to another mess hall.")
    return alert


def page(offset: int = 0, limit: int = 50, max_limit: int = 200):
    return max(0, offset), max(1, min(limit, max_limit))
