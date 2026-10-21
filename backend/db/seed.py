"""db/seed.py — first-start data and one-time back-fills."""

import json
import logging

from .core import transaction
from . import activity
from .colleges import new_kitchen_code
from .inspections import inspection_summary, _parse_responses

logger = logging.getLogger("traytrack")


def seed(bootstrap_admin_email, bootstrap_password_hash):
    with transaction() as cur:
        # A sample college so a fresh install has something to click on.
        cur.execute("SELECT COUNT(*) AS cnt FROM colleges")
        if cur.fetchone()["cnt"] == 0:
            cur.execute("INSERT INTO colleges (name, email_domain) VALUES (%s, %s)",
                        ("Sample Institute of Technology", "sample-college.edu"))
            college_id = cur.lastrowid
            for name in ("Mess A - North Block", "Mess B - South Block"):
                cur.execute("INSERT INTO mess_halls (college_id, name, kitchen_code) VALUES (%s, %s, %s)",
                            (college_id, name, new_kitchen_code()))

        # Every hall needs a kitchen code for inspector check-in.
        cur.execute("SELECT id FROM mess_halls WHERE kitchen_code IS NULL")
        for row in cur.fetchall():
            cur.execute("UPDATE mess_halls SET kitchen_code = %s WHERE id = %s", (new_kitchen_code(), row["id"]))

        # One all-colleges admin on an empty staff table, so an install can
        # always be logged into; real accounts are created from there.
        cur.execute("SELECT COUNT(*) AS cnt FROM staff_users")
        if cur.fetchone()["cnt"] == 0:
            from .core import now_iso
            cur.execute(
                "INSERT INTO staff_users (name, email, role, college_id, password_hash, active, created_at) "
                "VALUES ('Administrator', %s, 'admin', NULL, %s, 1, %s)",
                (bootstrap_admin_email.strip().lower(), bootstrap_password_hash, now_iso()),
            )
            logger.warning("Created bootstrap admin account %s (password = MESS_ADMIN_PASSWORD). "
                           "Change it in Admin Panel -> Staff.", bootstrap_admin_email)

        cur.execute("SELECT COUNT(*) AS cnt FROM activity_log")
        if cur.fetchone()["cnt"] == 0:
            _backfill_activity(cur)


def _backfill_activity(cur):
    """Installs that pre-date the activity log get their history imported,
    in chronological order, so the admin feed isn't blank."""
    events = []
    cur.execute("SELECT complaints.*, mess_halls.name AS mess_name FROM complaints "
                "JOIN mess_halls ON complaints.mess_id = mess_halls.id")
    events += [(c["created_at"], 0, "complaint", c) for c in cur.fetchall()]
    cur.execute("SELECT inspections.*, mess_halls.name AS mess_name FROM inspections "
                "JOIN mess_halls ON inspections.mess_id = mess_halls.id")
    events += [(i["created_at"], 0, "inspection", i) for i in cur.fetchall()]
    cur.execute("SELECT alert_history.*, alerts.mess_id, mess_halls.name AS mess_name FROM alert_history "
                "JOIN alerts ON alert_history.alert_id = alerts.id JOIN mess_halls ON alerts.mess_id = mess_halls.id")
    events += [(h["timestamp"], 1, "alert", h) for h in cur.fetchall()]
    events.sort(key=lambda e: (e[0], e[1]))
    if events:
        logger.info("Back-filling %d activity log entries from existing data", len(events))

    for ts, _, kind, row in events:
        ts = ts.strftime("%Y-%m-%d %H:%M:%S")
        if kind == "complaint":
            activity.log(
                cur, "complaint_submitted", f"Complaint #{row['id']}: {row['category']} — {row['mess_name']}",
                mess_id=row["mess_id"], college_id=row["college_id"], ref_id=row["id"],
                details={"category": row["category"], "description": row["description"],
                         "masked_email": activity.mask(row["student_email"]),
                         "photo_url": activity.complaint_photo_url(row["photo_path"])},
                ts=ts,
            )
        elif kind == "inspection":
            activity.log(
                cur, "inspection_submitted",
                f"Inspection #{row['id']} by {row['inspector_name']}: {row['score']}% — {row['mess_name']}",
                mess_id=row["mess_id"], ref_id=row["id"],
                details=inspection_summary(row["inspector_name"], _parse_responses(row["responses"]), row["score"]),
                ts=ts,
            )
        else:
            activity.log(
                cur, f"alert_{row['event']}",
                f"Alert #{row['alert_id']} {row['event']} at {row['level']} — {row['mess_name']}",
                mess_id=row["mess_id"], ref_id=row["alert_id"],
                details={"level": row["level"], "note": row["note"]}, ts=ts,
            )
