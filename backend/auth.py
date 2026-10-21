"""
auth.py — email masking, staff password hashing, and signed staff/student
sessions.

IMPORTANT: change ADMIN_TOKEN_SECRET before real deployment, and change
the bootstrap admin's password (MESS_ADMIN_PASSWORD only seeds the very
first admin account on an empty database).
"""

import os
import hmac
import hashlib
import time
import base64
import json

ADMIN_PASSWORD = os.environ.get("MESS_ADMIN_PASSWORD", "changeme123")  # bootstrap admin only
ADMIN_EMAIL = os.environ.get("MESS_ADMIN_EMAIL", "admin@traytrack.local")   # bootstrap admin only
TOKEN_SECRET = os.environ.get("ADMIN_TOKEN_SECRET", "dev-secret-change-me")
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60  # 8 hours


def mask_email(email: str) -> str:
    """Never show a raw student email anywhere in the UI — even admins only
    ever see this masked form, e.g. john.doe@college.edu -> jo******@college.edu"""
    if not email or "@" not in email:
        return "****"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[:2] + "*" * (len(local) - 2)
    return f"{masked_local}@{domain}"


# ---------- Staff passwords ----------
# scrypt (memory-hard, in the standard library) with a per-user random
# salt. Stored as "scrypt$n$r$p$salt$hash" so parameters can be raised
# later without breaking existing hashes.

MIN_PASSWORD_LENGTH = 8
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        unb64 = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        digest = hashlib.scrypt(password.encode(), salt=unb64(salt_b64), n=int(n), r=int(r), p=int(p), dklen=32)
        # constant-time comparison — avoids leaking timing info
        return hmac.compare_digest(digest, unb64(digest_b64))
    except Exception:
        return False


# Used when a login names an email with no account, so that response takes
# as long as a wrong password and doesn't reveal which emails exist.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-account")


# ---------- Signed session tokens ----------
# The real password (staff) or Google credential (student) is only ever
# sent once, at login. After that, the frontend holds a signed, expiring
# token instead — and the server reads identity ONLY from that token, never
# from anything else the client sends.

STUDENT_TOKEN_LIFETIME_SECONDS = 24 * 60 * 60  # 24 hours


def _sign(payload: dict) -> str:
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify(token: str):
    """Returns the payload if the signature is valid and unexpired, else None."""
    if not token or "." not in token:
        return None
    payload_b64, _, signature = token.partition(".")

    expected_signature = hmac.new(TOKEN_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None

    if payload.get("exp", 0) <= time.time():
        return None
    return payload


def create_staff_token(staff_id: int) -> str:
    """The token only names the account. Role, college scope and whether
    the account is still active are looked up fresh on every request."""
    return _sign({"role": "staff", "uid": staff_id, "exp": int(time.time()) + TOKEN_LIFETIME_SECONDS})


def verify_staff_token(token: str):
    """Returns the staff account id, or None."""
    payload = _verify(token)
    if payload is None or payload.get("role") != "staff":
        return None
    return payload.get("uid")


def create_student_token(email: str) -> str:
    """Issued only after Google has verified the email (see /auth/google)."""
    return _sign({
        "role": "student",
        "email": email.strip().lower(),
        "exp": int(time.time()) + STUDENT_TOKEN_LIFETIME_SECONDS,
    })


def verify_student_token(token: str):
    """Returns the Google-verified email baked into the token, or None."""
    payload = _verify(token)
    if payload is None or payload.get("role") != "student":
        return None
    return payload.get("email")


# ---------- Login attempt rate limiting ----------
# In-memory (per-process) tracking: 5 wrong attempts -> locked out for 6
# hours. Resets on backend restart, which is fine for this scale.

_attempts = {}  # key -> {"count": int, "locked_until": float}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 6 * 60 * 60  # 6 hours


def check_lockout(key: str):
    """Returns seconds remaining if locked out, else None."""
    entry = _attempts.get(key)
    if not entry:
        return None
    locked_until = entry.get("locked_until")
    if locked_until and locked_until > time.time():
        return int(locked_until - time.time())
    return None


def record_failed_attempt(key: str):
    entry = _attempts.setdefault(key, {"count": 0, "locked_until": None})
    entry["count"] += 1
    if entry["count"] >= MAX_ATTEMPTS:
        entry["locked_until"] = time.time() + LOCKOUT_SECONDS


def reset_attempts(key: str):
    _attempts.pop(key, None)
