"""
auth.py — email masking, staff password hashing, server-side sessions in
HttpOnly cookies, and the shared login lockout.

IMPORTANT: change the bootstrap admin's password (MESS_ADMIN_PASSWORD only
seeds the very first admin account on an empty database).
"""

import base64
import hashlib
import hmac
import os

import config

ADMIN_PASSWORD = config.BOOTSTRAP_ADMIN_PASSWORD  # bootstrap admin only
ADMIN_EMAIL = config.BOOTSTRAP_ADMIN_EMAIL        # bootstrap admin only


def mask_email(email: str) -> str:
    """Staff only ever see this masked form, e.g. john.doe@college.edu -> jo******@college.edu"""
    if not email or "@" not in email:
        return "****"
    local, domain = email.split("@", 1)
    masked_local = local[0] + "*" if len(local) <= 2 else local[:2] + "*" * (len(local) - 2)
    return f"{masked_local}@{domain}"


# ---------- Staff passwords ----------
# scrypt (memory-hard, in the standard library) with a per-user random salt.
# Stored as "scrypt$n$r$p$salt$hash" so parameters can be raised later.

# Password rules live in passwords.py.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=_unb64(salt_b64), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest, _unb64(digest_b64))
    except Exception:
        return False


# Used when a login names an email with no account, so that response takes
# as long as a wrong password and doesn't reveal which emails exist.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-account")


# ---------- Sessions ----------
# Signing in creates a server-side session (db/sessions.py) and sets its
# random token as an HttpOnly cookie, so page scripts never see it. API
# clients and tests may send the same token as "Authorization: Bearer".

from datetime import timedelta

STAFF_COOKIE = "tt_staff"
STUDENT_COOKIE = "tt_student"
STAFF_IDLE = timedelta(hours=config.STAFF_IDLE_HOURS)
STAFF_MAX = timedelta(days=config.STAFF_MAX_DAYS)
STUDENT_IDLE = timedelta(days=config.STUDENT_IDLE_DAYS)
STUDENT_MAX = timedelta(days=config.STUDENT_MAX_DAYS)


def _client(request):
    ip = request.client.host if request and request.client else None
    ua = request.headers.get("user-agent") if request else None
    return ip, ua


def start_staff_session(staff_id, request=None):
    import db
    ip, ua = _client(request)
    return db.sessions.create("staff", STAFF_IDLE, STAFF_MAX, staff_id=staff_id, ip=ip, user_agent=ua)


def start_student_session(email, name="", request=None):
    import db
    ip, ua = _client(request)
    return db.sessions.create("student", STUDENT_IDLE, STUDENT_MAX, student_email=email, student_name=name,
                              ip=ip, user_agent=ua)


def staff_session(token):
    import db
    return db.sessions.get(token, "staff", STAFF_IDLE, STAFF_MAX)


def student_session(token):
    import db
    return db.sessions.get(token, "student", STUDENT_IDLE, STUDENT_MAX)


def set_session_cookie(response, name, token, max_age: timedelta):
    response.set_cookie(
        name, token, max_age=int(max_age.total_seconds()), httponly=True,
        secure=config.COOKIE_SECURE_FLAG, samesite=config.COOKIE_SAMESITE, path="/",
    )


def clear_session_cookie(response, name):
    response.delete_cookie(name, path="/", secure=config.COOKIE_SECURE_FLAG, samesite=config.COOKIE_SAMESITE)


# ---------- Login lockout (shared across server processes via MySQL) ----------

MAX_ATTEMPTS = 5                    # per IP
MAX_ATTEMPTS_PER_ACCOUNT = 10       # per email, across IPs — slows distributed guessing
LOCKOUT_SECONDS = 6 * 60 * 60


def check_lockout(*keys):
    """Seconds remaining for whichever key is locked longest, else None."""
    import db
    remaining = [s for s in (db.security.lockout_remaining(k) for k in keys) if s]
    return max(remaining) if remaining else None


def record_failed_attempt(ip_key, account_key=None):
    """Returns attempts left for this IP (0 = now locked)."""
    import db
    if account_key:
        db.security.record_failure(account_key, MAX_ATTEMPTS_PER_ACCOUNT, LOCKOUT_SECONDS)
    return db.security.record_failure(ip_key, MAX_ATTEMPTS, LOCKOUT_SECONDS)


def reset_attempts(*keys):
    import db
    for k in keys:
        db.security.clear_failures(k)
