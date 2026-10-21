"""
insights.py — numbers for running a pilot and tuning the alert rules.

The thresholds in fssai_rules.DEFAULT_SETTINGS are educated guesses. This
module answers, from a college's own history: how fast are alerts handled,
how many get reopened, and "if the threshold were T, how many alerts would
we have had?" — so the rules can be set from evidence instead of guesswork.
"""

from collections import defaultdict
from datetime import timedelta
from statistics import median

import db
import fssai_rules as rules


def _max_distinct_in_window(events, window):
    """events: [(time, reporter)] sorted by time. The most distinct
    reporters seen inside any sliding window of length `window`."""
    best, start = 0, 0
    counts = defaultdict(int)
    for end, (t, who) in enumerate(events):
        counts[who] += 1
        while t - events[start][0] > window:
            old = events[start][1]
            counts[old] -= 1
            if counts[old] == 0:
                del counts[old]
            start += 1
        best = max(best, len(counts))
    return best


def _hours(a, b):
    return round((b - a).total_seconds() / 3600, 1)


def college_insights(college_id, days=90):
    settings = db.get_college_settings(college_id)
    since = db.utcnow() - timedelta(days=days)
    since_s = db.to_db(since)

    complaints = db.fetch_all(
        "SELECT mess_id, category, student_email, created_at FROM complaints "
        "WHERE college_id = %s AND created_at >= %s ORDER BY created_at",
        (college_id, since_s),
    )
    halls = {h["id"]: h for h in db.list_mess_halls(college_id)}

    # ---- volume ----
    weekly = defaultdict(lambda: {"complaints": 0, "reporters": set()})
    for c in complaints:
        week = (c["created_at"] - timedelta(days=c["created_at"].weekday())).date().isoformat()
        weekly[week]["complaints"] += 1
        weekly[week]["reporters"].add(c["student_email"])
    volume = [{"week": w, "complaints": v["complaints"], "reporters": len(v["reporters"])}
              for w, v in sorted(weekly.items())]

    # ---- threshold simulation ----
    groups = defaultdict(list)
    for c in complaints:
        groups[(c["mess_id"], c["category"])].append((c["created_at"], c["student_email"]))
    window = timedelta(days=settings["window_days"])
    fast_window = timedelta(hours=settings["fast_lane_hours"])
    peaks, fast_peaks = [], []
    for (mess_id, category), events in groups.items():
        peak = _max_distinct_in_window(events, window)
        peaks.append({"mess_id": mess_id, "mess_name": halls.get(mess_id, {}).get("name"), "category": category,
                      "peak_reporters": peak,
                      "current_threshold": rules.category_threshold(halls.get(mess_id, {}).get("capacity"), settings)})
        if rules.is_fast_lane(category):
            fast_peaks.append(_max_distinct_in_window(events, fast_window))
    peaks.sort(key=lambda p: -p["peak_reporters"])
    category_curve = [{"threshold": t, "alerts": sum(1 for p in peaks if p["peak_reporters"] >= t)} for t in range(2, 26)]
    fast_curve = [{"threshold": t, "alerts": sum(1 for p in fast_peaks if p >= t)} for t in range(2, 11)]

    # ---- how alerts are handled ----
    alerts = db.fetch_all(
        "SELECT alerts.id, alerts.level, alerts.source, alerts.status, alerts.created_at, alerts.resolved_at, "
        "alerts.reopened_count FROM alerts JOIN mess_halls ON alerts.mess_id = mess_halls.id "
        "WHERE mess_halls.college_id = %s AND alerts.created_at >= %s",
        (college_id, since_s),
    )
    first_action = {}
    if alerts:
        rows = db.fetch_all(
            "SELECT alert_id, MIN(timestamp) AS t FROM alert_history WHERE event IN "
            "('acknowledged', 'in_progress', 'fixed', 'resolved') AND alert_id IN ("
            + ", ".join(["%s"] * len(alerts)) + ") GROUP BY alert_id",
            [a["id"] for a in alerts],
        )
        first_action = {r["alert_id"]: r["t"] for r in rows}
    to_ack = [_hours(a["created_at"], first_action[a["id"]]) for a in alerts if a["id"] in first_action]
    to_resolve = [_hours(a["created_at"], a["resolved_at"]) for a in alerts if a["resolved_at"]]
    delivered = db.notifications.delivery_by_alert([a["id"] for a in alerts])
    by_source = defaultdict(int)
    for a in alerts:
        by_source[a["source"]] += 1

    ratings = db.fetch_all(
        "SELECT DATE_FORMAT(rating_date, '%%x-W%%v') AS week, ROUND(AVG(stars), 2) AS avg, COUNT(*) AS n "
        "FROM meal_ratings WHERE college_id = %s AND rating_date >= %s GROUP BY week ORDER BY week",
        (college_id, since.date()),
    )

    return {
        "days": days,
        "settings": settings,
        "volume": volume,
        "totals": {
            "complaints": len(complaints),
            "reporters": len({c["student_email"] for c in complaints}),
            "alerts": len(alerts),
            "alerts_by_source": dict(by_source),
            "alerts_open": sum(1 for a in alerts if a["status"] != "resolved"),
            "reopened": sum(1 for a in alerts if a["reopened_count"]),
            "notified_pct": round(100 * sum(1 for a in alerts if delivered.get(a["id"])) / len(alerts)) if alerts else None,
            "median_hours_to_first_action": median(to_ack) if to_ack else None,
            "median_hours_to_resolve": median(to_resolve) if to_resolve else None,
            "never_actioned": sum(1 for a in alerts if a["id"] not in first_action and a["status"] != "resolved"),
        },
        "simulation": {
            "note": ("Counts (hall, category) pairs whose busiest window reached each threshold — "
                     "at most one alert per pair, so real numbers could be slightly higher."),
            "category_curve": category_curve,
            "fast_lane_curve": fast_curve,
            "top_patterns": peaks[:10],
        },
        "ratings": [{"week": r["week"], "avg": float(r["avg"]), "count": r["n"]} for r in ratings],
    }
