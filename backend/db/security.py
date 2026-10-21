"""
db/security.py — state that must be shared by every server process:
login lockouts and background-job bookkeeping. Keeping these in MySQL (not
in memory) means a restart doesn't reset a lockout, and two workers never
run the same job twice.
"""

from contextlib import contextmanager
from datetime import timedelta

from .core import transaction, fetch_one, now_iso, utcnow, to_db, get_connection


# ---------- Login lockout ----------

def lockout_remaining(key):
    """Seconds until `key` may try again, or None if not locked."""
    row = fetch_one(
        "SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), locked_until) AS secs FROM login_attempts "
        "WHERE attempt_key = %s AND locked_until > UTC_TIMESTAMP()",
        (key,),
    )
    return row["secs"] if row else None


def record_failure(key, max_attempts, lockout_seconds):
    """Returns attempts left before lockout (0 = now locked)."""
    with transaction() as cur:
        cur.execute(
            "INSERT INTO login_attempts (attempt_key, failures, updated_at) VALUES (%s, 1, %s) "
            "ON DUPLICATE KEY UPDATE "
            # A lock that has expired starts a fresh count.
            "failures = IF(locked_until IS NOT NULL AND locked_until <= UTC_TIMESTAMP(), 1, failures + 1), "
            "locked_until = IF(locked_until IS NOT NULL AND locked_until <= UTC_TIMESTAMP(), NULL, locked_until), "
            "updated_at = VALUES(updated_at)",
            (key, now_iso()),
        )
        cur.execute("SELECT failures FROM login_attempts WHERE attempt_key = %s", (key,))
        failures = cur.fetchone()["failures"]
        if failures >= max_attempts:
            cur.execute("UPDATE login_attempts SET locked_until = %s WHERE attempt_key = %s",
                        (to_db(utcnow() + timedelta(seconds=lockout_seconds)), key))
            return 0
        return max_attempts - failures


def clear_failures(key):
    with transaction() as cur:
        cur.execute("DELETE FROM login_attempts WHERE attempt_key = %s", (key,))


# ---------- Rate limits (fixed windows, shared by every process) ----------

def hit(bucket, window_seconds):
    """Counts one request in `bucket` for the current window; returns
    (hits so far in this window, seconds until the window resets)."""
    now = utcnow()
    epoch = int(now.timestamp())
    start_epoch = epoch - epoch % window_seconds
    from datetime import datetime, timezone
    window_start = datetime.fromtimestamp(start_epoch, tz=timezone.utc).replace(tzinfo=None)
    with transaction() as cur:
        cur.execute(
            "INSERT INTO rate_limits (bucket, window_start, hits) VALUES (%s, %s, 1) "
            "ON DUPLICATE KEY UPDATE hits = hits + 1",
            (bucket[:255], to_db(window_start)),
        )
        cur.execute("SELECT hits FROM rate_limits WHERE bucket = %s AND window_start = %s",
                    (bucket[:255], to_db(window_start)))
        hits = cur.fetchone()["hits"]
    return hits, start_epoch + window_seconds - epoch


def purge_rate_limits(older_than_hours=48):
    with transaction() as cur:
        cur.execute("DELETE FROM rate_limits WHERE window_start < UTC_TIMESTAMP() - INTERVAL %s HOUR",
                    (older_than_hours,))
        return cur.rowcount


# ---------- Background jobs ----------

@contextmanager
def job_lock(name, timeout=0):
    """MySQL named lock held for the duration of a job. Yields True if this
    process got it; another worker already running the job yields False."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT GET_LOCK(%s, %s) AS got", (f"traytrack_job_{name}", timeout))
        got = bool(cur.fetchone()["got"])
        try:
            yield got
        finally:
            if got:
                cur.execute("SELECT RELEASE_LOCK(%s)", (f"traytrack_job_{name}",))
    finally:
        conn.close()


def last_job_run(name):
    row = fetch_one("SELECT last_run_at FROM job_runs WHERE job_name = %s", (name,))
    return row["last_run_at"] if row else None


def record_job_run(name, result):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO job_runs (job_name, last_run_at, last_result) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE last_run_at = VALUES(last_run_at), last_result = VALUES(last_result)",
            (name, now_iso(), str(result)[:255]),
        )


def all_job_runs():
    from .core import fetch_all
    return fetch_all("SELECT * FROM job_runs ORDER BY job_name")
