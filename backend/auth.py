"""
auth.py — email masking, staff password hashing, signed staff/student
sessions, and the shared login lockout.

IMPORTANT: change ADMIN_TOKEN_SECRET before real deployment, and change
the bootstrap admin's password (MESS_ADMIN_PASSWORD only seeds the very
first admin account on an empty database).
"""

import base64
import hashlib
import hmac
import json
import os
import time

import config

ADMIN_PASSWORD = config.BOOTSTRAP_ADMIN_PASSWORD  # bootstrap admin only
ADMIN_EMAIL = config.BOOTSTRAP_ADMIN_EMAIL        # bootstrap admin only
TOKEN_SECRET = config.TOKEN_SECRET


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

MIN_PASSWORD_LENGTH = 8
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


# ---------- Signed session tokens ----------
# The password (staff) or Google credential (student) is sent once, at
# login. After that the frontend holds a signed, expiring token, and the
# server reads identity ONLY from it.

def _sign(payload: dict) -> str:
    payload_b64 = _b64(json.dumps(payload).encode())
    signature = hmac.new(TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify(token: str):
    if not token or "." not in token:
        return None
    payload_b64, _, signature = token.partition(".")
    expected = hmac.new(TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_unb64(payload_b64))
    except Exception:
        return None
    return payload if payload.get("exp", 0) > time.time() else None


def create_staff_token(staff_id: int) -> str:
    """Only names the account; role, scope and active flag are looked up
    fresh on every request."""
    return _sign({"role": "staff", "uid": staff_id, "exp": int(time.time()) + config.STAFF_TOKEN_HOURS * 3600})


def verify_staff_token(token: str):
    payload = _verify(token)
    return payload.get("uid") if payload and payload.get("role") == "staff" else None


def create_student_token(email: str, name: str = "") -> str:
    """Issued only after Google has verified the email (see /auth/google)."""
    return _sign({
        "role": "student", "email": email.strip().lower(), "name": (name or "")[:120],
        "exp": int(time.time()) + config.STUDENT_TOKEN_DAYS * 86400,
    })


def verify_student_token(token: str):
    """Returns {"email", "name"} or None."""
    payload = _verify(token)
    if not payload or payload.get("role") != "student" or not payload.get("email"):
        return None
    return {"email": payload["email"], "name": payload.get("name", "")}


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
