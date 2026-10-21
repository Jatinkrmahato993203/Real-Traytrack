"""
database.py — MySQL storage layer for the Mess Monitoring System.

Multi-college design:
- Each college has an authorized email domain (e.g. "nitrkl.ac.in"). A student
  is considered "authorized" simply by their college email matching that
  domain — no manually maintained roster needed, which is what makes this
  scale to many colleges later.
- Mess halls belong to a specific college.
- Student email is stored ONLY in the `complaints` table, and is never
  selected by any public-facing query. Admin views only ever see a masked
  email (see auth.mask_email), never the raw value.
- Alerts track `last_escalated_at` so the 7-day auto-escalation rule
  (see alert_engine.escalate_stale_alerts) has a clock to check against.

Connection settings are read from environment variables so the same code
works locally and in production:
  DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
"""

import os
import json
import logging
import pymysql
import pymysql.cursors
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Automatically load variables from a .env file in the project folder,
# so you don't need to manually export them before running streamlit.
load_dotenv()

logger = logging.getLogger("traytrack.activity")

LEVELS = ["Low", "Medium", "High"]  # index order matters — used for escalation

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "mess_monitor")


def get_connection():
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS colleges (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            email_domain VARCHAR(255) UNIQUE NOT NULL,
            mess_head_email VARCHAR(255),
            principal_email VARCHAR(255),
            fssai_contact_email VARCHAR(255)
        )
    """)

    # Migration safety: add contact columns to pre-existing colleges tables
    for col in ("mess_head_email", "principal_email", "fssai_contact_email"):
        c.execute("""
            SELECT COUNT(*) as cnt FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = 'colleges' AND column_name = %s
        """, (col,))
        if c.fetchone()["cnt"] == 0:
            c.execute(f"ALTER TABLE colleges ADD COLUMN {col} VARCHAR(255)")
            conn.commit()

    c.execute("""
        CREATE TABLE IF NOT EXISTS mess_halls (
            id INT AUTO_INCREMENT PRIMARY KEY,
            college_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            UNIQUE KEY college_name (college_id, name),
            FOREIGN KEY (college_id) REFERENCES colleges(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INT AUTO_INCREMENT PRIMARY KEY,
            college_id INT NOT NULL,
            mess_id INT NOT NULL,
            student_email VARCHAR(255) NOT NULL,
            student_name VARCHAR(255),
            category VARCHAR(100) NOT NULL,
            description TEXT,
            photo_path VARCHAR(500),
            created_at DATETIME NOT NULL,
            FOREIGN KEY (college_id) REFERENCES colleges(id),
            FOREIGN KEY (mess_id) REFERENCES mess_halls(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inspections (
            id INT AUTO_INCREMENT PRIMARY KEY,
            mess_id INT NOT NULL,
            inspector_name VARCHAR(255) NOT NULL,
            responses TEXT NOT NULL,
            score FLOAT NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (mess_id) REFERENCES mess_halls(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INT AUTO_INCREMENT PRIMARY KEY,
            mess_id INT NOT NULL,
            source VARCHAR(50) NOT NULL,
            source_id INT,
            level VARCHAR(20) NOT NULL,
            reason TEXT NOT NULL,
            fssai_reference VARCHAR(255),
            pattern_key VARCHAR(255),
            created_at DATETIME NOT NULL,
            last_escalated_at DATETIME NOT NULL,
            resolved TINYINT NOT NULL DEFAULT 0,
            resolved_at DATETIME,
            resolution_notes TEXT,
            FOREIGN KEY (mess_id) REFERENCES mess_halls(id)
        )
    """)

    # Migration safety: add pattern_key to pre-existing alerts tables that
    # were created before this column existed.
    c.execute("""
        SELECT COUNT(*) as cnt FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'alerts' AND column_name = 'pattern_key'
    """)
    if c.fetchone()["cnt"] == 0:
        c.execute("ALTER TABLE alerts ADD COLUMN pattern_key VARCHAR(255)")
        conn.commit()

    c.execute("""
        CREATE TABLE IF NOT EXISTS alert_history (
            id INT AUTO_INCREMENT PRIMARY KEY,
            alert_id INT NOT NULL,
            event VARCHAR(50) NOT NULL,
            level VARCHAR(20) NOT NULL,
            note TEXT,
            timestamp DATETIME NOT NULL,
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
        )
    """)

    # One row per (alert, student) — a complaint-pattern alert is only
    # closed by students once enough DIFFERENT reporters agree it's fixed.
    c.execute("""
        CREATE TABLE IF NOT EXISTS alert_resolution_votes (
            alert_id INT NOT NULL,
            student_email VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (alert_id, student_email),
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
        )
    """)

    # Unified, append-only audit trail of everything that happens — student
    # complaints (accepted and rejected), inspections, alert lifecycle,
    # resolution votes and admin changes. Powers the Admin Panel's live
    # activity feed; ids only ever increase, so "everything after id N" is
    # all a live client needs to ask for.
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            event_type VARCHAR(50) NOT NULL,
            college_id INT,
            mess_id INT,
            ref_id INT,
            summary VARCHAR(500) NOT NULL,
            details TEXT,
            created_at DATETIME NOT NULL,
            INDEX idx_activity_college (college_id, id),
            INDEX idx_activity_type (event_type, id)
        )
    """)

    conn.commit()

    # Individual admin / inspector accounts. college_id NULL = all colleges.
    # Role and active flag are re-read on every request, so deactivating
    # someone or changing their role takes effect immediately.
    c.execute("""
        CREATE TABLE IF NOT EXISTS staff_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            role VARCHAR(20) NOT NULL,
            college_id INT,
            password_hash VARCHAR(255) NOT NULL,
            active TINYINT NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (college_id) REFERENCES colleges(id)
        )
    """)

    # Who did it: the inspector behind each inspection, the admin behind
    # each resolution (NULL for rows from before staff accounts existed).
    _add_column_if_missing(c, "inspections", "inspector_id", "INT")
    _add_column_if_missing(c, "alerts", "resolved_by_staff_id", "INT")
    conn.commit()

    c.execute("SELECT COUNT(*) as cnt FROM activity_log")
    if c.fetchone()["cnt"] == 0:
        _backfill_activity(c)
        conn.commit()

    # Seed one sample college + its mess halls, only on a fresh DB
    c.execute("SELECT COUNT(*) as cnt FROM colleges")
    if c.fetchone()["cnt"] == 0:
        c.execute("INSERT INTO colleges (name, email_domain) VALUES (%s, %s)",
                   ("Sample Institute of Technology", "sample-college.edu"))
        college_id = c.lastrowid
        c.executemany("INSERT INTO mess_halls (college_id, name) VALUES (%s, %s)", [
            (college_id, "Mess A - North Block"),
            (college_id, "Mess B - South Block"),
        ])
        conn.commit()

    conn.close()


def _add_column_if_missing(c, table, column, ddl):
    c.execute(
        "SELECT COUNT(*) as cnt FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, column),
    )
    if c.fetchone()["cnt"] == 0:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def now_iso():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ---------- Activity log ----------

def complaint_photo_url(photo_path):
    """Photos are only served through the staff-authenticated endpoint,
    never as public static files."""
    return f"/admin/complaint-photos/{os.path.basename(photo_path)}" if photo_path else None


def _mask(email):
    from auth import mask_email
    return mask_email(email)


def _log_activity(cur, event_type, summary, mess_id=None, college_id=None, ref_id=None, details=None, ts=None):
    """Writes one activity row using the caller's cursor, so the log entry
    commits (or rolls back) together with the change it describes. Never
    put a raw student email in summary/details — use _mask()."""
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
    """Standalone version of _log_activity for events that don't write
    anything else (e.g. a rejected complaint, an admin change)."""
    conn = get_connection()
    cur = conn.cursor()
    _log_activity(cur, event_type, summary, mess_id, college_id, ref_id, details)
    conn.commit()
    conn.close()


def _alert_activity(cur, event, alert_id, level, note, ts):
    from fssai_rules import get_authority
    cur.execute(
        "SELECT alerts.mess_id, alerts.source, mess_halls.name as mess_name FROM alerts "
        "JOIN mess_halls ON alerts.mess_id = mess_halls.id WHERE alerts.id = %s",
        (alert_id,),
    )
    a = cur.fetchone()
    verb = {"created": "raised at", "escalated": "escalated to", "resolved": "resolved at"}[event]
    _log_activity(
        cur, f"alert_{event}",
        f"Alert #{alert_id} {verb} {level} — {a['mess_name'] if a else 'unknown mess'}",
        mess_id=a["mess_id"] if a else None, ref_id=alert_id,
        details={"level": level, "note": note, "authority": get_authority(level),
                 "source": a["source"] if a else None},
        ts=ts,
    )


def _inspection_details(inspector_name, responses_json, score, checklist):
    responses = json.loads(responses_json) if isinstance(responses_json, str) else responses_json
    failed = [{"text": item["text"], "critical": item["critical"]}
              for item in checklist if not responses.get(item["id"], False)]
    return {"inspector_name": inspector_name, "score": score, "failed_items": failed,
            "passed": len(checklist) - len(failed), "total": len(checklist)}


def _backfill_activity(cur):
    """One-time: turn data that existed before activity_log into log rows,
    in chronological order, so the admin feed shows full history."""
    from fssai_rules import CHECKLIST
    events = []
    cur.execute(
        "SELECT complaints.*, mess_halls.name as mess_name FROM complaints "
        "JOIN mess_halls ON complaints.mess_id = mess_halls.id"
    )
    for c in cur.fetchall():
        events.append((c["created_at"], 0, "complaint", c))
    cur.execute(
        "SELECT inspections.*, mess_halls.name as mess_name FROM inspections "
        "JOIN mess_halls ON inspections.mess_id = mess_halls.id"
    )
    for i in cur.fetchall():
        events.append((i["created_at"], 0, "inspection", i))
    cur.execute("SELECT * FROM alert_history")
    for h in cur.fetchall():
        events.append((h["timestamp"], 1, "alert", h))
    events.sort(key=lambda e: (e[0], e[1]))

    for ts, _, kind, row in events:
        ts = ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else ts
        if kind == "complaint":
            _log_activity(
                cur, "complaint_submitted", f"Complaint #{row['id']}: {row['category']} — {row['mess_name']}",
                mess_id=row["mess_id"], college_id=row["college_id"], ref_id=row["id"],
                details={"category": row["category"], "description": row["description"],
                         "masked_email": _mask(row["student_email"]), "photo_url": complaint_photo_url(row["photo_path"])},
                ts=ts,
            )
        elif kind == "inspection":
            _log_activity(
                cur, "inspection_submitted",
                f"Inspection #{row['id']} by {row['inspector_name']}: {row['score']}% — {row['mess_name']}",
                mess_id=row["mess_id"], ref_id=row["id"],
                details=_inspection_details(row["inspector_name"], row["responses"], row["score"], CHECKLIST),
                ts=ts,
            )
        else:
            _alert_activity(cur, row["event"], row["alert_id"], row["level"], row["note"], ts)


def get_activity(after_id=None, before_id=None, college_id=None, event_type=None, limit=100, only_prefixes=None):
    """Activity rows. after_id → only rows newer than that, oldest first
    (live updates); otherwise newest first, before_id paging back."""
    query = (
        "SELECT activity_log.*, mess_halls.name as mess_name, colleges.name as college_name "
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
    if event_type:
        query += " AND activity_log.event_type LIKE %s"
        params.append(event_type + "%")
    if only_prefixes:
        query += " AND (" + " OR ".join("activity_log.event_type LIKE %s" for _ in only_prefixes) + ")"
        params.extend(p + "%" for p in only_prefixes)
    # Live updates read forward (oldest first) so a burst bigger than
    # `limit` is delivered in order across polls instead of skipping rows.
    order = "ASC" if after_id is not None and before_id is None else "DESC"
    query += f" ORDER BY activity_log.id {order} LIMIT %s"
    params.append(limit)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    for r in rows:
        r["details"] = json.loads(r["details"]) if r["details"] else {}
    return list(rows)


# ---------- Colleges ----------

def list_colleges():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM colleges ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def get_college(college_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM colleges WHERE id = %s", (college_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_college(name: str, email_domain: str, mess_head_email: str = None,
                 principal_email: str = None, fssai_contact_email: str = None):
    domain = email_domain.strip().lower().lstrip("@")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO colleges (name, email_domain, mess_head_email, principal_email, fssai_contact_email) "
        "VALUES (%s, %s, %s, %s, %s)",
        (name.strip(), domain, mess_head_email, principal_email, fssai_contact_email),
    )
    conn.commit()
    conn.close()


def update_college_contacts(college_id, mess_head_email=None, principal_email=None, fssai_contact_email=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE colleges SET mess_head_email = %s, principal_email = %s, fssai_contact_email = %s WHERE id = %s",
        (mess_head_email, principal_email, fssai_contact_email, college_id),
    )
    conn.commit()
    conn.close()


def get_contact_email_for_level(college_id, level):
    """Looks up the right real contact for a given alert severity level.
    Returns None if that college hasn't set that contact yet — callers
    should handle that gracefully (skip sending, don't crash)."""
    college = get_college(college_id)
    if not college:
        return None
    return {
        "Low": college.get("mess_head_email"),
        "Medium": college.get("principal_email"),
        "High": college.get("fssai_contact_email"),
    }.get(level)


def is_authorized_email(college_id, email: str):
    """A student is authorized simply if their email domain matches the
    college's registered domain — no per-student roster to maintain."""
    college = get_college(college_id)
    if not college:
        return False
    email = email.strip().lower()
    if "@" not in email:
        return False
    domain = email.split("@")[-1]
    return domain == college["email_domain"]


# ---------- Mess halls ----------

def list_mess_halls(college_id=None):
    conn = get_connection()
    cur = conn.cursor()
    if college_id:
        cur.execute("SELECT * FROM mess_halls WHERE college_id = %s ORDER BY name", (college_id,))
    else:
        cur.execute("SELECT * FROM mess_halls ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def get_mess_hall(mess_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mess_halls WHERE id = %s", (mess_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_mess_hall(college_id, name: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO mess_halls (college_id, name) VALUES (%s, %s)", (college_id, name.strip()))
    conn.commit()
    conn.close()


def delete_mess_hall(mess_id):
    """Deletes a mess hall. Will fail if complaints/inspections/alerts still
    reference it (foreign key constraint) — caller should catch and surface
    a clear message rather than silently losing data."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM mess_halls WHERE id = %s", (mess_id,))
    conn.commit()
    conn.close()


def delete_college(college_id):
    """Deletes a college. Will fail if any mess halls still exist under it
    (delete those first) — same reasoning as delete_mess_hall."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM colleges WHERE id = %s", (college_id,))
    conn.commit()
    conn.close()


# ---------- Complaints ----------

def insert_complaint(college_id, mess_id, student_email, student_name, category, description, photo_path=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO complaints (college_id, mess_id, student_email, student_name, category, description, photo_path, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (college_id, mess_id, student_email.strip().lower(), student_name, category, description, photo_path, now_iso()),
    )
    complaint_id = cur.lastrowid
    cur.execute("SELECT name FROM mess_halls WHERE id = %s", (mess_id,))
    mess = cur.fetchone()
    _log_activity(
        cur, "complaint_submitted", f"Complaint #{complaint_id}: {category} — {mess['name'] if mess else mess_id}",
        mess_id=mess_id, college_id=college_id, ref_id=complaint_id,
        details={"category": category, "description": description,
                 "masked_email": _mask(student_email), "photo_url": complaint_photo_url(photo_path)},
    )
    conn.commit()
    conn.close()
    return complaint_id


def student_complaint_count_since(email, mess_id, since):
    """How many complaints this one student has filed at this mess since
    `since` — used to rate-limit a single account."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) as cnt FROM complaints "
        "WHERE student_email = %s AND mess_id = %s AND created_at >= %s",
        (email.strip().lower(), mess_id, since),
    )
    row = cur.fetchone()
    conn.close()
    return row["cnt"]


def count_reporters(mess_id, since, category=None):
    """Number of DISTINCT students who complained at this mess since
    `since`. Counting people rather than rows means one account filing 20
    complaints can never look like 20 independent reports.
    If category is given, counts only that category; otherwise counts all."""
    conn = get_connection()
    cur = conn.cursor()
    if category:
        cur.execute(
            "SELECT COUNT(DISTINCT student_email) as cnt FROM complaints "
            "WHERE mess_id = %s AND category = %s AND created_at >= %s",
            (mess_id, category, since),
        )
    else:
        cur.execute(
            "SELECT COUNT(DISTINCT student_email) as cnt FROM complaints "
            "WHERE mess_id = %s AND created_at >= %s",
            (mess_id, since),
        )
    row = cur.fetchone()
    conn.close()
    return row["cnt"]


def open_pattern_alert_exists(pattern_key):
    """Whether an UNRESOLVED alert already covers this pattern (e.g. 'mess
    5, category Stale food'), so complaint #21, #22, ... don't create
    duplicates. Resolved alerts don't count — once a pattern is resolved it
    re-arms, and can fire again if the problem comes back."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM alerts WHERE pattern_key = %s AND resolved = 0 LIMIT 1",
        (pattern_key,),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def last_pattern_resolution(pattern_key):
    """When this pattern's most recent alert was resolved (or None). Only
    complaints AFTER this point count toward re-firing it — otherwise the
    complaints that caused the old alert would instantly trigger a new one."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT MAX(resolved_at) as ts FROM alerts WHERE pattern_key = %s AND resolved = 1",
        (pattern_key,),
    )
    row = cur.fetchone()
    conn.close()
    return row["ts"] if row else None


def get_complaints_since(college_id, since_date):
    """Raw complaints (not alerts) within a college, since a given date —
    used to power the dashboard charts + description lists."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT complaints.*, mess_halls.name as mess_name FROM complaints "
        "JOIN mess_halls ON complaints.mess_id = mess_halls.id "
        "WHERE complaints.college_id = %s AND complaints.created_at >= %s "
        "ORDER BY complaints.created_at DESC, complaints.id DESC",
        (college_id, since_date),
    )
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def get_complaints_for_review(college_id=None, mess_id=None, since=None):
    """Every complaint (alert or not) for the password-gated Admin Panel and
    Inspector screens, newest first. Includes the raw student email — the
    caller MUST mask_email() it before returning it to the frontend."""
    query = (
        "SELECT complaints.*, mess_halls.name as mess_name, colleges.name as college_name "
        "FROM complaints "
        "JOIN mess_halls ON complaints.mess_id = mess_halls.id "
        "JOIN colleges ON complaints.college_id = colleges.id WHERE 1=1"
    )
    params = []
    if college_id:
        query += " AND complaints.college_id = %s"
        params.append(college_id)
    if mess_id:
        query += " AND complaints.mess_id = %s"
        params.append(mess_id)
    if since:
        query += " AND complaints.created_at >= %s"
        params.append(since)
    query += " ORDER BY complaints.created_at DESC, complaints.id DESC LIMIT 500"
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def get_my_complaints(email):
    """All complaints filed by this verified email, newest first."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT complaints.*, mess_halls.name as mess_name FROM complaints "
        "JOIN mess_halls ON complaints.mess_id = mess_halls.id "
        "WHERE complaints.student_email = %s ORDER BY complaints.created_at DESC, complaints.id DESC",
        (email.strip().lower(),),
    )
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def get_alert_for_complaint(complaint_id, window_days):
    """The complaint-pattern alert (if any) this complaint is part of — i.e.
    an alert for the same mess, covering this complaint's category (or all
    categories), raised within `window_days` after the complaint and still
    open when it was filed. Every
    contributing student sees it, not just the one whose complaint happened
    to cross the threshold."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT mess_id, category, created_at FROM complaints WHERE id = %s", (complaint_id,))
    c = cur.fetchone()
    if not c:
        conn.close()
        return None
    cur.execute(
        "SELECT * FROM alerts WHERE source = 'complaint_pattern' AND mess_id = %s "
        "AND pattern_key IN (%s, %s) "
        "AND created_at <= %s AND (resolved = 0 OR resolved_at >= %s) "
        "ORDER BY created_at DESC LIMIT 1",
        (
            c["mess_id"],
            f"mess{c['mess_id']}_category_{c['category']}",
            f"mess{c['mess_id']}_all_categories",
            c["created_at"] + timedelta(days=window_days),
            c["created_at"],
        ),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def student_contributed_to_alert(email, alert, window_days):
    """True if this student filed a complaint this alert covers: same mess
    (and category, for a category pattern), no earlier than the detection
    window that produced the alert."""
    conn = get_connection()
    cur = conn.cursor()
    query = "SELECT 1 FROM complaints WHERE student_email = %s AND mess_id = %s AND created_at >= %s"
    params = [email.strip().lower(), alert["mess_id"], alert["created_at"] - timedelta(days=window_days)]
    category_prefix = f"mess{alert['mess_id']}_category_"
    if (alert.get("pattern_key") or "").startswith(category_prefix):
        query += " AND category = %s"
        params.append(alert["pattern_key"][len(category_prefix):])
    cur.execute(query + " LIMIT 1", params)
    row = cur.fetchone()
    conn.close()
    return row is not None


def add_resolution_vote(alert_id, email):
    """Records this student's 'it's fixed' vote (idempotent). Returns
    (total distinct votes for the alert, whether this was a new vote)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT IGNORE INTO alert_resolution_votes (alert_id, student_email, created_at) VALUES (%s, %s, %s)",
        (alert_id, email.strip().lower(), now_iso()),
    )
    is_new = cur.rowcount == 1
    cur.execute("SELECT COUNT(*) as cnt FROM alert_resolution_votes WHERE alert_id = %s", (alert_id,))
    count = cur.fetchone()["cnt"]
    conn.commit()
    conn.close()
    return count, is_new


def get_resolution_vote_state(alert_id, email):
    """(total votes, whether this student has voted)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(student_email = %s), 0) as mine "
        "FROM alert_resolution_votes WHERE alert_id = %s",
        (email.strip().lower(), alert_id),
    )
    row = cur.fetchone()
    conn.close()
    return row["cnt"], bool(row["mine"])


def mark_alert_resolved_by_students(alert_id, vote_count):
    """Closes an alert once enough contributing students have voted that
    it's fixed. Voters' emails stay in alert_resolution_votes (private);
    only the count goes into the visible resolution notes."""
    ts = now_iso()
    conn = get_connection()
    cur = conn.cursor()
    notes = f"Marked resolved by {vote_count} reporting students"
    cur.execute(
        "UPDATE alerts SET resolved = 1, resolved_at = %s, resolution_notes = %s WHERE id = %s AND resolved = 0",
        (ts, notes, alert_id),
    )
    if cur.rowcount:
        cur.execute("SELECT level FROM alerts WHERE id = %s", (alert_id,))
        row = cur.fetchone()
        cur.execute(
            "INSERT INTO alert_history (alert_id, event, level, note, timestamp) VALUES (%s, 'resolved', %s, %s, %s)",
            (alert_id, row["level"], notes, ts),
        )
        _alert_activity(cur, "resolved", alert_id, row["level"], notes, ts)
    conn.commit()
    conn.close()


def get_complaint_by_photo(filename):
    """The complaint a stored photo belongs to — used to check the viewing
    staff member's college scope. `filename` must already be validated
    (hex + extension) so it can't carry LIKE wildcards or path parts."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, college_id, mess_id FROM complaints WHERE photo_path LIKE %s", ("%" + filename,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_complaint_private(complaint_id):
    """Full complaint record INCLUDING student email — only ever call this
    from the password-gated admin panel, and only mask_email() the result before display."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM complaints WHERE id = %s", (complaint_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


# ---------- Inspections ----------

def insert_inspection(mess_id, inspector_name, responses_json, score, inspector_id=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO inspections (mess_id, inspector_name, inspector_id, responses, score, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (mess_id, inspector_name, inspector_id, responses_json, score, now_iso()),
    )
    inspection_id = cur.lastrowid
    from fssai_rules import CHECKLIST
    cur.execute("SELECT name FROM mess_halls WHERE id = %s", (mess_id,))
    mess = cur.fetchone()
    _log_activity(
        cur, "inspection_submitted",
        f"Inspection #{inspection_id} by {inspector_name}: {score}% — {mess['name'] if mess else mess_id}",
        mess_id=mess_id, ref_id=inspection_id,
        details=_inspection_details(inspector_name, responses_json, score, CHECKLIST),
    )
    conn.commit()
    conn.close()
    return inspection_id


# ---------- Alerts ----------

def insert_alert(mess_id, source, source_id, level, reason, fssai_reference, pattern_key=None):
    ts = now_iso()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO alerts (mess_id, source, source_id, level, reason, fssai_reference, pattern_key, created_at, last_escalated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (mess_id, source, source_id, level, reason, fssai_reference, pattern_key, ts, ts),
    )
    conn.commit()
    alert_id = cur.lastrowid
    cur.execute(
        "INSERT INTO alert_history (alert_id, event, level, note, timestamp) VALUES (%s, 'created', %s, %s, %s)",
        (alert_id, level, reason, ts),
    )
    _alert_activity(cur, "created", alert_id, level, reason, ts)
    conn.commit()
    conn.close()
    return alert_id


def get_alerts(college_id=None, mess_id=None, level=None, resolved=None, start_date=None, end_date=None):
    query = """
        SELECT alerts.*, mess_halls.name as mess_name, mess_halls.college_id as college_id
        FROM alerts JOIN mess_halls ON alerts.mess_id = mess_halls.id
        WHERE 1=1
    """
    params = []
    if college_id:
        query += " AND mess_halls.college_id = %s"
        params.append(college_id)
    if mess_id:
        query += " AND alerts.mess_id = %s"
        params.append(mess_id)
    if level:
        query += " AND alerts.level = %s"
        params.append(level)
    if resolved is not None:
        query += " AND alerts.resolved = %s"
        params.append(1 if resolved else 0)
    if start_date:
        query += " AND DATE(alerts.created_at) >= %s"
        params.append(start_date)
    if end_date:
        query += " AND DATE(alerts.created_at) <= %s"
        params.append(end_date)
    query += " ORDER BY alerts.created_at DESC"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def get_alert(alert_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT alerts.*, mess_halls.name as mess_name, mess_halls.college_id as college_id "
        "FROM alerts JOIN mess_halls ON alerts.mess_id = mess_halls.id WHERE alerts.id = %s",
        (alert_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_alerts_with_details(college_id=None, start_date=None, end_date=None):
    """Same as get_alerts but also joins in the complaint category (null for
    inspection-sourced alerts) — used for category-level trend breakdowns."""
    query = """
        SELECT alerts.*, mess_halls.name as mess_name, mess_halls.college_id as college_id,
               complaints.category as complaint_category
        FROM alerts
        JOIN mess_halls ON alerts.mess_id = mess_halls.id
        LEFT JOIN complaints ON alerts.source IN ('complaint', 'complaint_pattern') AND alerts.source_id = complaints.id
        WHERE 1=1
    """
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
    query += " ORDER BY alerts.created_at DESC"

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def get_unresolved_stale_alerts(days=7):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM alerts WHERE resolved = 0 AND level != %s "
        "AND last_escalated_at <= (NOW() - INTERVAL %s DAY)",
        (LEVELS[-1], days),
    )
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def escalate_alert(alert_id, new_level):
    from fssai_rules import get_authority
    ts = now_iso()
    note = f"Auto-escalated: unresolved for 7+ days — now handled by {get_authority(new_level)}"
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE alerts SET level = %s, last_escalated_at = %s WHERE id = %s",
        (new_level, ts, alert_id),
    )
    cur.execute(
        "INSERT INTO alert_history (alert_id, event, level, note, timestamp) VALUES (%s, 'escalated', %s, %s, %s)",
        (alert_id, new_level, note, ts),
    )
    _alert_activity(cur, "escalated", alert_id, new_level, note, ts)
    conn.commit()
    conn.close()


def resolve_alert(alert_id, notes="", staff=None):
    """Admin resolution, attributed to the staff account that did it.
    Returns False if the alert doesn't exist or was already resolved (so a
    double-click doesn't log two resolutions)."""
    ts = now_iso()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE alerts SET resolved = 1, resolved_at = %s, resolution_notes = %s, resolved_by_staff_id = %s "
        "WHERE id = %s AND resolved = 0",
        (ts, notes, staff["id"] if staff else None, alert_id),
    )
    if not cur.rowcount:
        conn.close()
        return False
    cur.execute("SELECT level FROM alerts WHERE id = %s", (alert_id,))
    row = cur.fetchone()
    cur.execute(
        "INSERT INTO alert_history (alert_id, event, level, note, timestamp) VALUES (%s, 'resolved', %s, %s, %s)",
        (alert_id, row["level"], notes, ts),
    )
    by = staff["name"] if staff else "admin"
    _alert_activity(cur, "resolved", alert_id, row["level"], f"By {by}: {notes}" if notes else f"By {by}", ts)
    conn.commit()
    conn.close()
    return True


# ---------- Staff accounts (admins + inspectors) ----------

STAFF_PUBLIC_COLUMNS = (
    "staff_users.id, staff_users.name, staff_users.email, staff_users.role, "
    "staff_users.college_id, staff_users.active, staff_users.created_at, colleges.name as college_name"
)


def count_staff():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM staff_users")
    row = cur.fetchone()
    conn.close()
    return row["cnt"]


def count_active_global_admins():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM staff_users WHERE role = 'admin' AND college_id IS NULL AND active = 1")
    row = cur.fetchone()
    conn.close()
    return row["cnt"]


def create_staff(name, email, role, college_id, password_hash):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO staff_users (name, email, role, college_id, password_hash, active, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 1, %s)",
        (name.strip(), email.strip().lower(), role, college_id, password_hash, now_iso()),
    )
    conn.commit()
    staff_id = cur.lastrowid
    conn.close()
    return staff_id


def get_staff(staff_id):
    """Public fields only — never the password hash."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"SELECT {STAFF_PUBLIC_COLUMNS} FROM staff_users "
        "LEFT JOIN colleges ON staff_users.college_id = colleges.id WHERE staff_users.id = %s",
        (staff_id,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_staff_login(email):
    """Includes password_hash — only for checking a login attempt."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM staff_users WHERE email = %s", (email.strip().lower(),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_staff(college_id=None):
    """All staff, or (for a college-scoped admin) only that college's."""
    query = (
        f"SELECT {STAFF_PUBLIC_COLUMNS} FROM staff_users "
        "LEFT JOIN colleges ON staff_users.college_id = colleges.id"
    )
    params = []
    if college_id:
        query += " WHERE staff_users.college_id = %s"
        params.append(college_id)
    query += " ORDER BY staff_users.active DESC, staff_users.role, staff_users.name"
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return list(rows)


def update_staff(staff_id, name=None, role=None, active=None, password_hash=None):
    sets, params = [], []
    if name is not None:
        sets.append("name = %s")
        params.append(name.strip())
    if role is not None:
        sets.append("role = %s")
        params.append(role)
    if active is not None:
        sets.append("active = %s")
        params.append(1 if active else 0)
    if password_hash is not None:
        sets.append("password_hash = %s")
        params.append(password_hash)
    if not sets:
        return
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE staff_users SET {', '.join(sets)} WHERE id = %s", params + [staff_id])
    conn.commit()
    conn.close()
