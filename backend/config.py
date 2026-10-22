"""
config.py — every setting the backend reads from the environment, in one
place. Values come from the process environment or backend/.env.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --- Database ---
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = _int("DB_PORT", 3306)
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "mess_monitor")
DB_POOL_SIZE = _int("DB_POOL_SIZE", 20)

# --- Web ---
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
# Comma-separated list, e.g. "http://localhost:5173,https://traytrack.college.edu"
FRONTEND_ORIGINS = [o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173").split(",") if o.strip()]
# Public address of the frontend — used in QR codes and email links.
APP_BASE_URL = os.environ.get("APP_BASE_URL", FRONTEND_ORIGINS[0]).rstrip("/")

# --- Sessions (server-side, HttpOnly cookies) ---
# Staff: signed out after 8 idle hours, and at most 7 days after signing in.
STAFF_IDLE_HOURS = _int("STAFF_IDLE_HOURS", 8)
STAFF_MAX_DAYS = _int("STAFF_MAX_DAYS", 7)
# Students: signed out after 7 idle days, and at most 30 days after signing in.
STUDENT_IDLE_DAYS = _int("STUDENT_IDLE_DAYS", 7)
STUDENT_MAX_DAYS = _int("STUDENT_MAX_DAYS", 30)
# Cookies are Secure automatically when the site is served over HTTPS.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "auto")
# "lax" works when the frontend and API share a site (e.g. one domain with
# /api, or localhost:5173 + localhost:8000). Use "none" (HTTPS only) if the
# API lives on a different site than the frontend.
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax").lower()

# Browser end-to-end tests only: lets a test sign in as any student
# without Google. NEVER enable on a real deployment — it's refused unless
# the database is a throwaway test one and the site runs on localhost.
E2E_TEST_LOGIN = os.environ.get("E2E_TEST_LOGIN", "0") == "1"

# Roles that must use two-factor sign-in (authenticator app). They can still
# sign in without it, but can do nothing except set it up.
REQUIRE_2FA_ROLES = {r.strip() for r in os.environ.get("REQUIRE_2FA_ROLES", "admin,principal").split(",") if r.strip()}
BOOTSTRAP_ADMIN_EMAIL = os.environ.get("MESS_ADMIN_EMAIL", "admin@traytrack.local")
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("MESS_ADMIN_PASSWORD", "changeme123")

# --- Email (optional — without it, notifications are recorded as skipped) ---
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1") != "0"   # 0 only for a local test mail server

# Multiplies every rate limit (tests raise it; never set below 1 in production).
RATE_LIMIT_SCALE = float(os.environ.get("RATE_LIMIT_SCALE", "1"))

# --- Privacy ---
# Student identity (email, name) on complaints/ratings is irreversibly
# anonymized after this many days; their photos are deleted.
RETENTION_DAYS = _int("RETENTION_DAYS", 365)
PRIVACY_NOTICE_VERSION = "2026-10"
# The activity log (audit trail) is trimmed to this many days.
ACTIVITY_RETENTION_DAYS = _int("ACTIVITY_RETENTION_DAYS", 730)

# --- Files ---
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", BASE_DIR / "uploads"))
LOG_DIR = Path(os.environ.get("LOG_DIR", BASE_DIR / "logs"))

# --- Background jobs (escalation, reminders, digests, retention) ---
JOBS_ENABLED = os.environ.get("JOBS_ENABLED", "1") != "0"
# Local timezone for "Monday 9 AM" style schedules and for email text.
LOCAL_TZ = os.environ.get("LOCAL_TZ", "Asia/Kolkata")

# --- Optional error tracking ---
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")


if E2E_TEST_LOGIN:
    from urllib.parse import urlparse
    _host = urlparse(APP_BASE_URL).hostname or ""
    if not DB_NAME.startswith(("traytrack_e2e", "traytrack_test")) or _host not in ("localhost", "127.0.0.1"):
        raise RuntimeError(
            "E2E_TEST_LOGIN lets anyone sign in as any student. It only runs with a test database "
            "(DB_NAME starting traytrack_e2e/traytrack_test) on localhost. Remove it from this deployment."
        )

COOKIE_SECURE_FLAG = APP_BASE_URL.startswith("https://") if COOKIE_SECURE == "auto" else COOKIE_SECURE == "1"
