"""Monitoring, ops alerts, and a real backup → restore round trip."""

import json
import os
import shutil
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import backups
import config
import db
import jobs
import ops
from conftest import hdr


# ---------- a local "Slack" ----------

@pytest.fixture
def webhook(monkeypatch):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(ops, "OPS_WEBHOOK_URL", f"http://127.0.0.1:{server.server_port}/hook")
    db.execute("DELETE FROM notifications WHERE kind LIKE 'ops_%%'")
    yield received
    server.shutdown()


def _wait(cond, seconds=3):
    end = time.time() + seconds
    while time.time() < end and not cond():
        time.sleep(0.05)
    return cond()


def test_ops_alert_is_sent_once_per_cooldown(webhook):
    assert ops.alert("disk_full", "Disk is 99% full") is True
    assert ops.alert("disk_full", "Still full") is False          # cooldown: one message per outage
    assert ops.alert("other_problem", "Different kind") is True
    assert [m["text"].splitlines()[0] for m in webhook] == ["[TrayTrack ops] disk full", "[TrayTrack ops] other problem"]


def test_error_burst_alerts(webhook, monkeypatch):
    monkeypatch.setattr(ops, "ERROR_BURST", 3)
    for _ in range(3):
        ops.record_server_error("/complaints")
    assert _wait(lambda: webhook)
    assert "server errors" in webhook[0]["text"]


def test_failing_job_alerts(webhook, monkeypatch):
    def broken():
        raise ValueError("boom")
    monkeypatch.setattr(jobs, "JOBS", [("broken_job", lambda: True, broken)])
    jobs.run_due_jobs()
    assert _wait(lambda: webhook) and "broken_job" in webhook[0]["text"] and "boom" in webhook[0]["text"]


def test_alerts_without_destination_are_still_recorded(monkeypatch):
    monkeypatch.setattr(ops, "OPS_WEBHOOK_URL", "")
    monkeypatch.setattr(ops, "OPS_ALERT_EMAIL", "")
    db.execute("DELETE FROM notifications WHERE kind = 'ops_nowhere'")
    ops.alert("nowhere", "test")
    row = db.fetch_one("SELECT status, error FROM notifications WHERE kind = 'ops_nowhere'")
    assert row["status"] == "skipped_no_contact" and "OPS_ALERT_EMAIL" in row["error"]


# ---------- health & metrics ----------

def test_health_goes_503_when_jobs_stop(client, monkeypatch):
    assert client.get("/health").status_code == 200
    monkeypatch.setattr(config, "JOBS_ENABLED", True)
    monkeypatch.setattr(jobs, "_started_at", db.utcnow() - timedelta(hours=5))
    for name in jobs.STALE_AFTER:
        db.security.record_job_run(name, "test")
    assert client.get("/health").status_code == 200                       # jobs ran recently
    db.execute("UPDATE job_runs SET last_run_at = UTC_TIMESTAMP() - INTERVAL 4 HOUR WHERE job_name = 'escalation'")
    r = client.get("/health")
    assert r.status_code == 503 and r.json()["stale_jobs"] == ["escalation"]
    db.security.record_job_run("escalation", "test")
    assert client.get("/health").status_code == 200


def test_metrics_need_a_token(client, monkeypatch):
    import main
    assert client.get("/metrics").status_code == 404                       # off unless configured
    monkeypatch.setattr(main, "METRICS_TOKEN", "scrape-secret")
    assert client.get("/metrics", headers=hdr("wrong")).status_code == 401
    r = client.get("/metrics", headers=hdr("scrape-secret"))
    assert r.status_code == 200
    body = r.text
    for name in ("traytrack_http_requests_total", "traytrack_http_request_duration_seconds_bucket",
                 "traytrack_database_up 1", "traytrack_open_alerts", "traytrack_job_last_run_age_seconds"):
        assert name in body


# ---------- backup → restore ----------

def _tools_available():
    for env, names in (("MYSQLDUMP", ("mysqldump", "mariadb-dump")), ("MYSQL", ("mysql", "mariadb"))):
        if not (os.environ.get(env) or any(shutil.which(n) for n in names)):
            return False
    return True


@pytest.mark.skipif(not _tools_available(), reason="mysqldump/mysql client not installed (set MYSQLDUMP/MYSQL)")
def test_backup_restore_round_trip(client, tmp_path, admin_token):
    before = {t: db.fetch_one(f"SELECT COUNT(*) AS n FROM `{t}`")["n"]
              for t in ("complaints", "alerts", "staff_users", "activity_log", "inspections")}
    version = db.current_version()
    sql_path, zip_path = backups.run_backup(keep=3, out_dir=tmp_path)
    assert backups.verify_dump(sql_path)

    # A damaged backup is caught, not silently "kept".
    broken = tmp_path / "broken.sql"
    broken.write_bytes(sql_path.read_bytes()[: sql_path.stat().st_size // 2])
    with pytest.raises(RuntimeError, match="truncated"):
        backups.verify_dump(broken)

    # Something happens after the backup...
    db.execute("DELETE FROM activity_log WHERE id > 0 LIMIT 5")
    with pytest.raises(RuntimeError, match="already has"):
        backups.restore(sql_path)                                   # refuses without force
    backups.restore(sql_path, zip_path, force=True)
    db.reset_pool()

    after = {t: db.fetch_one(f"SELECT COUNT(*) AS n FROM `{t}`")["n"] for t in before}
    assert after == before and db.current_version() == version
    # and the app still works on the restored data
    assert client.get("/staff/me", headers=hdr(admin_token)).status_code in (200, 401)
    assert client.get("/health").status_code == 200
