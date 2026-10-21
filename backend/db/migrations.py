"""
db/migrations.py — versioned, forward-only schema migrations.

Each migration runs once and is recorded in `schema_migrations`. Migrations
are written to be safe on databases created by older versions of the app
(CREATE TABLE IF NOT EXISTS, add-column-if-missing), so an existing install
upgrades in place. A MySQL named lock makes concurrent workers wait instead
of migrating twice.

To change the schema: append a new (version, name, function) to MIGRATIONS.
Never edit a migration that has already shipped.
"""

import logging

from .core import transaction, now_iso

logger = logging.getLogger("traytrack.migrations")


def _column_exists(cur, table, column):
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()["cnt"] > 0


def _add_column(cur, table, column, ddl):
    if not _column_exists(cur, table, column):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _index_exists(cur, table, index):
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
        (table, index),
    )
    return cur.fetchone()["cnt"] > 0


def _add_index(cur, table, index, columns):
    if not _index_exists(cur, table, index):
        cur.execute(f"CREATE INDEX {index} ON {table} ({columns})")


# ---------------------------------------------------------------------------

def m001_baseline(cur):
    """The schema as it existed before versioned migrations."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS colleges (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            email_domain VARCHAR(255) UNIQUE NOT NULL,
            mess_head_email VARCHAR(255),
            principal_email VARCHAR(255),
            fssai_contact_email VARCHAR(255)
        )
    """)
    for col in ("mess_head_email", "principal_email", "fssai_contact_email"):
        _add_column(cur, "colleges", col, "VARCHAR(255)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mess_halls (
            id INT AUTO_INCREMENT PRIMARY KEY,
            college_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            UNIQUE KEY college_name (college_id, name),
            FOREIGN KEY (college_id) REFERENCES colleges(id)
        )
    """)
    cur.execute("""
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
    cur.execute("""
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
    cur.execute("""
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
    _add_column(cur, "alerts", "pattern_key", "VARCHAR(255)")
    cur.execute("""
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alert_resolution_votes (
            alert_id INT NOT NULL,
            student_email VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (alert_id, student_email),
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
        )
    """)
    cur.execute("""
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
    cur.execute("""
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
    _add_column(cur, "inspections", "inspector_id", "INT")
    _add_column(cur, "alerts", "resolved_by_staff_id", "INT")


def m002_students_privacy_notifications(cur):
    """Complaint follow-up + meal context, anonymous reporting, ratings,
    notification delivery tracking, DB-backed login lockout, privacy consent,
    hall capacity (scales thresholds) and kitchen codes (inspector check-in)."""
    _add_column(cur, "complaints", "meal", "VARCHAR(20)")
    _add_column(cur, "complaints", "dish", "VARCHAR(120)")
    _add_column(cur, "complaints", "anonymous", "TINYINT NOT NULL DEFAULT 0")
    # received -> acknowledged -> action_taken -> closed | dismissed
    _add_column(cur, "complaints", "status", "VARCHAR(20) NOT NULL DEFAULT 'received'")
    _add_column(cur, "complaints", "staff_response", "TEXT")
    _add_column(cur, "complaints", "responded_by_staff_id", "INT")
    _add_column(cur, "complaints", "responded_at", "DATETIME")
    _add_column(cur, "complaints", "anonymized_at", "DATETIME")
    _add_index(cur, "complaints", "idx_complaints_mess_time", "mess_id, created_at")
    _add_index(cur, "complaints", "idx_complaints_email", "student_email")
    _add_index(cur, "complaints", "idx_complaints_college_time", "college_id, created_at")
    _add_index(cur, "alerts", "idx_alerts_mess_resolved", "mess_id, resolved")

    _add_column(cur, "mess_halls", "capacity", "INT")
    _add_column(cur, "mess_halls", "kitchen_code", "VARCHAR(16)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meal_ratings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            college_id INT NOT NULL,
            mess_id INT NOT NULL,
            student_email VARCHAR(255) NOT NULL,
            rating_date DATE NOT NULL,
            meal VARCHAR(20) NOT NULL,
            stars TINYINT NOT NULL,
            comment VARCHAR(280),
            created_at DATETIME NOT NULL,
            UNIQUE KEY one_rating (student_email, mess_id, rating_date, meal),
            INDEX idx_ratings_mess_date (mess_id, rating_date),
            FOREIGN KEY (mess_id) REFERENCES mess_halls(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INT AUTO_INCREMENT PRIMARY KEY,
            college_id INT,
            alert_id INT,
            kind VARCHAR(40) NOT NULL,
            recipient_role VARCHAR(40),
            recipient_email VARCHAR(255),
            subject VARCHAR(255),
            status VARCHAR(30) NOT NULL,
            error TEXT,
            created_at DATETIME NOT NULL,
            INDEX idx_notifications_college (college_id, id),
            INDEX idx_notifications_alert (alert_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            attempt_key VARCHAR(255) PRIMARY KEY,
            failures INT NOT NULL DEFAULT 0,
            locked_until DATETIME,
            updated_at DATETIME NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_consents (
            student_email VARCHAR(255) PRIMARY KEY,
            notice_version VARCHAR(20) NOT NULL,
            accepted_at DATETIME NOT NULL
        )
    """)


def m003_inspections(cur):
    """Configurable checklist, pass/fail/N-A answers with notes, photo
    evidence, on-site verification and inspection scheduling."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS checklist_items (
            id INT AUTO_INCREMENT PRIMARY KEY,
            college_id INT,
            item_key VARCHAR(60) NOT NULL,
            text VARCHAR(255) NOT NULL,
            critical TINYINT NOT NULL DEFAULT 0,
            sort_order INT NOT NULL DEFAULT 0,
            active TINYINT NOT NULL DEFAULT 1,
            UNIQUE KEY college_item (college_id, item_key)
        )
    """)
    cur.execute("SELECT COUNT(*) AS cnt FROM checklist_items WHERE college_id IS NULL")
    if cur.fetchone()["cnt"] == 0:
        from fssai_rules import DEFAULT_CHECKLIST
        for order, item in enumerate(DEFAULT_CHECKLIST):
            cur.execute(
                "INSERT INTO checklist_items (college_id, item_key, text, critical, sort_order, active) "
                "VALUES (NULL, %s, %s, %s, %s, 1)",
                (item["id"], item["text"], 1 if item["critical"] else 0, order),
            )

    _add_column(cur, "inspections", "verified_onsite", "TINYINT NOT NULL DEFAULT 0")
    _add_column(cur, "inspections", "latitude", "DECIMAL(9,6)")
    _add_column(cur, "inspections", "longitude", "DECIMAL(9,6)")
    _add_column(cur, "inspections", "general_notes", "TEXT")
    # Set by the inspector's device; a retried offline submission with the
    # same ref returns the original inspection instead of a duplicate.
    _add_column(cur, "inspections", "client_ref", "VARCHAR(64)")
    _add_index(cur, "inspections", "idx_inspections_mess_time", "mess_id, created_at")
    if not _index_exists(cur, "inspections", "uq_inspections_client_ref"):
        cur.execute("CREATE UNIQUE INDEX uq_inspections_client_ref ON inspections (client_ref)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS inspection_photos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            inspection_id INT NOT NULL,
            item_key VARCHAR(60),
            photo_path VARCHAR(500) NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (inspection_id) REFERENCES inspections(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inspection_schedule (
            id INT AUTO_INCREMENT PRIMARY KEY,
            mess_id INT NOT NULL,
            due_date DATE NOT NULL,
            assigned_staff_id INT,
            notes VARCHAR(500),
            completed_inspection_id INT,
            created_by_staff_id INT,
            created_at DATETIME NOT NULL,
            INDEX idx_schedule_mess (mess_id, completed_inspection_id),
            FOREIGN KEY (mess_id) REFERENCES mess_halls(id)
        )
    """)


def m004_workflow_roles_compliance(cur):
    """Alert workflow (owner, due date, evidence, reopen), authority roles
    tied to a mess hall, compliance records, and job bookkeeping."""
    # open -> acknowledged -> in_progress -> fixed -> resolved
    _add_column(cur, "alerts", "status", "VARCHAR(20) NOT NULL DEFAULT 'open'")
    _add_column(cur, "alerts", "owner_staff_id", "INT")
    _add_column(cur, "alerts", "due_date", "DATE")
    _add_column(cur, "alerts", "last_reminder_at", "DATETIME")
    _add_column(cur, "alerts", "reopened_count", "INT NOT NULL DEFAULT 0")
    cur.execute("UPDATE alerts SET status = 'resolved' WHERE resolved = 1 AND status = 'open'")
    _add_column(cur, "alert_history", "actor_staff_id", "INT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alert_evidence (
            id INT AUTO_INCREMENT PRIMARY KEY,
            alert_id INT NOT NULL,
            kind VARCHAR(20) NOT NULL,
            note TEXT,
            photo_path VARCHAR(500),
            inspection_id INT,
            staff_id INT,
            created_at DATETIME NOT NULL,
            FOREIGN KEY (alert_id) REFERENCES alerts(id)
        )
    """)

    # A mess head can be tied to one mess hall.
    _add_column(cur, "staff_users", "mess_id", "INT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS compliance_documents (
            id INT AUTO_INCREMENT PRIMARY KEY,
            college_id INT NOT NULL,
            mess_id INT,
            doc_type VARCHAR(40) NOT NULL,
            title VARCHAR(255) NOT NULL,
            person_name VARCHAR(255),
            reference_no VARCHAR(120),
            issued_on DATE,
            expires_on DATE,
            file_path VARCHAR(500),
            notes VARCHAR(500),
            created_by_staff_id INT,
            created_at DATETIME NOT NULL,
            last_reminder_window INT,
            INDEX idx_compliance_expiry (college_id, expires_on),
            FOREIGN KEY (college_id) REFERENCES colleges(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS job_runs (
            job_name VARCHAR(60) PRIMARY KEY,
            last_run_at DATETIME NOT NULL,
            last_result VARCHAR(255)
        )
    """)


MIGRATIONS = [
    (1, "baseline", m001_baseline),
    (2, "students_privacy_notifications", m002_students_privacy_notifications),
    (3, "inspections", m003_inspections),
    (4, "workflow_roles_compliance", m004_workflow_roles_compliance),
]


def current_version():
    with transaction() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                applied_at DATETIME NOT NULL
            )
        """)
        cur.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations")
        return cur.fetchone()["v"]


def run_migrations():
    """Applies every pending migration in order. Safe to call on every start."""
    with transaction() as cur:
        cur.execute("SELECT GET_LOCK('traytrack_migrations', 60) AS got")
        if not cur.fetchone()["got"]:
            raise RuntimeError("Timed out waiting for another process to finish migrating.")
        try:
            applied_before = current_version()
            for version, name, fn in MIGRATIONS:
                if version <= applied_before:
                    continue
                logger.info("Applying migration %03d_%s", version, name)
                # MySQL commits DDL implicitly, so each migration is written
                # to be re-runnable if it is ever interrupted part-way.
                with transaction() as mcur:
                    fn(mcur)
                    mcur.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (%s, %s, %s)",
                        (version, name, now_iso()),
                    )
        finally:
            cur.execute("SELECT RELEASE_LOCK('traytrack_migrations')")
    return current_version()
