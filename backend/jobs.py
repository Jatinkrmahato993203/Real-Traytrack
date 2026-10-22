"""
jobs.py — background work that must happen even when nobody opens the app.

One scheduler thread per server process wakes every few minutes. Each job
takes a MySQL named lock and records its last run in `job_runs`, so with
several workers (or several servers) a job still runs once per period.

  escalation          hourly   — stale alerts move up the authority chain
  high_reminders      6-hourly — unresolved High alerts nag every 3 days
  compliance          daily    — licences/certificates nearing expiry
  retention           daily    — anonymize student data past RETENTION_DAYS
  weekly_digest       weekly   — Monday 9:00 local summary to each principal
  backup              nightly  — BACKUP_HOUR local (if BACKUPS_ENABLED=1), verified

A job that raises, or a backup that fails, sends an ops alert (ops.py).
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import os

import alert_engine
import backups
import config
import db
import notify
import ops

logger = logging.getLogger("traytrack.jobs")
TICK_SECONDS = 300


def _due(name, every):
    last = db.security.last_job_run(name)
    return last is None or db.utcnow() - last >= every


def _local_now():
    return datetime.now(timezone.utc).astimezone(ZoneInfo(config.LOCAL_TZ))


def _weekly_digest_due():
    """Monday 9:00 local time, once per week."""
    now = _local_now()
    if now.weekday() != 0 or now.hour < 9:
        return False
    last = db.security.last_job_run("weekly_digest")
    if last is None:
        return True
    last_local = last.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(config.LOCAL_TZ))
    return last_local.isocalendar()[:2] != now.isocalendar()[:2]


def compliance_reminders():
    sent = 0
    for doc in db.compliance.due_reminders():
        college = db.get_college(doc["college_id"])
        when = "has EXPIRED" if doc["days_left"] < 0 else (
            "expires today" if doc["days_left"] == 0 else f"expires in {doc['days_left']} days")
        subject = f"[TrayTrack] Compliance: {doc['title']} {when}"
        body = (f"Hello,\n\n{doc['title']} ({db.compliance.DOC_TYPES.get(doc['doc_type'])})"
                f"{' for ' + doc['person_name'] if doc.get('person_name') else ''}"
                f"{' at ' + doc['mess_name'] if doc.get('mess_name') else ''}, {doc['college_name']}, "
                f"{when} ({doc['expires_on']}).\n\nPlease renew it and update the record: "
                f"{config.APP_BASE_URL}/admin/compliance\n")
        for role in ("mess_head", "principal"):
            notify.send("compliance_expiry", college.get(notify.CONTACT_COLUMN[role]), subject, body,
                        doc["college_id"], recipient_role=role)
        db.compliance.mark_reminded(doc["id"], doc["window"])
        sent += 1
    return sent


def weekly_digest():
    week_ago = db.to_db(db.utcnow() - timedelta(days=7))
    sent = 0
    for college in db.list_colleges():
        complaints = db.get_complaints_since(college["id"], week_ago)
        by_category = {}
        for c in complaints:
            by_category[c["category"]] = by_category.get(c["category"], 0) + 1
        open_alerts, _ = db.search_alerts(college_id=college["id"], resolved=False)
        today = db.utcnow().date()
        overdue = [o for o in db.overview(college["id"])
                   if o["last_inspected_at"] is None
                   or min(d for d in (o["scheduled_due"], o["interval_due"]) if d) < today]
        expiring = db.compliance.list_documents(college["id"], expiring_within_days=30)
        per_mess, _ = db.rating_summary(college["id"], (db.utcnow() - timedelta(days=7)).date())
        halls = {m["id"]: m["name"] for m in db.list_mess_halls(college["id"])}
        lines = [f"TrayTrack weekly summary — {college['name']}", ""]
        lines.append(f"Complaints this week: {len(complaints)}")
        lines += [f"  • {cat}: {n}" for cat, n in sorted(by_category.items(), key=lambda x: -x[1])]
        lines.append(f"\nOpen alerts: {len(open_alerts)}")
        lines += [f"  • #{a['id']} {a['level']} at {a['mess_name']} — {a['status'].replace('_', ' ')}" for a in open_alerts[:15]]
        lines.append(f"\nInspections overdue: {len(overdue)}")
        lines += [f"  • {o['mess_name']} (last: {o['last_inspected_at'] or 'never'})" for o in overdue]
        lines.append(f"\nCompliance records expiring within 30 days: {len(expiring)}")
        lines += [f"  • {d['title']} — {d['expires_on']}" for d in expiring]
        if per_mess:
            lines.append("\nAverage meal rating this week:")
            lines += [f"  • {halls.get(r['mess_id'], r['mess_id'])}: {r['avg_stars']}★ ({r['ratings']} ratings)" for r in per_mess]
        lines.append(f"\nOpen the dashboard: {config.APP_BASE_URL}/admin")
        notify.send("weekly_digest", college.get("principal_email"),
                    f"[TrayTrack] Weekly summary — {college['name']}", "\n".join(lines), college["id"],
                    recipient_role="principal")
        sent += 1
    return sent


def retention():
    """Privacy retention plus housekeeping of tables that only grow."""
    photos, ratings = db.apply_retention(config.RETENTION_DAYS)
    sessions = db.sessions.purge_old()
    limits = db.security.purge_rate_limits()
    _, trimmed = db.execute("DELETE FROM activity_log WHERE created_at < UTC_TIMESTAMP() - INTERVAL %s DAY",
                            (config.ACTIVITY_RETENTION_DAYS,))
    return (f"{photos} photos deleted, {ratings} ratings anonymized, {sessions} old sessions, "
            f"{limits} rate-limit rows, {trimmed} activity rows trimmed")


BACKUPS_ENABLED = os.environ.get("BACKUPS_ENABLED", "0") == "1"
BACKUP_HOUR = int(os.environ.get("BACKUP_HOUR", "2"))       # local time
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "30"))


def _backup_due():
    if not BACKUPS_ENABLED or _local_now().hour < BACKUP_HOUR:
        return False
    last = db.security.last_job_run("backup")
    if last is None:
        return True
    last_local = last.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(config.LOCAL_TZ))
    return last_local.date() != _local_now().date()


def nightly_backup():
    try:
        sql_path, zip_path = backups.run_backup(keep=BACKUP_KEEP)
    except Exception as e:
        ops.alert("backup_failed", f"Nightly backup failed: {e}")
        raise
    return f"{sql_path.name} ({sql_path.stat().st_size // 1024} KB, verified)" + (", photos zipped" if zip_path else "")


JOBS = [
    ("escalation", lambda: _due("escalation", timedelta(hours=1)), alert_engine.escalate_stale_alerts),
    ("high_reminders", lambda: _due("high_reminders", timedelta(hours=6)), alert_engine.remind_high_alerts),
    ("compliance", lambda: _due("compliance", timedelta(days=1)), compliance_reminders),
    ("retention", lambda: _due("retention", timedelta(days=1)), retention),
    ("weekly_digest", _weekly_digest_due, weekly_digest),
    ("backup", _backup_due, nightly_backup),
]

# /health reports "degraded" (503) if a job that should run often hasn't —
# the sign the scheduler itself has died.
STALE_AFTER = {"escalation": timedelta(hours=3), "high_reminders": timedelta(hours=13)}


def stale_jobs():
    if not config.JOBS_ENABLED:
        return []
    runs = {r["job_name"]: r["last_run_at"] for r in db.security.all_job_runs()}
    now = db.utcnow()
    started = _started_at or now
    return [name for name, limit in STALE_AFTER.items()
            if now - (runs.get(name) or started) > limit and now - started > limit]


def run_due_jobs():
    for name, is_due, fn in JOBS:
        try:
            if not is_due():
                continue
            with db.security.job_lock(name) as got:
                if not got or not is_due():  # another worker has it / just did it
                    continue
                result = fn()
                db.security.record_job_run(name, result)
                logger.info("Job %s finished: %s", name, result)
        except Exception as e:
            logger.exception("Job %s failed", name)
            ops.alert(f"job_{name}_failed", f"Background job '{name}' failed: {e!r}")


def _loop():
    time.sleep(5)  # let the app finish starting
    while True:
        run_due_jobs()
        time.sleep(TICK_SECONDS)


_started = False
_started_at = None


def start():
    global _started, _started_at
    if config.JOBS_ENABLED and not _started:
        _started = True
        _started_at = db.utcnow()
        threading.Thread(target=_loop, name="traytrack-jobs", daemon=True).start()
