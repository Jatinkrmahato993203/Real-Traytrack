"""
routers/staff_setup.py — staff sign-in, staff accounts, and setup: colleges,
alert contacts, mess halls (capacity, kitchen codes) and the checklist.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from datetime import timedelta

import auth
import config
import db
import fssai_rules
import insights
import notify
import passwords
import totp
from deps import current_staff, rate_limit, require, require_global_admin, require_mess_in_scope, scoped_college
from permissions import ROLES, capabilities

router = APIRouter(prefix="/staff", tags=["staff"])


def staff_view(staff):
    keys = ("id", "name", "email", "role", "college_id", "college_name", "mess_id", "mess_name", "active")
    return {**{k: staff.get(k) for k in keys}, "capabilities": capabilities(staff),
            "two_factor_enabled": bool(staff.get("two_factor_enabled")),
            "two_factor_required": staff.get("role") in config.REQUIRE_2FA_ROLES}


MFA_COOKIE = "tt_mfa"
MFA_TTL = timedelta(minutes=5)   # time allowed between password and code


# ---------- Sign-in ----------

class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    rate_limit(request, "staff_login", 30, 60)
    ip_key = f"ip:{request.client.host if request.client else 'unknown'}"
    account_key = f"acct:{payload.email.strip().lower()}"
    locked = auth.check_lockout(ip_key, account_key)
    if locked:
        raise HTTPException(status_code=429,
                            detail=f"Too many failed attempts. Try again in {locked // 3600}h {(locked % 3600) // 60}m.")
    account = db.get_staff_login(payload.email)
    # Always run one password check so response time doesn't reveal which
    # emails have accounts.
    ok = auth.verify_password(payload.password, account["password_hash"] if account else auth.DUMMY_PASSWORD_HASH)
    if not account or not ok or not account["active"]:
        left = auth.record_failed_attempt(ip_key, account_key)
        if left > 0:
            raise HTTPException(status_code=401, detail=f"Incorrect email or password. {left} attempt(s) left.")
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 6 hours.")
    staff = db.get_staff(account["id"])
    if staff["two_factor_enabled"]:
        # Password was right, but that's only half: hand out a short-lived
        # challenge (HttpOnly cookie) that /login/verify exchanges for a
        # session once the authenticator code checks out.
        challenge = db.sessions.create("mfa", MFA_TTL, MFA_TTL, staff_id=staff["id"],
                                       ip=request.client.host if request.client else None)
        auth.set_session_cookie(response, MFA_COOKIE, challenge, MFA_TTL)
        return {"two_factor_required": True}
    auth.reset_attempts(ip_key, account_key)
    return _complete_sign_in(staff, request, response)


def _complete_sign_in(staff, request, response):
    token = auth.start_staff_session(staff["id"], request)
    auth.set_session_cookie(response, auth.STAFF_COOKIE, token, auth.STAFF_MAX)
    return {"staff": staff_view(staff)}


class VerifyRequest(BaseModel):
    code: str


def _check_second_factor(staff_id, code):
    """True for a valid, unused authenticator code or recovery code."""
    secrets_ = db.get_two_factor(staff_id)
    step = totp.verify(secrets_["totp_secret"], code, last_used_step=secrets_["totp_last_step"])
    if step is not None:
        return db.record_totp_step(staff_id, step)
    if "-" in (code or "") or len((code or "").strip()) > totp.DIGITS:
        remaining = db.use_recovery_code(staff_id, totp.hash_recovery_code(code))
        if remaining is not None:
            staff = db.get_staff(staff_id)
            db.log_activity("staff_recovery_code_used",
                            f"{staff['name']} signed in with a recovery code ({remaining} left)",
                            college_id=staff["college_id"], details={"actor": staff["name"], "remaining": remaining})
            return True
    return False


@router.post("/login/verify")
def verify_second_factor(payload: VerifyRequest, request: Request, response: Response):
    """Second step of sign-in: the 6-digit authenticator code (or a recovery code)."""
    rate_limit(request, "staff_login_verify", 20, 60)
    challenge = request.cookies.get(MFA_COOKIE)
    session = db.sessions.get(challenge, "mfa", MFA_TTL, MFA_TTL)
    if not session:
        raise HTTPException(status_code=401, detail="Your sign-in timed out — enter your email and password again.")
    staff = db.get_staff(session["staff_id"])
    ip_key = f"ip:{request.client.host if request.client else 'unknown'}"
    account_key = f"acct:{staff['email']}"
    locked = auth.check_lockout(ip_key, account_key)
    if locked:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again later.")
    if not staff["active"] or not _check_second_factor(staff["id"], payload.code):
        left = auth.record_failed_attempt(ip_key, account_key)
        raise HTTPException(status_code=401 if left else 429,
                            detail=f"That code didn't work. {left} attempt(s) left." if left else "Too many failed attempts.")
    db.sessions.revoke(challenge)
    auth.clear_session_cookie(response, MFA_COOKIE)
    auth.reset_attempts(ip_key, account_key)
    return _complete_sign_in(staff, request, response)


@router.post("/logout")
def logout(request: Request, response: Response):
    db.sessions.revoke(request.cookies.get(auth.STAFF_COOKIE))
    auth.clear_session_cookie(response, auth.STAFF_COOKIE)
    return {"ok": True}


@router.post("/me/sign-out-everywhere")
def sign_out_everywhere(response: Response, staff=Depends(current_staff)):
    count = db.sessions.revoke_staff(staff["id"])
    auth.clear_session_cookie(response, auth.STAFF_COOKIE)
    return {"ok": True, "sessions_ended": count}


@router.get("/me")
def me(staff=Depends(current_staff)):
    return staff_view(staff)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/me/password")
def change_own_password(payload: ChangePasswordRequest, staff=Depends(current_staff)):
    account = db.get_staff_login(staff["email"])
    if not auth.verify_password(payload.current_password, account["password_hash"]):
        raise HTTPException(status_code=400, detail="Your current password is incorrect.")
    _check_password(payload.new_password, staff["email"], staff["name"])
    db.update_staff(staff["id"], password_hash=auth.hash_password(payload.new_password))
    # Anyone else signed in as this person (an old device, someone who saw
    # the password) is signed out; this session continues.
    db.sessions.revoke_staff(staff["id"], keep_token=staff["session_token"])
    db.log_activity("staff_password_changed", f"{staff['name']} changed their password",
                    college_id=staff["college_id"], details={"actor": staff["name"]})
    return {"ok": True}


def _check_password(password, email="", name=""):
    problem = passwords.problem_with(password, email, name)
    if problem:
        raise HTTPException(status_code=400, detail=problem)


# ---------- Two-factor setup (for yourself) ----------

@router.post("/me/2fa/setup")
def two_factor_setup(staff=Depends(current_staff)):
    """Starts setup: a new secret to scan into an authenticator app. Not
    active until confirmed with a code from the app."""
    secret = totp.new_secret()
    db.set_pending_two_factor(staff["id"], secret)
    return {"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, staff["email"])}


@router.post("/me/2fa/enable")
def two_factor_enable(payload: VerifyRequest, staff=Depends(current_staff)):
    pending = db.get_two_factor(staff["id"])["totp_pending_secret"]
    if not pending:
        raise HTTPException(status_code=400, detail="Start setup first.")
    step = totp.verify(pending, payload.code)
    if step is None:
        raise HTTPException(status_code=400, detail="That code didn't match — check the time on your phone and try the newest code.")
    codes = totp.new_recovery_codes()
    db.enable_two_factor(staff["id"], pending, step, [totp.hash_recovery_code(c) for c in codes])
    db.sessions.revoke_staff(staff["id"], keep_token=staff["session_token"])
    db.log_activity("staff_2fa_enabled", f"{staff['name']} turned on two-factor sign-in",
                    college_id=staff["college_id"], details={"actor": staff["name"]})
    return {"ok": True, "recovery_codes": codes}


class DisableTwoFactorRequest(BaseModel):
    password: str
    code: str


@router.post("/me/2fa/disable")
def two_factor_disable(payload: DisableTwoFactorRequest, staff=Depends(current_staff)):
    if staff["role"] in config.REQUIRE_2FA_ROLES:
        raise HTTPException(status_code=400, detail="Your role requires two-factor sign-in, so it can't be turned off.")
    account = db.get_staff_login(staff["email"])
    if not auth.verify_password(payload.password, account["password_hash"]) or not _check_second_factor(staff["id"], payload.code):
        raise HTTPException(status_code=400, detail="Password or code is incorrect.")
    db.disable_two_factor(staff["id"])
    db.log_activity("staff_2fa_disabled", f"{staff['name']} turned off two-factor sign-in",
                    college_id=staff["college_id"], details={"actor": staff["name"]})
    return {"ok": True}


@router.post("/me/2fa/recovery-codes")
def new_recovery_codes(payload: VerifyRequest, staff=Depends(current_staff)):
    """Replaces all recovery codes (e.g. after using some)."""
    if not staff["two_factor_enabled"] or not _check_second_factor(staff["id"], payload.code):
        raise HTTPException(status_code=400, detail="Enter a current code from your authenticator app.")
    codes = totp.new_recovery_codes()
    secrets_ = db.get_two_factor(staff["id"])
    db.enable_two_factor(staff["id"], secrets_["totp_secret"], secrets_["totp_last_step"],
                         [totp.hash_recovery_code(c) for c in codes])
    return {"recovery_codes": codes}


# ---------- Staff accounts ----------

@router.get("/roles")
def list_roles(staff=Depends(current_staff)):
    return [{"role": r, "description": d} for r, d in ROLES.items()]


@router.get("/accounts")
def list_accounts(role: Optional[str] = None, staff=Depends(current_staff)):
    """Admins manage accounts; anyone who assigns work (alert owners,
    scheduled inspectors) can list active colleagues in their college."""
    if role:
        return db.list_staff(college_id=staff["college_id"], roles=[role], active_only=True)
    require(staff, "manage_staff")
    return db.list_staff(college_id=staff["college_id"])


class CreateStaffRequest(BaseModel):
    name: str
    email: str
    role: str
    college_id: Optional[int] = None
    mess_id: Optional[int] = None
    password: str


@router.post("/accounts")
def create_account(payload: CreateStaffRequest, staff=Depends(current_staff)):
    """College-scoped admins create accounts for their own college only;
    only an all-colleges admin creates another all-colleges account."""
    require(staff, "manage_staff")
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role.")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    _check_password(payload.password, email, payload.name)
    college_id = scoped_college(staff, payload.college_id) if (payload.college_id or staff["college_id"]) else None
    if college_id and not db.get_college(college_id):
        raise HTTPException(status_code=400, detail="College not found.")
    mess_id = None
    if payload.mess_id:
        mess = require_mess_in_scope(staff, payload.mess_id)
        if mess["college_id"] != college_id:
            raise HTTPException(status_code=400, detail="That mess hall belongs to a different college.")
        mess_id = mess["id"]
    if payload.role in ("mess_head", "principal") and not college_id:
        raise HTTPException(status_code=400, detail="A principal or mess head must belong to a college.")
    if db.get_staff_login(email):
        raise HTTPException(status_code=400, detail="An account with that email already exists.")
    new_id = db.create_staff(payload.name, email, payload.role, college_id, auth.hash_password(payload.password), mess_id)
    db.log_activity("admin_staff_added", f"{staff['name']} added {payload.role.replace('_', ' ')} account {payload.name.strip()}",
                    college_id=college_id, details={"actor": staff["name"], "role": payload.role, "email": email})
    return db.get_staff(new_id)


class UpdateStaffRequest(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None
    mess_id: Optional[int] = None
    clear_mess: bool = False
    reset_two_factor: bool = False   # lost phone: they set it up again at next sign-in


@router.patch("/accounts/{staff_id}")
def update_account(staff_id: int, payload: UpdateStaffRequest, staff=Depends(current_staff)):
    require(staff, "manage_staff")
    target = db.get_staff(staff_id)
    if not target:
        raise HTTPException(status_code=404, detail="Account not found.")
    if staff["college_id"] and target["college_id"] != staff["college_id"]:
        raise HTTPException(status_code=403, detail="You can only manage your own college's staff.")
    if payload.role is not None and payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role.")
    if payload.password is not None:
        _check_password(payload.password, target["email"], target["name"])
    if target["id"] == staff["id"] and (payload.active is False or (payload.role and payload.role != "admin")):
        raise HTTPException(status_code=400, detail="You can't deactivate or demote your own account.")
    removes_global_admin = (target["role"] == "admin" and not target["college_id"] and target["active"]
                            and (payload.active is False or (payload.role and payload.role != "admin")))
    if removes_global_admin and db.count_active_global_admins() <= 1:
        raise HTTPException(status_code=400, detail="That's the last active all-colleges admin — add another first.")
    if payload.mess_id:
        mess = require_mess_in_scope(staff, payload.mess_id)
        if mess["college_id"] != target["college_id"]:
            raise HTTPException(status_code=400, detail="That mess hall belongs to a different college.")

    db.update_staff(staff_id, name=payload.name, role=payload.role, active=payload.active,
                    password_hash=auth.hash_password(payload.password) if payload.password else None,
                    mess_id=payload.mess_id, clear_mess=payload.clear_mess)
    if payload.reset_two_factor:
        db.disable_two_factor(staff_id)
    if payload.active is False or payload.password or payload.reset_two_factor:
        db.sessions.revoke_staff(staff_id)  # deactivated or reset: signed out everywhere
    changes = [k for k in ("name", "role", "active", "mess_id") if getattr(payload, k) is not None]
    if payload.clear_mess:
        changes.append("mess_id")
    if payload.reset_two_factor:
        changes.append("two-factor reset")
    if payload.password:
        changes.append("password")
    db.log_activity("admin_staff_updated",
                    f"{staff['name']} updated {target['name']}'s account ({', '.join(changes) or 'no changes'})",
                    college_id=target["college_id"], details={"actor": staff["name"], "changes": changes})
    return db.get_staff(staff_id)


# ---------- Colleges & contacts ----------

@router.get("/colleges")
def list_colleges(staff=Depends(current_staff)):
    """Full records (with alert contacts) for the colleges in scope."""
    colleges = db.list_colleges()
    return [c for c in colleges if not staff["college_id"] or c["id"] == staff["college_id"]]


class AddCollegeRequest(BaseModel):
    name: str
    email_domain: str
    mess_head_email: Optional[str] = None
    principal_email: Optional[str] = None
    fssai_contact_email: Optional[str] = None


@router.post("/colleges")
def add_college(payload: AddCollegeRequest, staff=Depends(current_staff)):
    require_global_admin(staff)
    if not payload.name.strip() or "." not in payload.email_domain:
        raise HTTPException(status_code=400, detail="Enter a college name and an email domain like college.ac.in.")
    try:
        college_id = db.add_college(payload.name, payload.email_domain, payload.mess_head_email,
                                    payload.principal_email, payload.fssai_contact_email)
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't add college — that name or domain already exists.")
    db.log_activity("admin_college_added", f"{staff['name']} added college {payload.name} (@{payload.email_domain})",
                    college_id=college_id, details={"actor": staff["name"]})
    return {"ok": True, "id": college_id}


class ContactsRequest(BaseModel):
    mess_head_email: Optional[str] = None
    principal_email: Optional[str] = None
    fssai_contact_email: Optional[str] = None
    grievance_contact: Optional[str] = None  # shown to students on the privacy page


@router.patch("/colleges/{college_id}/contacts")
def update_contacts(college_id: int, payload: ContactsRequest, staff=Depends(current_staff)):
    require(staff, "setup")
    scoped_college(staff, college_id)
    db.update_college_contacts(college_id, payload.mess_head_email, payload.principal_email, payload.fssai_contact_email)
    db.update_grievance_contact(college_id, payload.grievance_contact)
    college = db.get_college(college_id)
    db.log_activity("admin_contacts_updated", f"{staff['name']} updated alert contacts — {college['name']}",
                    college_id=college_id, details={"actor": staff["name"]})
    return {"ok": True}


@router.get("/colleges/{college_id}/settings")
def get_settings(college_id: int, staff=Depends(current_staff)):
    require(staff, "view")
    scoped_college(staff, college_id)
    return {"settings": db.get_college_settings(college_id), "defaults": fssai_rules.DEFAULT_SETTINGS,
            "bounds": fssai_rules.SETTING_BOUNDS}


@router.patch("/colleges/{college_id}/settings")
def update_settings(college_id: int, changes: dict, staff=Depends(current_staff)):
    """Alert rules for this college. Send a value to change it, null to go
    back to the default. Every change is logged with who made it."""
    require(staff, "setup")
    scoped_college(staff, college_id)
    clean, errors = fssai_rules.validate_settings(changes)
    merged = {**db.get_college_settings(college_id), **{k: v for k, v in clean.items() if v is not None}}
    for lo, hi in (("category_min", "category_max"), ("mess_min", "mess_max")):
        if merged[lo] > merged[hi]:
            errors.append(f"{lo} can't be more than {hi}")
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    before = db.get_college_settings(college_id)
    db.update_college_settings(college_id, clean)
    after = db.get_college_settings(college_id)
    changed = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
    db.log_activity("admin_settings_changed",
                    f"{staff['name']} changed alert rules: " + ", ".join(f"{k} {a}→{b}" for k, (a, b) in changed.items()),
                    college_id=college_id, details={"actor": staff["name"], "changes": changed})
    return {"settings": after}


@router.get("/insights")
def get_insights(college_id: Optional[int] = None, days: int = 90, staff=Depends(current_staff)):
    require(staff, "view")
    college_id = scoped_college(staff, college_id)
    if not college_id:
        raise HTTPException(status_code=400, detail="Choose a college.")
    return insights.college_insights(college_id, max(7, min(days, 365)))


@router.delete("/colleges/{college_id}")
def delete_college(college_id: int, staff=Depends(current_staff)):
    require_global_admin(staff)
    college = db.get_college(college_id)
    if not college:
        raise HTTPException(status_code=404, detail="College not found.")
    try:
        db.delete_college(college_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't delete — remove this college's mess halls and staff first.")
    db.log_activity("admin_college_deleted", f"{staff['name']} deleted college {college['name']}",
                    details={"actor": staff["name"]})
    return {"ok": True}


@router.get("/setup-health")
def setup_health(staff=Depends(current_staff)):
    """What's stopping notifications from reaching people."""
    require(staff, "view")
    health = notify.setup_health()
    if staff["college_id"]:
        health["colleges"] = [c for c in health["colleges"] if c["college_id"] == staff["college_id"]]
    health["jobs"] = db.security.all_job_runs() if not staff["college_id"] else []
    return health


# ---------- Mess halls ----------

@router.get("/mess-halls")
def list_mess_halls(college_id: Optional[int] = None, staff=Depends(current_staff)):
    college_id = scoped_college(staff, college_id)
    halls = db.list_mess_halls(college_id, include_codes=True)
    if staff.get("mess_id"):
        halls = [h for h in halls if h["id"] == staff["mess_id"]]
    for h in halls:
        h["report_url"] = f"{config.APP_BASE_URL}/report?mess={h['id']}"
        h["rate_url"] = f"{config.APP_BASE_URL}/rate?mess={h['id']}"
        if not (staff["role"] in ("admin", "inspector")):
            h.pop("kitchen_code", None)  # only people who print it or inspect need it
    return halls


class MessHallRequest(BaseModel):
    college_id: int
    name: str
    capacity: Optional[int] = None


@router.post("/mess-halls")
def add_mess_hall(payload: MessHallRequest, staff=Depends(current_staff)):
    require(staff, "setup")
    scoped_college(staff, payload.college_id)
    if payload.capacity is not None and payload.capacity < 1:
        raise HTTPException(status_code=400, detail="Capacity must be a positive number.")
    try:
        mess_id = db.add_mess_hall(payload.college_id, payload.name, payload.capacity)
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't add mess hall — it may already exist.")
    db.log_activity("admin_mess_added", f"{staff['name']} added mess hall {payload.name.strip()}",
                    mess_id=mess_id, details={"actor": staff["name"]})
    return {"ok": True, "id": mess_id}


class UpdateMessHallRequest(BaseModel):
    name: Optional[str] = None
    capacity: Optional[int] = None
    clear_capacity: bool = False


@router.patch("/mess-halls/{mess_id}")
def update_mess_hall(mess_id: int, payload: UpdateMessHallRequest, staff=Depends(current_staff)):
    require(staff, "setup")
    mess = require_mess_in_scope(staff, mess_id)
    if payload.capacity is not None and payload.capacity < 1:
        raise HTTPException(status_code=400, detail="Capacity must be a positive number.")
    db.update_mess_hall(mess_id, payload.name, payload.capacity, payload.clear_capacity)
    db.log_activity("admin_mess_updated", f"{staff['name']} updated mess hall {mess['name']}",
                    mess_id=mess_id, details={"actor": staff["name"], "capacity": payload.capacity})
    return {"ok": True}


@router.post("/mess-halls/{mess_id}/kitchen-code")
def regenerate_kitchen_code(mess_id: int, staff=Depends(current_staff)):
    """A new code invalidates the printed one (e.g. if it was photographed
    and shared, so inspections could be 'verified' remotely)."""
    require(staff, "setup")
    mess = require_mess_in_scope(staff, mess_id)
    code = db.ensure_kitchen_code(mess_id, regenerate=True)
    db.log_activity("admin_kitchen_code", f"{staff['name']} issued a new kitchen code for {mess['name']}",
                    mess_id=mess_id, details={"actor": staff["name"]})
    return {"kitchen_code": code}


@router.delete("/mess-halls/{mess_id}")
def delete_mess_hall(mess_id: int, staff=Depends(current_staff)):
    require(staff, "setup")
    mess = require_mess_in_scope(staff, mess_id)
    try:
        db.delete_mess_hall(mess_id)
    except Exception:
        raise HTTPException(status_code=400,
                            detail="Couldn't delete — this mess hall still has complaints, inspections or alerts.")
    db.log_activity("admin_mess_deleted", f"{staff['name']} deleted mess hall {mess['name']}",
                    college_id=mess["college_id"], details={"actor": staff["name"]})
    return {"ok": True}


# ---------- Checklist ----------

@router.get("/checklist")
def get_checklist(college_id: Optional[int] = None, mess_id: Optional[int] = None,
                  include_inactive: bool = False, staff=Depends(current_staff)):
    if mess_id:
        college_id = require_mess_in_scope(staff, mess_id)["college_id"]
    college_id = scoped_college(staff, college_id)
    return db.get_checklist(college_id, include_inactive=include_inactive)


class ChecklistItemRequest(BaseModel):
    college_id: int
    text: str
    critical: bool = False


@router.post("/checklist-items")
def add_checklist_item(payload: ChecklistItemRequest, staff=Depends(current_staff)):
    require(staff, "setup")
    scoped_college(staff, payload.college_id)
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Describe what the inspector should check.")
    item_id = db.add_checklist_item(payload.college_id, payload.text, payload.critical)
    db.log_activity("admin_checklist_changed", f"{staff['name']} added checklist item: {payload.text.strip()}",
                    college_id=payload.college_id, details={"actor": staff["name"], "critical": payload.critical})
    return {"ok": True, "id": item_id}


class UpdateChecklistItemRequest(BaseModel):
    college_id: int
    text: Optional[str] = None
    critical: Optional[bool] = None
    active: Optional[bool] = None


@router.patch("/checklist-items/{item_id}")
def update_checklist_item(item_id: int, payload: UpdateChecklistItemRequest, staff=Depends(current_staff)):
    require(staff, "setup")
    scoped_college(staff, payload.college_id)
    if not db.update_checklist_item(payload.college_id, item_id, payload.text, payload.critical, payload.active):
        raise HTTPException(status_code=404, detail="Checklist item not found.")
    db.log_activity("admin_checklist_changed", f"{staff['name']} edited a checklist item",
                    college_id=payload.college_id, details={"actor": staff["name"], "item_id": item_id})
    return {"ok": True}
