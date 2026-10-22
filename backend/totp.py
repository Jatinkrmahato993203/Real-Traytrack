"""
totp.py — time-based one-time passwords (RFC 6238), the 6-digit codes from
authenticator apps (Google Authenticator, Microsoft Authenticator, Authy…).
Standard library only.

  * 30-second steps, SHA-1, 6 digits — what every authenticator app uses.
  * Accepts the previous/current/next step to tolerate clock drift.
  * Returns the matched step so callers can refuse re-use of a code
    (replay protection).
  * Recovery codes: 10 one-time codes, stored only as SHA-256 hashes.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6


def new_secret():
    """160 random bits, base32 (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now=None):
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def code_at(secret, now=None):
    return _code(secret, current_step(now))


def verify(secret, code, last_used_step=None, now=None, window=1):
    """The step the code matched, or None. A code for a step at or before
    `last_used_step` is refused, so an intercepted code can't be replayed."""
    code = (code or "").replace(" ", "").strip()
    if not secret or not code.isdigit() or len(code) != DIGITS:
        return None
    step = current_step(now)
    for candidate in range(step - window, step + window + 1):
        if last_used_step is not None and candidate <= last_used_step:
            continue
        if hmac.compare_digest(_code(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret, account, issuer="TrayTrack"):
    """otpauth:// link — shown as a QR code for the authenticator app."""
    # Issuer and account are encoded separately with a literal ":" between
    # them — the form every authenticator app parses.
    label = f"{quote(issuer)}:{quote(account)}"
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"


# ---------- Recovery codes ----------

def new_recovery_codes(count=10):
    """Human-friendly one-time codes like 'k7m2-q9xd'."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2)) for _ in range(count)]


def hash_recovery_code(code):
    return hashlib.sha256(code.strip().lower().replace(" ", "").encode()).hexdigest()
