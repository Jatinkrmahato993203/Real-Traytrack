"""
db/alerts.py — alerts and their lifecycle.

status: open -> acknowledged -> in_progress -> fixed -> resolved
The legacy `resolved` flag is kept in sync (1 only when status = resolved)
so older queries and reports stay correct.
"""

from .core import transaction, fetch_all, fetch_one, now_iso, LEVELS
from . import activity

OPEN_STATUSES = ("open", "acknowledged", "in_progress", "fixed")

ALERT_SELECT = (
    "SELECT alerts.*, mess_halls.name AS mess_name, mess_halls.college_id AS college_id, "
    "colleges.name AS college_name, owner.name AS owner_name "
    "FROM alerts JOIN mess_halls ON alerts.mess_id = mess_halls.id "
    "JOIN colleges ON mess_halls.college_id = colleges.id "
    "LEFT JOIN staff_users owner ON alerts.owner_staff_id = owner.id "
)


def insert_alert(mess_id, source, source_id, level, reason, fssai_reference, pattern_key=None):
    ts = now_iso()
    with transaction() as cur:
        cur.execute(
            "INSERT INTO alerts (mess_id, source, source_id, level, reason, fssai_reference, pattern_key, "
            "created_at, last_escalated_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')",
            (mess_id, source, source_id, level, reason, fssai_reference, pattern_key, ts, ts),
        )
        alert_id = cur.lastrowid
        activity.alert_event(cur, "created", alert_id, level, reason, ts)
        return alert_id


def get_alert(alert_id):
    return fetch_one(ALERT_SELECT + "WHERE alerts.id = %s", (alert_id,))


def search_alerts(college_id=None, mess_id=None, statuses=None, level=None, resolved=None,
                  start_date=None, end_date=None, offset=0, limit=None):
    """Returns (rows, total)."""
    where, params = ["1=1"], []
    if college_id:
        where.append("mess_halls.college_id = %s")
        params.append(college_id)
    if mess_id:
        where.append("alerts.mess_id = %s")
        params.append(mess_id)
    if statuses:
        where.append("alerts.status IN (" + ", ".join(["%s"] * len(statuses)) + ")")
        params += list(statuses)
    if level:
        where.append("alerts.level = %s")
        params.append(level)
    if resolved is not None:
        where.append("alerts.resolved = %s")
        params.append(1 if resolved else 0)
    if start_date:
        where.append("DATE(alerts.created_at) >= %s")
        params.append(start_date)
    if end_date:
        where.append("DATE(alerts.created_at) <= %s")
        params.append(end_date)
    where_sql = " AND ".join(where)
    total = fetch_one(
        "SELECT COUNT(*) AS cnt FROM alerts JOIN mess_halls ON alerts.mess_id = mess_halls.id WHERE " + where_sql,
        params,
    )["cnt"]
    query = ALERT_SELECT + "WHERE " + where_sql + " ORDER BY alerts.created_at DESC, alerts.id DESC"
    if limit:
        query += " LIMIT %s OFFSET %s"
        params = params + [limit, offset]
    return fetch_all(query, params), total


def get_alerts(**filters):
    return search_alerts(**filters)[0]


def dashboard_summary(college_id):
    """One query for every hall's open-alert count and worst level (instead
    of one query per hall)."""
    return fetch_all(
        "SELECT mess_halls.id AS mess_id, "
        "SUM(alerts.id IS NOT NULL) AS open_count, "
        "MAX(CASE alerts.level WHEN 'High' THEN 3 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 1 ELSE 0 END) AS worst "
        "FROM mess_halls LEFT JOIN alerts ON alerts.mess_id = mess_halls.id AND alerts.resolved = 0 "
        "WHERE mess_halls.college_id = %s GROUP BY mess_halls.id",
        (college_id,),
    )


def alerts_with_category(college_id=None, start_date=None, end_date=None):
    query = (
        "SELECT alerts.id, alerts.level, alerts.status, alerts.resolved, alerts.source, alerts.created_at, "
        "alerts.resolved_at, mess_halls.name AS mess_name, complaints.category AS complaint_category "
        "FROM alerts JOIN mess_halls ON alerts.mess_id = mess_halls.id "
        "LEFT JOIN complaints ON alerts.source IN ('complaint', 'complaint_pattern') AND alerts.source_id = complaints.id "
        "WHERE 1=1"
    )
    params = []
    if college_id:
        query += " AND mess_halls.college_id = %s"
        params.append(college_id)
    if start_date:
        query += " AND DATE(alerts.created_at) >= %s"
        params.append(start_date)
    if end_date:
        query += " AND DATE(alerts.created_at) <= %s"
        params.append(end_date)
    return fetch_all(query + " ORDER BY alerts.created_at DESC", params)


def open_pattern_alert_exists(pattern_key):
    return fetch_one("SELECT 1 FROM alerts WHERE pattern_key = %s AND resolved = 0 LIMIT 1", (pattern_key,)) is not None


def last_pattern_resolution(pattern_key):
    row = fetch_one("SELECT MAX(resolved_at) AS ts FROM alerts WHERE pattern_key = %s AND resolved = 1", (pattern_key,))
    return row["ts"] if row else None


# ---------- Escalation & reminders (background jobs) ----------

def stale_alerts_for_escalation(days):
    """Unresolved, below High, and not moving: still open/acknowledged after
    `days`, or in progress past its due date. Fixed-awaiting-verification
    alerts don't escalate. UTC_TIMESTAMP() because stored times are UTC."""
    return fetch_all(
        "SELECT * FROM alerts WHERE resolved = 0 AND level != %s AND ("
        " (status IN ('open', 'acknowledged') AND last_escalated_at <= UTC_TIMESTAMP() - INTERVAL %s DAY)"
        " OR (status = 'in_progress' AND due_date IS NOT NULL AND due_date < UTC_DATE()"
        "     AND last_escalated_at <= UTC_TIMESTAMP() - INTERVAL %s DAY))",
        (LEVELS[-1], days, days),
    )


def escalate_alert(alert_id, new_level, note):
    ts = now_iso()
    with transaction() as cur:
        cur.execute("UPDATE alerts SET level = %s, last_escalated_at = %s WHERE id = %s", (new_level, ts, alert_id))
        activity.alert_event(cur, "escalated", alert_id, new_level, note, ts)


def high_alerts_needing_reminder(every_days):
    """High is the top of the chain, so instead of escalating further, an
    unresolved High alert keeps generating reminders."""
    return fetch_all(
        "SELECT * FROM alerts WHERE resolved = 0 AND level = 'High' AND status != 'fixed' "
        "AND last_escalated_at <= UTC_TIMESTAMP() - INTERVAL %s DAY "
        "AND (last_reminder_at IS NULL OR last_reminder_at <= UTC_TIMESTAMP() - INTERVAL %s DAY)",
        (every_days, every_days),
    )


def mark_reminded(alert_id, level, note):
    ts = now_iso()
    with transaction() as cur:
        cur.execute("UPDATE alerts SET last_reminder_at = %s WHERE id = %s", (ts, alert_id))
        activity.alert_event(cur, "reminder", alert_id, level, note, ts)


# ---------- Workflow ----------

def set_status(alert_id, new_status, note, actor, expected_from=None):
    """Moves an alert to new_status if it's currently in one of
    expected_from. Returns False when it wasn't (stale UI / double click)."""
    ts = now_iso()
    with transaction() as cur:
        sql = "UPDATE alerts SET status = %s"
        params = [new_status]
        if new_status == "resolved":
            sql += ", resolved = 1, resolved_at = %s, resolution_notes = %s, resolved_by_staff_id = %s"
            params += [ts, note, actor["id"] if actor else None]
        sql += " WHERE id = %s"
        params.append(alert_id)
        if expected_from:
            sql += " AND status IN (" + ", ".join(["%s"] * len(expected_from)) + ")"
            params += list(expected_from)
        cur.execute(sql, params)
        if not cur.rowcount:
            return False
        cur.execute("SELECT level FROM alerts WHERE id = %s", (alert_id,))
        level = cur.fetchone()["level"]
        event = {"resolved": "resolved"}.get(new_status, new_status)
        by = actor["name"] if actor else "students"
        activity.alert_event(cur, event, alert_id, level, f"By {by}: {note}" if note else f"By {by}", ts, actor)
        return True


def reopen(alert_id, note, actor):
    ts = now_iso()
    with transaction() as cur:
        cur.execute(
            "UPDATE alerts SET status = 'open', resolved = 0, resolved_at = NULL, last_escalated_at = %s, "
            "reopened_count = reopened_count + 1 WHERE id = %s AND status = 'resolved'",
            (ts, alert_id),
        )
        if not cur.rowcount:
            return False
        cur.execute("SELECT level FROM alerts WHERE id = %s", (alert_id,))
        activity.alert_event(cur, "reopened", alert_id, cur.fetchone()["level"],
                             f"By {actor['name']}: {note}", ts, actor)
        return True


def assign(alert_id, owner_staff_id, due_date, actor):
    with transaction() as cur:
        cur.execute("UPDATE alerts SET owner_staff_id = %s, due_date = %s WHERE id = %s",
                    (owner_staff_id, due_date, alert_id))
        cur.execute(
            "SELECT alerts.level, staff_users.name AS owner_name FROM alerts "
            "LEFT JOIN staff_users ON staff_users.id = %s WHERE alerts.id = %s",
            (owner_staff_id, alert_id),
        )
        row = cur.fetchone()
        note = f"Owner: {row['owner_name'] or 'nobody'}; due {due_date or 'not set'}"
        activity.alert_event(cur, "assigned", alert_id, row["level"], f"By {actor['name']}: {note}", None, actor)


def add_evidence(alert_id, kind, note, actor, photo_path=None, inspection_id=None):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO alert_evidence (alert_id, kind, note, photo_path, inspection_id, staff_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (alert_id, kind, note, photo_path, inspection_id, actor["id"] if actor else None, now_iso()),
        )
        return cur.lastrowid


def list_evidence(alert_id):
    return fetch_all(
        "SELECT alert_evidence.*, staff_users.name AS staff_name FROM alert_evidence "
        "LEFT JOIN staff_users ON alert_evidence.staff_id = staff_users.id "
        "WHERE alert_id = %s ORDER BY alert_evidence.id",
        (alert_id,),
    )


def has_evidence(alert_id):
    """Proof that a fix happened: a photo or a follow-up inspection."""
    return fetch_one(
        "SELECT 1 FROM alert_evidence WHERE alert_id = %s AND (photo_path IS NOT NULL OR inspection_id IS NOT NULL) LIMIT 1",
        (alert_id,),
    ) is not None


def history(alert_id):
    return fetch_all(
        "SELECT alert_history.*, staff_users.name AS actor_name FROM alert_history "
        "LEFT JOIN staff_users ON alert_history.actor_staff_id = staff_users.id "
        "WHERE alert_id = %s ORDER BY alert_history.id",
        (alert_id,),
    )


def get_evidence_by_photo(filename):
    return fetch_one(
        "SELECT alert_evidence.alert_id, mess_halls.college_id, alerts.mess_id FROM alert_evidence "
        "JOIN alerts ON alert_evidence.alert_id = alerts.id JOIN mess_halls ON alerts.mess_id = mess_halls.id "
        "WHERE alert_evidence.photo_path LIKE %s",
        ("%" + filename,),
    )
