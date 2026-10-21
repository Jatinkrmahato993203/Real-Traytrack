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

from fastapi import Header, HTTPException

import auth
import db
from permissions import can


def bearer(authorization: Optional[str]):
    if authorization and authorization.startswith("Bearer "):
        return authorization[len("Bearer "):]
    return None


# ---------- Students ----------

def current_student(authorization: Optional[str] = Header(None)) -> dict:
    """{"email", "name"} from the signed token issued at /auth/google —
    never a client-supplied email, which anyone could forge."""
    token = bearer(authorization)
    student = auth.verify_student_token(token) if token else None
    if not student:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please sign in again.")
    return student


# ---------- Staff ----------

def staff_from_header(authorization: Optional[str]) -> dict:
    token = bearer(authorization)
    staff_id = auth.verify_staff_token(token) if token else None
    staff = db.get_staff(staff_id) if staff_id else None
    if not staff or not staff["active"]:
        raise HTTPException(status_code=401, detail="Session expired or invalid — please log in again.")
    return staff


def current_staff(authorization: Optional[str] = Header(None)) -> dict:
    return staff_from_header(authorization)


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
