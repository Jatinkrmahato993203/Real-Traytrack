"""
db/complaints.py — student complaints, their follow-up by staff, pattern
counting, student resolution votes, meal ratings, and the student's own data
(export / erasure / retention).

Student email is stored only here (and in votes/ratings/consents). It is
never returned to the public, and staff only ever see a masked form — or
nothing at all for anonymous complaints.
"""

import os
import secrets
from datetime import timedelta

from .core import transaction, fetch_all, fetch_one, now_iso, utcnow, to_db
from . import activity

COMPLAINT_STATUSES = ("received", "acknowledged", "action_taken", "closed", "dismissed")


def insert_complaint(college_id, mess_id, student_email, student_name, category, description,
                     photo_path=None, meal=None, dish=None, anonymous=False):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO complaints (college_id, mess_id, student_email, student_name, category, description, "
            "photo_path, file_name, meal, dish, anonymous, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'received', %s)",
            (college_id, mess_id, student_email.strip().lower(), student_name, category, description,
             photo_path, os.path.basename(photo_path) if photo_path else None, meal, dish,
             1 if anonymous else 0, now_iso()),
        )
        complaint_id = cur.lastrowid
        cur.execute("SELECT name FROM mess_halls WHERE id = %s", (mess_id,))
        mess = cur.fetchone()
        meal_text = f" ({meal}{', ' + dish if dish else ''})" if meal else ""
        activity.log(
            cur, "complaint_submitted",
            f"Complaint #{complaint_id}: {category}{meal_text} — {mess['name'] if mess else mess_id}",
            mess_id=mess_id, college_id=college_id, ref_id=complaint_id,
            details={"category": category, "description": description, "meal": meal, "dish": dish,
                     "masked_email": "Anonymous student" if anonymous else activity.mask(student_email),
                     "photo_url": activity.complaint_photo_url(photo_path)},
        )
        return complaint_id


def student_complaint_count_since(email, mess_id, since):
    row = fetch_one(
        "SELECT COUNT(*) AS cnt FROM complaints WHERE student_email = %s AND mess_id = %s AND created_at >= %s",
        (email.strip().lower(), mess_id, since),
    )
    return row["cnt"]


def count_reporters(mess_id, since, category=None):
    """DISTINCT students who complained at this mess since `since` — one
    account filing 20 complaints never looks like 20 independent reports."""
    query = "SELECT COUNT(DISTINCT student_email) AS cnt FROM complaints WHERE mess_id = %s AND created_at >= %s"
    params = [mess_id, since]
    if category:
        query += " AND category = %s"
        params.append(category)
    return fetch_one(query, params)["cnt"]


def get_complaint(complaint_id):
    """Full record INCLUDING student email — callers must not expose it."""
    return fetch_one(
        "SELECT complaints.*, mess_halls.name AS mess_name, colleges.name AS college_name FROM complaints "
        "JOIN mess_halls ON complaints.mess_id = mess_halls.id "
        "JOIN colleges ON complaints.college_id = colleges.id WHERE complaints.id = %s",
        (complaint_id,),
    )


def search_complaints(college_id=None, mess_id=None, since=None, until=None, category=None, status=None,
                      meal=None, q=None, offset=0, limit=50):
    """Staff complaint search with paging. Returns (rows, total). Rows include
    the raw email — the router masks it (or hides it for anonymous ones)."""
    where, params = ["1=1"], []
    for clause, value in (
        ("complaints.college_id = %s", college_id), ("complaints.mess_id = %s", mess_id),
        ("complaints.created_at >= %s", since), ("complaints.created_at <= %s", until),
        ("complaints.category = %s", category), ("complaints.status = %s", status),
        ("complaints.meal = %s", meal),
    ):
        if value:
            where.append(clause)
            params.append(value)
    if q:
        words = [w for w in q.replace("*", " ").split() if len(w) >= 3]
        if words:
            # Full-text index: each word must appear (prefix match), so
            # "cock" finds "cockroach" without scanning every row.
            where.append("MATCH(complaints.description, complaints.dish) AGAINST (%s IN BOOLEAN MODE)")
            params.append(" ".join(f"+{w}*" for w in words))
        else:
            where.append("complaints.dish = %s")
            params.append(q)
    base = (
        "FROM complaints JOIN mess_halls ON complaints.mess_id = mess_halls.id "
        "JOIN colleges ON complaints.college_id = colleges.id WHERE " + " AND ".join(where)
    )
    total = fetch_one(f"SELECT COUNT(*) AS cnt {base}", params)["cnt"]
    rows = fetch_all(
        f"SELECT complaints.*, mess_halls.name AS mess_name, colleges.name AS college_name {base} "
        "ORDER BY complaints.created_at DESC, complaints.id DESC LIMIT %s OFFSET %s",
        params + [limit, offset],
    )
    return rows, total


def respond_to_complaint(complaint_id, status, response, staff):
    """Staff follow-up the student sees in My Reports."""
    with transaction() as cur:
        cur.execute(
            "UPDATE complaints SET status = %s, staff_response = %s, responded_by_staff_id = %s, responded_at = %s "
            "WHERE id = %s",
            (status, response, staff["id"], now_iso(), complaint_id),
        )
        cur.execute(
            "SELECT complaints.mess_id, complaints.college_id, complaints.category, mess_halls.name AS mess_name "
            "FROM complaints JOIN mess_halls ON complaints.mess_id = mess_halls.id WHERE complaints.id = %s",
            (complaint_id,),
        )
        c = cur.fetchone()
        activity.log(
            cur, "complaint_responded",
            f"{staff['name']} marked complaint #{complaint_id} {status.replace('_', ' ')} — {c['mess_name']}",
            mess_id=c["mess_id"], college_id=c["college_id"], ref_id=complaint_id,
            details={"actor": staff["name"], "status": status, "response": response, "category": c["category"]},
        )


def hide_complaint_text(complaint_id, reason, staff):
    """Moderation: removes abusive or identifying text (and the photo, if
    asked) from a complaint everywhere staff could see it, keeping the
    report itself (category, hall, time) for pattern counting."""
    with transaction() as cur:
        cur.execute(
            "UPDATE complaints SET description = NULL, dish = NULL, hidden_at = %s, hidden_reason = %s, "
            "hidden_by_staff_id = %s WHERE id = %s",
            (now_iso(), reason, staff["id"], complaint_id),
        )
        # The live feed copied the text when the complaint arrived.
        cur.execute(
            "SELECT id, details FROM activity_log WHERE event_type = 'complaint_submitted' AND ref_id = %s",
            (complaint_id,),
        )
        import json
        for row in cur.fetchall():
            details = json.loads(row["details"] or "{}")
            details.update(description=None, dish=None, hidden=reason)
            cur.execute("UPDATE activity_log SET details = %s WHERE id = %s", (json.dumps(details), row["id"]))
        cur.execute("SELECT mess_id, college_id FROM complaints WHERE id = %s", (complaint_id,))
        c = cur.fetchone()
        activity.log(cur, "complaint_hidden", f"{staff['name']} hid the text of complaint #{complaint_id}",
                     mess_id=c["mess_id"], college_id=c["college_id"], ref_id=complaint_id,
                     details={"actor": staff["name"], "reason": reason})


def get_complaints_since(college_id, since):
    return fetch_all(
        "SELECT id, mess_id, category, meal, created_at FROM complaints "
        "WHERE college_id = %s AND created_at >= %s",
        (college_id, since),
    )


def get_my_complaints(email):
    return fetch_all(
        "SELECT complaints.*, mess_halls.name AS mess_name FROM complaints "
        "JOIN mess_halls ON complaints.mess_id = mess_halls.id "
        "WHERE complaints.student_email = %s ORDER BY complaints.created_at DESC, complaints.id DESC",
        (email.strip().lower(),),
    )


def get_complaint_by_photo(filename):
    """`filename` must already be validated (hex + extension)."""
    return fetch_one("SELECT id, college_id, mess_id FROM complaints WHERE file_name = %s", (filename,))


# ---------- Pattern alerts ↔ complaints ----------

def get_alert_for_complaint(complaint_id, window_days):
    """The pattern alert this complaint is part of — same mess, its category
    (or all categories), raised within the window after it, still open when
    it was filed. Every contributing student sees it."""
    c = fetch_one("SELECT mess_id, category, created_at FROM complaints WHERE id = %s", (complaint_id,))
    if not c:
        return None
    return fetch_one(
        "SELECT * FROM alerts WHERE source = 'complaint_pattern' AND mess_id = %s "
        "AND pattern_key IN (%s, %s, %s) "
        "AND created_at <= %s AND (resolved = 0 OR resolved_at >= %s) "
        "ORDER BY created_at DESC LIMIT 1",
        (
            c["mess_id"],
            f"mess{c['mess_id']}_category_{c['category']}",
            f"mess{c['mess_id']}_fastlane_{c['category']}",
            f"mess{c['mess_id']}_all_categories",
            c["created_at"] + timedelta(days=window_days),
            c["created_at"],
        ),
    )


def student_contributed_to_alert(email, alert, window_days):
    query = "SELECT 1 FROM complaints WHERE student_email = %s AND mess_id = %s AND created_at >= %s"
    params = [email.strip().lower(), alert["mess_id"], alert["created_at"] - timedelta(days=window_days)]
    key = alert.get("pattern_key") or ""
    for prefix in (f"mess{alert['mess_id']}_category_", f"mess{alert['mess_id']}_fastlane_"):
        if key.startswith(prefix):
            query += " AND category = %s"
            params.append(key[len(prefix):])
    return fetch_one(query + " LIMIT 1", params) is not None


def add_resolution_vote(alert_id, email):
    """(total distinct votes, whether this was a new vote)."""
    with transaction() as cur:
        cur.execute(
            "INSERT IGNORE INTO alert_resolution_votes (alert_id, student_email, created_at) VALUES (%s, %s, %s)",
            (alert_id, email.strip().lower(), now_iso()),
        )
        is_new = cur.rowcount == 1
        cur.execute("SELECT COUNT(*) AS cnt FROM alert_resolution_votes WHERE alert_id = %s", (alert_id,))
        return cur.fetchone()["cnt"], is_new


def get_resolution_vote_state(alert_id, email):
    row = fetch_one(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(student_email = %s), 0) AS mine "
        "FROM alert_resolution_votes WHERE alert_id = %s",
        (email.strip().lower(), alert_id),
    )
    return row["cnt"], bool(row["mine"])


# ---------- Meal ratings ----------

def upsert_rating(college_id, mess_id, email, rating_date, meal, stars, comment):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO meal_ratings (college_id, mess_id, student_email, rating_date, meal, stars, comment, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE stars = VALUES(stars), comment = VALUES(comment), created_at = VALUES(created_at)",
            (college_id, mess_id, email.strip().lower(), rating_date, meal, stars, comment, now_iso()),
        )


def rating_summary(college_id, since_date):
    """Average stars per mess hall (and per meal) since a date."""
    per_mess = fetch_all(
        "SELECT mess_id, ROUND(AVG(stars), 2) AS avg_stars, COUNT(*) AS ratings FROM meal_ratings "
        "WHERE college_id = %s AND rating_date >= %s GROUP BY mess_id",
        (college_id, since_date),
    )
    per_meal = fetch_all(
        "SELECT mess_id, meal, ROUND(AVG(stars), 2) AS avg_stars, COUNT(*) AS ratings FROM meal_ratings "
        "WHERE college_id = %s AND rating_date >= %s GROUP BY mess_id, meal",
        (college_id, since_date),
    )
    return per_mess, per_meal


def my_ratings(email, since_date):
    return fetch_all(
        "SELECT mess_id, rating_date, meal, stars, comment FROM meal_ratings "
        "WHERE student_email = %s AND rating_date >= %s ORDER BY rating_date DESC",
        (email.strip().lower(), since_date),
    )


# ---------- Privacy: consent, export, erasure, retention ----------

def get_consent(email):
    return fetch_one("SELECT * FROM student_consents WHERE student_email = %s", (email.strip().lower(),))


def record_consent(email, version):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO student_consents (student_email, notice_version, accepted_at) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE notice_version = VALUES(notice_version), accepted_at = VALUES(accepted_at)",
            (email.strip().lower(), version, now_iso()),
        )


def export_student_data(email):
    email = email.strip().lower()
    return {
        "complaints": fetch_all(
            "SELECT id, college_id, mess_id, student_name, category, description, meal, dish, anonymous, status, "
            "staff_response, responded_at, created_at, photo_path IS NOT NULL AS has_photo "
            "FROM complaints WHERE student_email = %s ORDER BY created_at", (email,)),
        "meal_ratings": fetch_all(
            "SELECT mess_id, rating_date, meal, stars, comment, created_at FROM meal_ratings "
            "WHERE student_email = %s ORDER BY rating_date", (email,)),
        "resolution_votes": fetch_all(
            "SELECT alert_id, created_at FROM alert_resolution_votes WHERE student_email = %s", (email,)),
        "consent": get_consent(email),
    }


def _anonymize(cur, where_sql, params, clear_description):
    """Replaces identity on matching complaints. Each student gets one random
    pseudonym (not derived from the email, so it can't be reversed), which
    keeps distinct-reporter counts correct. Returns photo paths to delete."""
    cur.execute(f"SELECT DISTINCT student_email FROM complaints WHERE {where_sql}", params)
    emails = [r["student_email"] for r in cur.fetchall()]
    cur.execute(f"SELECT photo_path FROM complaints WHERE {where_sql} AND photo_path IS NOT NULL", params)
    photos = [r["photo_path"] for r in cur.fetchall()]
    for email in emails:
        pseudonym = f"anon-{secrets.token_hex(8)}@deleted.invalid"
        cur.execute(
            f"UPDATE complaints SET student_email = %s, student_name = NULL, photo_path = NULL, file_name = NULL, "
            f"{'description = NULL, dish = NULL, ' if clear_description else ''}anonymized_at = %s "
            f"WHERE student_email = %s AND {where_sql}",
            [pseudonym, now_iso(), email] + list(params),
        )
    return photos


def erase_student(email):
    """The student's right to erasure: their identity, text and photos are
    removed from complaints; votes, ratings and consent go with them.
    Category/time/hall stay so aggregate history remains accurate."""
    email = email.strip().lower()
    with transaction() as cur:
        photos = _anonymize(cur, "student_email = %s", [email], clear_description=True)
        pseudonym = f"anon-{secrets.token_hex(8)}@deleted.invalid"
        cur.execute("UPDATE alert_resolution_votes SET student_email = %s WHERE student_email = %s", (pseudonym, email))
        cur.execute("UPDATE meal_ratings SET student_email = %s, comment = NULL WHERE student_email = %s", (pseudonym, email))
        cur.execute("DELETE FROM student_consents WHERE student_email = %s", (email,))
        activity.log(cur, "student_data_erased", f"A student erased their data ({activity.mask(email)})",
                     details={"photos_deleted": len(photos)})
    for p in photos:
        _delete_file(p)
    return len(photos)


def apply_retention(days):
    """Anonymizes complaints older than `days` and deletes their photos."""
    cutoff = to_db(utcnow() - timedelta(days=days))
    with transaction() as cur:
        photos = _anonymize(cur, "created_at < %s AND anonymized_at IS NULL", [cutoff], clear_description=True)
        cur.execute(
            "UPDATE meal_ratings SET student_email = CONCAT('anon-', SUBSTRING(SHA2(CONCAT(id, RAND()), 256), 1, 16), "
            "'@deleted.invalid'), comment = NULL WHERE rating_date < %s AND student_email NOT LIKE 'anon-%%'",
            (cutoff[:10],),
        )
        ratings = cur.rowcount
    for p in photos:
        _delete_file(p)
    return len(photos), ratings


def _delete_file(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
