"""
db/inspections.py — the checklist (per college, editable), inspections with
per-item results/notes/photos, on-site verification, and the schedule.
"""

import json
import os
import re
from datetime import timedelta

from .core import transaction, fetch_all, fetch_one, now_iso
from . import activity




# ---------- Checklist ----------

def get_checklist(college_id, include_inactive=False):
    """A college's own checklist if it has one, otherwise the default."""
    has_own = college_id and fetch_one(
        "SELECT 1 FROM checklist_items WHERE college_id = %s LIMIT 1", (college_id,)
    )
    query = "SELECT * FROM checklist_items WHERE " + ("college_id = %s" if has_own else "college_id IS NULL")
    params = [college_id] if has_own else []
    if not include_inactive:
        query += " AND active = 1"
    rows = fetch_all(query + " ORDER BY sort_order, id", params)
    for r in rows:
        r["critical"] = bool(r["critical"])
        r["active"] = bool(r["active"])
        r["is_default"] = not has_own
    return rows


def customize_checklist(college_id):
    """Copies the default checklist into a college-specific one (first edit)."""
    with transaction() as cur:
        cur.execute("SELECT 1 FROM checklist_items WHERE college_id = %s LIMIT 1", (college_id,))
        if cur.fetchone():
            return
        cur.execute(
            "INSERT INTO checklist_items (college_id, item_key, text, critical, sort_order, active) "
            "SELECT %s, item_key, text, critical, sort_order, active FROM checklist_items WHERE college_id IS NULL",
            (college_id,),
        )


def _slug(text):
    return (re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "item")[:50]


def add_checklist_item(college_id, text, critical):
    customize_checklist(college_id)
    with transaction() as cur:
        cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM checklist_items WHERE college_id = %s", (college_id,))
        order = cur.fetchone()["n"]
        key = _slug(text)
        cur.execute("SELECT COUNT(*) AS cnt FROM checklist_items WHERE college_id = %s AND item_key LIKE %s",
                    (college_id, key + "%"))
        if cur.fetchone()["cnt"]:
            key = f"{key}_{order}"
        cur.execute(
            "INSERT INTO checklist_items (college_id, item_key, text, critical, sort_order, active) "
            "VALUES (%s, %s, %s, %s, %s, 1)",
            (college_id, key, text.strip(), 1 if critical else 0, order),
        )
        return cur.lastrowid


def update_checklist_item(college_id, item_id, text=None, critical=None, active=None):
    customize_checklist(college_id)
    # The id may refer to the default row the admin was looking at; map it
    # to the college's copy by item_key.
    item = fetch_one("SELECT item_key FROM checklist_items WHERE id = %s", (item_id,))
    if not item:
        return False
    sets, params = [], []
    for col, val in (("text", text), ("critical", critical), ("active", active)):
        if val is not None:
            sets.append(f"{col} = %s")
            params.append(val.strip() if col == "text" else (1 if val else 0))
    if not sets:
        return True
    with transaction() as cur:
        cur.execute(
            f"UPDATE checklist_items SET {', '.join(sets)} WHERE college_id = %s AND item_key = %s",
            params + [college_id, item["item_key"]],
        )
        return cur.rowcount > 0


# ---------- Inspections ----------

def find_by_client_ref(client_ref):
    return fetch_one("SELECT id FROM inspections WHERE client_ref = %s", (client_ref,)) if client_ref else None


def insert_inspection(mess_id, staff, normalized, score, general_notes=None, verified_onsite=False,
                      latitude=None, longitude=None, client_ref=None):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO inspections (mess_id, inspector_name, inspector_id, responses, score, general_notes, "
            "verified_onsite, latitude, longitude, client_ref, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (mess_id, staff["name"], staff["id"], json.dumps(normalized), score, general_notes,
             1 if verified_onsite else 0, latitude, longitude, client_ref, now_iso()),
        )
        inspection_id = cur.lastrowid
        # Close the earliest open scheduled inspection for this hall.
        cur.execute(
            "UPDATE inspection_schedule SET completed_inspection_id = %s WHERE mess_id = %s "
            "AND completed_inspection_id IS NULL ORDER BY due_date LIMIT 1",
            (inspection_id, mess_id),
        )
        cur.execute("SELECT name FROM mess_halls WHERE id = %s", (mess_id,))
        mess = cur.fetchone()
        activity.log(
            cur, "inspection_submitted",
            f"Inspection #{inspection_id} by {staff['name']}: {score}% — {mess['name'] if mess else mess_id}",
            mess_id=mess_id, ref_id=inspection_id,
            details=inspection_summary(staff["name"], normalized, score, verified_onsite),
        )
        return inspection_id


def inspection_summary(inspector_name, normalized, score, verified_onsite=False):
    failed = [{"text": r["text"], "critical": r["critical"], "note": r.get("note", "")}
              for r in normalized.values() if r["result"] == "fail"]
    applicable = [r for r in normalized.values() if r["result"] != "na"]
    return {"inspector_name": inspector_name, "score": score, "failed_items": failed,
            "passed": len(applicable) - len(failed), "total": len(applicable),
            "na": len(normalized) - len(applicable), "verified_onsite": bool(verified_onsite)}


def _parse_responses(raw):
    data = json.loads(raw) if isinstance(raw, str) else raw
    # Older inspections stored {item_id: bool}.
    return {k: (v if isinstance(v, dict) else {"result": "pass" if v else "fail", "note": "", "text": k, "critical": False})
            for k, v in data.items()}


def add_inspection_photo(inspection_id, item_key, photo_path):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO inspection_photos (inspection_id, item_key, photo_path, file_name, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (inspection_id, item_key, photo_path, os.path.basename(photo_path), now_iso()),
        )
        return cur.lastrowid


def list_inspections(college_id=None, mess_id=None, inspector_id=None, offset=0, limit=50):
    where, params = ["1=1"], []
    for clause, value in (("mess_halls.college_id = %s", college_id), ("inspections.mess_id = %s", mess_id),
                          ("inspections.inspector_id = %s", inspector_id)):
        if value:
            where.append(clause)
            params.append(value)
    base = "FROM inspections JOIN mess_halls ON inspections.mess_id = mess_halls.id WHERE " + " AND ".join(where)
    total = fetch_one(f"SELECT COUNT(*) AS cnt {base}", params)["cnt"]
    rows = fetch_all(
        f"SELECT inspections.*, mess_halls.name AS mess_name, mess_halls.college_id {base} "
        "ORDER BY inspections.created_at DESC, inspections.id DESC LIMIT %s OFFSET %s",
        params + [limit, offset],
    )
    for r in rows:
        r["summary"] = inspection_summary(r["inspector_name"], _parse_responses(r.pop("responses")), r["score"],
                                          r["verified_onsite"])
    return rows, total


def get_inspection(inspection_id):
    row = fetch_one(
        "SELECT inspections.*, mess_halls.name AS mess_name, mess_halls.college_id FROM inspections "
        "JOIN mess_halls ON inspections.mess_id = mess_halls.id WHERE inspections.id = %s",
        (inspection_id,),
    )
    if not row:
        return None
    row["responses"] = _parse_responses(row["responses"])
    row["photos"] = fetch_all(
        "SELECT id, item_key, photo_path FROM inspection_photos WHERE inspection_id = %s ORDER BY id", (inspection_id,)
    )
    return row


def get_inspection_by_photo(filename):
    return fetch_one(
        "SELECT inspection_photos.inspection_id, mess_halls.college_id, inspections.mess_id FROM inspection_photos "
        "JOIN inspections ON inspection_photos.inspection_id = inspections.id "
        "JOIN mess_halls ON inspections.mess_id = mess_halls.id WHERE inspection_photos.file_name = %s",
        (filename,),
    )


def latest_by_mess(college_id):
    """Last inspection date + score per hall, for dashboards."""
    return fetch_all(
        "SELECT i.mess_id, i.score, i.created_at FROM inspections i "
        "JOIN (SELECT mess_id, MAX(id) AS max_id FROM inspections GROUP BY mess_id) last ON last.max_id = i.id "
        "JOIN mess_halls ON i.mess_id = mess_halls.id WHERE mess_halls.college_id = %s",
        (college_id,),
    )


def overview(college_id=None, mess_id=None):
    """Per hall: last inspection, scheduled date and the regular-interval due
    date (the college's inspection_interval_days setting) — the inspector's
    to-do list."""
    from .colleges import get_college_settings
    where, params = ["1=1"], []
    if college_id:
        where.append("m.college_id = %s")
        params.append(college_id)
    if mess_id:
        where.append("m.id = %s")
        params.append(mess_id)
    rows = fetch_all(
        "SELECT m.id AS mess_id, m.name AS mess_name, m.college_id, c.name AS college_name, "
        "  (SELECT MAX(created_at) FROM inspections WHERE mess_id = m.id) AS last_inspected_at, "
        "  (SELECT score FROM inspections WHERE mess_id = m.id ORDER BY id DESC LIMIT 1) AS last_score, "
        "  (SELECT MIN(due_date) FROM inspection_schedule WHERE mess_id = m.id AND completed_inspection_id IS NULL) AS scheduled_due "
        "FROM mess_halls m JOIN colleges c ON m.college_id = c.id WHERE " + " AND ".join(where) +
        " ORDER BY c.name, m.name",
        params,
    )
    intervals = {}
    for r in rows:
        days = intervals.setdefault(r["college_id"], get_college_settings(r["college_id"])["inspection_interval_days"])
        # None for a hall that has never been inspected — it's due now.
        r["interval_due"] = (r["last_inspected_at"] + timedelta(days=days)).date() if r["last_inspected_at"] else None
    return rows


# ---------- Schedule ----------

def add_schedule(mess_id, due_date, assigned_staff_id, notes, actor):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO inspection_schedule (mess_id, due_date, assigned_staff_id, notes, created_by_staff_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (mess_id, due_date, assigned_staff_id, notes, actor["id"], now_iso()),
        )
        schedule_id = cur.lastrowid
        cur.execute("SELECT name FROM mess_halls WHERE id = %s", (mess_id,))
        activity.log(cur, "inspection_scheduled",
                     f"{actor['name']} scheduled an inspection of {cur.fetchone()['name']} by {due_date}",
                     mess_id=mess_id, ref_id=schedule_id, details={"actor": actor["name"], "due_date": str(due_date)})
        return schedule_id


def list_schedule(college_id=None, mess_id=None, assigned_staff_id=None, include_done=False):
    where, params = ["1=1"], []
    for clause, value in (("mess_halls.college_id = %s", college_id), ("s.mess_id = %s", mess_id),
                          ("s.assigned_staff_id = %s", assigned_staff_id)):
        if value:
            where.append(clause)
            params.append(value)
    if not include_done:
        where.append("s.completed_inspection_id IS NULL")
    return fetch_all(
        "SELECT s.*, mess_halls.name AS mess_name, mess_halls.college_id, staff_users.name AS assigned_name "
        "FROM inspection_schedule s JOIN mess_halls ON s.mess_id = mess_halls.id "
        "LEFT JOIN staff_users ON s.assigned_staff_id = staff_users.id WHERE " + " AND ".join(where) +
        " ORDER BY s.due_date",
        params,
    )


def get_schedule(schedule_id):
    return fetch_one(
        "SELECT s.*, mess_halls.college_id FROM inspection_schedule s "
        "JOIN mess_halls ON s.mess_id = mess_halls.id WHERE s.id = %s",
        (schedule_id,),
    )


def delete_schedule(schedule_id):
    with transaction() as cur:
        cur.execute("DELETE FROM inspection_schedule WHERE id = %s AND completed_inspection_id IS NULL", (schedule_id,))
        return cur.rowcount > 0
