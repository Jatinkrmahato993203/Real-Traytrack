"""
db/notifications.py — a record of every notification attempt, sent or not.

This is what lets the app be honest: the public dashboard only says an
authority was notified when an email was actually delivered, and admins
can see exactly which contacts are missing or failing.
"""

from .core import transaction, fetch_all, fetch_one, now_iso

# sent | skipped_no_contact | skipped_no_smtp | failed
DELIVERED = "sent"


def record(kind, status, college_id=None, alert_id=None, recipient_role=None, recipient_email=None,
           subject=None, error=None):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO notifications (college_id, alert_id, kind, recipient_role, recipient_email, subject, "
            "status, error, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (college_id, alert_id, kind, recipient_role, recipient_email, subject, status,
             (error or "")[:2000] or None, now_iso()),
        )


def list_notifications(college_id=None, alert_id=None, status=None, offset=0, limit=50):
    where, params = ["1=1"], []
    for clause, value in (("n.college_id = %s", college_id), ("n.alert_id = %s", alert_id), ("n.status = %s", status)):
        if value:
            where.append(clause)
            params.append(value)
    base = "FROM notifications n LEFT JOIN colleges ON n.college_id = colleges.id WHERE " + " AND ".join(where)
    total = fetch_one(f"SELECT COUNT(*) AS cnt {base}", params)["cnt"]
    rows = fetch_all(f"SELECT n.*, colleges.name AS college_name {base} ORDER BY n.id DESC LIMIT %s OFFSET %s",
                     params + [limit, offset])
    return rows, total


def delivery_by_alert(alert_ids):
    """{alert_id: True if any notification for it was delivered}."""
    if not alert_ids:
        return {}
    rows = fetch_all(
        "SELECT alert_id, MAX(status = 'sent') AS delivered FROM notifications WHERE alert_id IN ("
        + ", ".join(["%s"] * len(alert_ids)) + ") GROUP BY alert_id",
        list(alert_ids),
    )
    return {r["alert_id"]: bool(r["delivered"]) for r in rows}


def recent_failures(college_id=None, days=7):
    query = ("SELECT COUNT(*) AS cnt FROM notifications WHERE status != 'sent' "
             "AND created_at >= UTC_TIMESTAMP() - INTERVAL %s DAY")
    params = [days]
    if college_id:
        query += " AND college_id = %s"
        params.append(college_id)
    return fetch_one(query, params)["cnt"]
