"""
db/activity.py — the append-only activity log behind the Admin Panel's live
feed. Writers pass their own cursor so a log row commits (or rolls back)
together with the change it describes.
"""

import json
import logging
import os

from .core import transaction, fetch_all, now_iso

logger = logging.getLogger("traytrack.activity")


def mask(email):
    from auth import mask_email
    return mask_email(email)


def complaint_photo_url(photo_path):
    """Photos are only served through the staff-authenticated endpoint,
    never as public static files."""
    return f"/staff/photos/{os.path.basename(photo_path)}" if photo_path else None


def log(cur, event_type, summary, mess_id=None, college_id=None, ref_id=None, details=None, ts=None):
    """Never put a raw student email in summary/details — use mask()."""
    if college_id is None and mess_id is not None:
        cur.execute("SELECT college_id FROM mess_halls WHERE id = %s", (mess_id,))
        row = cur.fetchone()
        college_id = row["college_id"] if row else None
    cur.execute(
        "INSERT INTO activity_log (event_type, college_id, mess_id, ref_id, summary, details, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (event_type, college_id, mess_id, ref_id, summary[:500],
         json.dumps(details or {}, default=str), ts or now_iso()),
    )
    logger.info("[%s] %s", event_type, summary)


def log_activity(event_type, summary, mess_id=None, college_id=None, ref_id=None, details=None):
    """Standalone version for events that don't write anything else."""
    with transaction() as cur:
        log(cur, event_type, summary, mess_id, college_id, ref_id, details)


def alert_event(cur, event, alert_id, level, note, ts=None, actor=None):
    """Writes both alert_history and the activity log for an alert change."""
    from fssai_rules import get_authority
    ts = ts or now_iso()
    cur.execute(
        "INSERT INTO alert_history (alert_id, event, level, note, timestamp, actor_staff_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (alert_id, event, level, note, ts, actor["id"] if actor else None),
    )
    cur.execute(
        "SELECT alerts.mess_id, alerts.source, mess_halls.name AS mess_name FROM alerts "
        "JOIN mess_halls ON alerts.mess_id = mess_halls.id WHERE alerts.id = %s",
        (alert_id,),
    )
    a = cur.fetchone()
    verbs = {
        "created": "raised at", "escalated": "escalated to", "resolved": "resolved at",
        "acknowledged": "acknowledged at", "in_progress": "being worked on at", "fixed": "marked fixed at",
        "reopened": "reopened at", "fix_rejected": "fix rejected at", "assigned": "assigned at",
        "reminder": "reminder sent at",
    }
    log(
        cur, f"alert_{event}",
        f"Alert #{alert_id} {verbs.get(event, event)} {level} — {a['mess_name'] if a else 'unknown mess'}",
        mess_id=a["mess_id"] if a else None, ref_id=alert_id,
        details={"level": level, "note": note, "authority": get_authority(level),
                 "source": a["source"] if a else None, **({"actor": actor["name"]} if actor else {})},
        ts=ts,
    )


def get_activity(after_id=None, before_id=None, college_id=None, mess_id=None, event_type=None,
                 limit=100, only_prefixes=None):
    """after_id → rows newer than that, oldest first (live updates);
    otherwise newest first, before_id paging back."""
    query = (
        "SELECT activity_log.*, mess_halls.name AS mess_name, colleges.name AS college_name "
        "FROM activity_log "
        "LEFT JOIN mess_halls ON activity_log.mess_id = mess_halls.id "
        "LEFT JOIN colleges ON activity_log.college_id = colleges.id WHERE 1=1"
    )
    params = []
    if after_id is not None:
        query += " AND activity_log.id > %s"
        params.append(after_id)
    if before_id is not None:
        query += " AND activity_log.id < %s"
        params.append(before_id)
    if college_id:
        query += " AND activity_log.college_id = %s"
        params.append(college_id)
    if mess_id:
        query += " AND activity_log.mess_id = %s"
        params.append(mess_id)
    if event_type:
        query += " AND activity_log.event_type LIKE %s"
        params.append(event_type + "%")
    if only_prefixes:
        query += " AND (" + " OR ".join("activity_log.event_type LIKE %s" for _ in only_prefixes) + ")"
        params.extend(p + "%" for p in only_prefixes)
    order = "ASC" if after_id is not None and before_id is None else "DESC"
    query += f" ORDER BY activity_log.id {order} LIMIT %s"
    params.append(limit)
    rows = fetch_all(query, params)
    for r in rows:
        r["details"] = json.loads(r["details"]) if r["details"] else {}
    return rows


def latest_activity_id():
    rows = fetch_all("SELECT COALESCE(MAX(id), 0) AS id FROM activity_log")
    return rows[0]["id"]
