"""
ops.py — telling the people who run TrayTrack that something is wrong.

alert() sends to OPS_ALERT_EMAIL and/or OPS_WEBHOOK_URL (any service that
accepts {"text": "..."} — Slack, Discord via /slack, Google Chat, ntfy…).
Each kind of problem alerts at most once per OPS_ALERT_COOLDOWN_MINUTES, so
an outage produces one message, not hundreds. Every alert is also written
to the notifications table, which is what the cooldown checks.

What triggers alerts:
  * a background job raising an error (jobs.py)
  * a backup that fails or produces an unusable dump (jobs.py)
  * a burst of server errors (main.py middleware → error_burst())
What can't alert from inside (the whole server down, the scheduler thread
dead): point an external uptime monitor at /health, which returns 503 for
those — see README "Monitoring".
"""

import json
import logging
import os
import threading
import time
import urllib.request
from collections import deque

import config
import db

logger = logging.getLogger("traytrack.ops")

OPS_ALERT_EMAIL = os.environ.get("OPS_ALERT_EMAIL", "")
OPS_WEBHOOK_URL = os.environ.get("OPS_WEBHOOK_URL", "")
COOLDOWN_MINUTES = int(os.environ.get("OPS_ALERT_COOLDOWN_MINUTES", "60"))
ERROR_BURST = int(os.environ.get("OPS_ERROR_BURST", "10"))          # server errors...
ERROR_WINDOW_SECONDS = 300                                            # ...within 5 minutes


def configured():
    return bool(OPS_ALERT_EMAIL or OPS_WEBHOOK_URL)


def _recently_alerted(kind):
    row = db.fetch_one(
        "SELECT 1 FROM notifications WHERE kind = %s AND created_at >= UTC_TIMESTAMP() - INTERVAL %s MINUTE LIMIT 1",
        (f"ops_{kind}", COOLDOWN_MINUTES),
    )
    return row is not None


def alert(kind, message):
    """Best effort; never raises."""
    try:
        logger.error("OPS ALERT [%s] %s", kind, message)
        if _recently_alerted(kind):
            return False
        subject = f"[TrayTrack ops] {kind.replace('_', ' ')}"
        text = f"{subject}\n{message}\nSite: {config.APP_BASE_URL}"
        delivered = False
        if OPS_WEBHOOK_URL:
            try:
                req = urllib.request.Request(OPS_WEBHOOK_URL, data=json.dumps({"text": text}).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=10).close()
                delivered = True
                db.notifications.record(f"ops_{kind}", "sent", recipient_role="ops_webhook", subject=subject)
            except Exception as e:
                db.notifications.record(f"ops_{kind}", "failed", recipient_role="ops_webhook", subject=subject, error=str(e))
        if OPS_ALERT_EMAIL:
            import notify
            delivered = notify.send(f"ops_{kind}", OPS_ALERT_EMAIL, subject, text, recipient_role="ops") or delivered
        if not configured():
            db.notifications.record(f"ops_{kind}", "skipped_no_contact", recipient_role="ops", subject=subject,
                                    error="Set OPS_ALERT_EMAIL or OPS_WEBHOOK_URL")
        return delivered
    except Exception:
        logger.exception("Could not send ops alert")
        return False


# ---------- Server-error bursts (fed by the request middleware) ----------

_errors = deque()
_lock = threading.Lock()


def record_server_error(path):
    now = time.monotonic()
    with _lock:
        _errors.append(now)
        while _errors and now - _errors[0] > ERROR_WINDOW_SECONDS:
            _errors.popleft()
        burst = len(_errors) >= ERROR_BURST
        if burst:
            _errors.clear()
    if burst:
        threading.Thread(target=alert, args=(
            "error_burst", f"{ERROR_BURST}+ server errors in {ERROR_WINDOW_SECONDS // 60} minutes (latest: {path}). "
                           "Check the logs (LOG_DIR/traytrack.log) for the request ids."), daemon=True).start()
