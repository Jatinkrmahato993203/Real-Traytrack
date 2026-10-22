"""
e2e_server.py — the backend as the browser tests need it: a brand-new
database, test sign-in enabled (no Google), no background jobs, no email.

    python scripts/e2e_server.py --port 8002 --frontend http://localhost:5175

Started automatically by frontend/playwright.config.js. Never point this at
a real database — it DROPS the one named by E2E_DB_NAME (default traytrack_e2e).
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8002)
parser.add_argument("--frontend", default="http://localhost:5175")
args = parser.parse_args()

db_name = os.environ.get("E2E_DB_NAME", "traytrack_e2e")
if not db_name.startswith(("traytrack_e2e", "traytrack_test")):
    sys.exit("Refusing to run: E2E_DB_NAME must start with traytrack_e2e (this script drops it).")

os.environ.update({
    "DB_NAME": db_name,
    "E2E_TEST_LOGIN": "1",
    "JOBS_ENABLED": "0",
    "FRONTEND_ORIGIN": args.frontend,
    "APP_BASE_URL": args.frontend,
    "SMTP_EMAIL": "",
    "SMTP_APP_PASSWORD": "",
    "MESS_ADMIN_EMAIL": "admin@e2e.test",
    "MESS_ADMIN_PASSWORD": "e2e-admin-pass",
    "RATE_LIMIT_SCALE": os.environ.get("RATE_LIMIT_SCALE", "20"),
    # Principals must use two-factor sign-in, so the browser tests exercise
    # the forced setup and the code step (the bootstrap admin is exempt).
    "REQUIRE_2FA_ROLES": "principal",
    "UPLOAD_DIR": tempfile.mkdtemp(prefix="traytrack-e2e-uploads-"),
    "LOG_DIR": tempfile.mkdtemp(prefix="traytrack-e2e-logs-"),
})

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import pymysql  # noqa: E402

conn = pymysql.connect(host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
                       password=config.DB_PASSWORD, autocommit=True)
with conn.cursor() as cur:
    cur.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
    cur.execute(f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4")
conn.close()

import uvicorn  # noqa: E402

uvicorn.run("main:app", host="127.0.0.1", port=args.port, log_level="warning")
