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

# --- Auth ---
TOKEN_SECRET = os.environ.get("ADMIN_TOKEN_SECRET", "dev-secret-change-me")
STAFF_TOKEN_HOURS = _int("STAFF_TOKEN_HOURS", 8)
STUDENT_TOKEN_DAYS = _int("STUDENT_TOKEN_DAYS", 7)
BOOTSTRAP_ADMIN_EMAIL = os.environ.get("MESS_ADMIN_EMAIL", "admin@traytrack.local")
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("MESS_ADMIN_PASSWORD", "changeme123")

# --- Email (optional — without it, notifications are recorded as skipped) ---
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)

# --- Privacy ---
# Student identity (email, name) on complaints/ratings is irreversibly
# anonymized after this many days; their photos are deleted.
RETENTION_DAYS = _int("RETENTION_DAYS", 365)
PRIVACY_NOTICE_VERSION = "2026-10"

# --- Files ---
UPLOAD_ROOT = Path(os.environ.get("UPLOAD_DIR", BASE_DIR / "uploads"))
LOG_DIR = Path(os.environ.get("LOG_DIR", BASE_DIR / "logs"))

# --- Background jobs (escalation, reminders, digests, retention) ---
JOBS_ENABLED = os.environ.get("JOBS_ENABLED", "1") != "0"
# Local timezone for "Monday 9 AM" style schedules and for email text.
LOCAL_TZ = os.environ.get("LOCAL_TZ", "Asia/Kolkata")

# --- Optional error tracking ---
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
