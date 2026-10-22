"""
metrics.py — Prometheus-format numbers at /metrics (needs METRICS_TOKEN).

Request counters are per server process (scrape each worker, or read them
as "this process"); the gauges come from the database and are global.
"""

import threading
import time
from collections import defaultdict

import db

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
_lock = threading.Lock()
_requests = defaultdict(int)             # (method, status class) -> count
_latency = [0] * (len(BUCKETS) + 1)      # histogram buckets + overflow
_latency_sum = 0.0
_latency_count = 0
STARTED = time.time()


def observe(method, status, seconds):
    global _latency_sum, _latency_count
    with _lock:
        _requests[(method, f"{status // 100}xx")] += 1
        _latency_sum += seconds
        _latency_count += 1
        for i, bound in enumerate(BUCKETS):
            if seconds <= bound:
                _latency[i] += 1
                break
        else:
            _latency[-1] += 1


def render():
    lines = []

    def metric(name, help_text, kind, samples):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        for labels, value in samples:
            label = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
            lines.append(f"{name}{label} {value}")

    with _lock:
        metric("traytrack_http_requests_total", "HTTP requests handled by this process", "counter",
               [({"method": m, "status": s}, n) for (m, s), n in sorted(_requests.items())])
        cumulative, samples = 0, []
        for bound, n in zip(BUCKETS, _latency):
            cumulative += n
            samples.append(({"le": bound}, cumulative))
        samples.append(({"le": "+Inf"}, _latency_count))
        lines.append("# HELP traytrack_http_request_duration_seconds Request latency (this process)")
        lines.append("# TYPE traytrack_http_request_duration_seconds histogram")
        for labels, value in samples:
            lines.append(f'traytrack_http_request_duration_seconds_bucket{{le="{labels["le"]}"}} {value}')
        lines.append(f"traytrack_http_request_duration_seconds_sum {round(_latency_sum, 4)}")
        lines.append(f"traytrack_http_request_duration_seconds_count {_latency_count}")

    metric("traytrack_process_uptime_seconds", "Seconds since this process started", "gauge",
           [({}, int(time.time() - STARTED))])
    up = db.ping()
    metric("traytrack_database_up", "1 if the database answers", "gauge", [({}, 1 if up else 0)])
    if up:
        open_by_level = db.fetch_all("SELECT level, COUNT(*) AS n FROM alerts WHERE resolved = 0 GROUP BY level")
        metric("traytrack_open_alerts", "Unresolved alerts by level", "gauge",
               [({"level": r["level"]}, r["n"]) for r in open_by_level])
        metric("traytrack_notifications_undelivered_7d", "Notifications not delivered in the last 7 days", "gauge",
               [({}, db.notifications.recent_failures())])
        metric("traytrack_job_last_run_age_seconds", "Seconds since each background job last ran", "gauge",
               [({"job": j["job_name"]}, int((db.utcnow() - j["last_run_at"]).total_seconds()))
                for j in db.security.all_job_runs()])
        metric("traytrack_complaints_24h", "Complaints filed in the last 24 hours", "gauge",
               [({}, db.fetch_one("SELECT COUNT(*) AS n FROM complaints WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 1 DAY")["n"])])
    return "\n".join(lines) + "\n"
