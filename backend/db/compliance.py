"""
db/compliance.py — the records FSSAI actually checks: licence, staff
medical fitness, FoSTaC training, water tests, pest control — each with an
expiry date so nothing lapses unnoticed.
"""

import os

from .core import transaction, fetch_all, fetch_one, now_iso
from . import activity

DOC_TYPES = {
    "fssai_license": "FSSAI licence / registration",
    "medical_certificate": "Food handler medical fitness certificate",
    "fostac_training": "FoSTaC food safety training",
    "water_test": "Water quality test report",
    "pest_control": "Pest control service record",
    "other": "Other",
}


def add_document(college_id, mess_id, doc_type, title, person_name, reference_no, issued_on, expires_on,
                 notes, file_path, actor):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO compliance_documents (college_id, mess_id, doc_type, title, person_name, reference_no, "
            "issued_on, expires_on, notes, file_path, file_name, created_by_staff_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (college_id, mess_id, doc_type, title.strip(), person_name, reference_no, issued_on, expires_on,
             notes, file_path, os.path.basename(file_path) if file_path else None, actor["id"], now_iso()),
        )
        doc_id = cur.lastrowid
        activity.log(cur, "compliance_added",
                     f"{actor['name']} added {DOC_TYPES.get(doc_type, doc_type)}: {title.strip()}"
                     + (f" (expires {expires_on})" if expires_on else ""),
                     mess_id=mess_id, college_id=college_id, ref_id=doc_id,
                     details={"actor": actor["name"], "doc_type": doc_type, "expires_on": str(expires_on or "")})
        return doc_id


def list_documents(college_id=None, mess_id=None, expiring_within_days=None):
    where, params = ["1=1"], []
    if college_id:
        where.append("d.college_id = %s")
        params.append(college_id)
    if mess_id:
        where.append("(d.mess_id = %s OR d.mess_id IS NULL)")
        params.append(mess_id)
    if expiring_within_days is not None:
        where.append("d.expires_on IS NOT NULL AND d.expires_on <= UTC_DATE() + INTERVAL %s DAY")
        params.append(expiring_within_days)
    rows = fetch_all(
        "SELECT d.*, colleges.name AS college_name, mess_halls.name AS mess_name, "
        "DATEDIFF(d.expires_on, UTC_DATE()) AS days_left FROM compliance_documents d "
        "JOIN colleges ON d.college_id = colleges.id LEFT JOIN mess_halls ON d.mess_id = mess_halls.id "
        "WHERE " + " AND ".join(where) + " ORDER BY d.expires_on IS NULL, d.expires_on, d.id",
        params,
    )
    for r in rows:
        r["doc_type_label"] = DOC_TYPES.get(r["doc_type"], r["doc_type"])
    return rows


def get_document(doc_id):
    return fetch_one("SELECT * FROM compliance_documents WHERE id = %s", (doc_id,))


def get_document_by_file(filename):
    return fetch_one("SELECT id, college_id, mess_id FROM compliance_documents WHERE file_name = %s", (filename,))


def delete_document(doc_id, actor):
    with transaction() as cur:
        cur.execute("SELECT * FROM compliance_documents WHERE id = %s", (doc_id,))
        doc = cur.fetchone()
        if not doc:
            return None
        cur.execute("DELETE FROM compliance_documents WHERE id = %s", (doc_id,))
        activity.log(cur, "compliance_deleted", f"{actor['name']} removed compliance record: {doc['title']}",
                     mess_id=doc["mess_id"], college_id=doc["college_id"], ref_id=doc_id,
                     details={"actor": actor["name"]})
        return doc


REMINDER_WINDOWS = (30, 7, 0)  # days before expiry; 0 = expired


def due_reminders():
    """Documents that have entered a reminder window they haven't been
    reminded about yet (30 days, 7 days, expired)."""
    rows = fetch_all(
        "SELECT d.*, colleges.name AS college_name, mess_halls.name AS mess_name, "
        "DATEDIFF(d.expires_on, UTC_DATE()) AS days_left FROM compliance_documents d "
        "JOIN colleges ON d.college_id = colleges.id LEFT JOIN mess_halls ON d.mess_id = mess_halls.id "
        "WHERE d.expires_on IS NOT NULL AND d.expires_on <= UTC_DATE() + INTERVAL 30 DAY"
    )
    due = []
    for r in rows:
        # The tightest window reached: 5 days left -> 7, expired -> 0.
        window = min((w for w in REMINDER_WINDOWS if r["days_left"] <= w), default=None)
        if window is not None and (r["last_reminder_window"] is None or window < r["last_reminder_window"]):
            r["window"] = window
            due.append(r)
    return due


def mark_reminded(doc_id, window):
    with transaction() as cur:
        cur.execute("UPDATE compliance_documents SET last_reminder_window = %s WHERE id = %s", (window, doc_id))
