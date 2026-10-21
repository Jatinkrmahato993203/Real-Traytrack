"""
db/sessions.py — server-side sign-in sessions.

The browser holds a random token in an HttpOnly cookie (page scripts can't
read it, so an XSS bug can't steal it). Only its SHA-256 is stored here, so
a database leak doesn't leak usable sessions either. Sessions expire after
a period of inactivity (sliding) and at an absolute maximum, and can be
revoked at any time — sign-out, password change, deactivation, data erasure.
"""

import hashlib
import secrets
from datetime import timedelta

from .core import transaction, fetch_one, utcnow, to_db

TOUCH_EVERY = timedelta(minutes=5)  # don't write on every request


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create(kind, idle, absolute, staff_id=None, student_email=None, student_name=None, ip=None, user_agent=None):
    """Returns the raw token (only ever given to the client)."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with transaction() as cur:
        cur.execute(
            "INSERT INTO sessions (token_hash, kind, staff_id, student_email, student_name, created_at, "
            "last_seen_at, expires_at, ip, user_agent) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (_hash(token), kind, staff_id, (student_email or "").lower() or None, student_name, to_db(now),
             to_db(now), to_db(now + min(idle, absolute)), (ip or "")[:64], (user_agent or "")[:255]),
        )
    return token


def get(token, kind, idle, absolute):
    """The live session for a token, sliding its idle expiry; None if
    missing, revoked or expired."""
    if not token:
        return None
    row = fetch_one(
        "SELECT * FROM sessions WHERE token_hash = %s AND kind = %s AND revoked_at IS NULL "
        "AND expires_at > UTC_TIMESTAMP()",
        (_hash(token), kind),
    )
    if not row:
        return None
    now = utcnow()
    if now - row["last_seen_at"] > TOUCH_EVERY:
        new_expiry = min(now + idle, row["created_at"] + absolute)
        with transaction() as cur:
            cur.execute("UPDATE sessions SET last_seen_at = %s, expires_at = %s WHERE token_hash = %s",
                        (to_db(now), to_db(new_expiry), row["token_hash"]))
    return row


def revoke(token):
    if token:
        with transaction() as cur:
            cur.execute("UPDATE sessions SET revoked_at = UTC_TIMESTAMP() WHERE token_hash = %s AND revoked_at IS NULL",
                        (_hash(token),))


def revoke_staff(staff_id, keep_token=None):
    """Signs a staff member out everywhere (optionally except this session)."""
    with transaction() as cur:
        cur.execute(
            "UPDATE sessions SET revoked_at = UTC_TIMESTAMP() WHERE staff_id = %s AND revoked_at IS NULL "
            "AND token_hash != %s",
            (staff_id, _hash(keep_token) if keep_token else ""),
        )
        return cur.rowcount


def revoke_student(email):
    with transaction() as cur:
        cur.execute("UPDATE sessions SET revoked_at = UTC_TIMESTAMP() WHERE student_email = %s AND revoked_at IS NULL",
                    (email.strip().lower(),))
        return cur.rowcount


def purge_old(days=30):
    """Deletes sessions that ended more than `days` ago."""
    with transaction() as cur:
        cur.execute(
            "DELETE FROM sessions WHERE expires_at < UTC_TIMESTAMP() - INTERVAL %s DAY "
            "OR revoked_at < UTC_TIMESTAMP() - INTERVAL %s DAY",
            (days, days),
        )
        return cur.rowcount
