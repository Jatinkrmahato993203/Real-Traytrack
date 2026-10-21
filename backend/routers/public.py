"""
routers/public.py — endpoints anyone can call: reference data, the public
dashboard and trends. Nothing here exposes a student identity, a contact
email, or free-text complaint content.
"""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException

import config
import db
import fssai_rules as rules
import notify

router = APIRouter(tags=["public"])
LEVEL_RANK = {1: "Low", 2: "Medium", 3: "High"}


@router.get("/health")
def health():
    ok = db.ping()
    return {
        "status": "ok" if ok else "degraded",
        "database": ok,
        "schema_version": db.current_version() if ok else None,
        "email_configured": notify.smtp_configured(),
    }


@router.get("/colleges")
def list_colleges():
    """Names and domains only — contact emails stay behind staff login."""
    return db.list_colleges_public()


@router.get("/mess-halls")
def list_mess_halls(college_id: int):
    return db.list_mess_halls(college_id)


@router.get("/mess-halls/{mess_id}")
def get_mess_hall(mess_id: int):
    """What a QR code on a table resolves to."""
    mess = db.get_mess_hall(mess_id)
    if not mess:
        raise HTTPException(status_code=404, detail="Mess hall not found.")
    return {"id": mess["id"], "name": mess["name"], "college_id": mess["college_id"],
            "college_name": mess["college_name"]}


@router.get("/categories")
def list_categories():
    return [{"name": name, "severity": sev, "fast_lane": rules.is_fast_lane(name)}
            for name, sev in rules.COMPLAINT_CATEGORIES.items()]


@router.get("/meals")
def list_meals():
    return rules.MEALS


@router.get("/privacy")
def privacy_info():
    return {"version": config.PRIVACY_NOTICE_VERSION, "retention_days": config.RETENTION_DAYS}


def _public_alert(a, delivered):
    return {
        "id": a["id"], "mess_id": a["mess_id"], "mess_name": a["mess_name"], "level": a["level"],
        "status": a["status"], "reason": a["reason"], "fssai_reference": a["fssai_reference"],
        "created_at": a["created_at"], "authority": rules.get_authority(a["level"]),
        # Only claim the authority was told when an email actually went out.
        "authority_notified": delivered.get(a["id"], False),
    }


@router.get("/dashboard-status")
def dashboard_status(college_id: int):
    halls = db.list_mess_halls(college_id)
    summary = {r["mess_id"]: r for r in db.dashboard_summary(college_id)}
    last_inspections = {r["mess_id"]: r for r in db.latest_by_mess(college_id)}
    week_ago = (db.utcnow() - timedelta(days=7)).date()
    ratings = {r["mess_id"]: r for r in db.rating_summary(college_id, week_ago)[0]}
    open_alerts = db.get_alerts(college_id=college_id, resolved=False)
    delivered = db.notifications.delivery_by_alert([a["id"] for a in open_alerts])

    result = []
    for mess in halls:
        s = summary.get(mess["id"], {})
        worst = LEVEL_RANK.get(int(s.get("worst") or 0))
        worst_alerts = [a for a in open_alerts if a["mess_id"] == mess["id"] and a["level"] == worst]
        insp = last_inspections.get(mess["id"])
        rating = ratings.get(mess["id"])
        result.append({
            "mess": mess,
            "status": "alert" if worst else "clear",
            "open_count": int(s.get("open_count") or 0),
            "worst_level": worst,
            "authority": rules.get_authority(worst) if worst else None,
            "authority_notified": any(delivered.get(a["id"]) for a in worst_alerts) if worst else None,
            "last_inspection": {"at": insp["created_at"], "score": insp["score"]} if insp else None,
            "rating": {"avg": float(rating["avg_stars"]), "count": rating["ratings"]} if rating else None,
        })
    return result


@router.get("/alerts")
def open_alerts(college_id: Optional[int] = None, mess_id: Optional[int] = None):
    alerts = db.get_alerts(college_id=college_id, mess_id=mess_id, resolved=False)
    delivered = db.notifications.delivery_by_alert([a["id"] for a in alerts])
    return [_public_alert(a, delivered) for a in alerts]


def _counts(rows, key):
    counts = {}
    for r in rows:
        if r.get(key):
            counts[r[key]] = counts.get(r[key], 0) + 1
    return [{key: k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


@router.get("/analytics")
def analytics(college_id: int):
    """Counts only — complaint text can name or identify people, so it stays
    behind staff login."""
    now = db.utcnow()
    weekly = db.get_complaints_since(college_id, db.to_db(now - timedelta(days=7)))
    monthly = db.get_complaints_since(college_id, db.to_db(now - timedelta(days=30)))
    per_mess, per_meal = db.rating_summary(college_id, (now - timedelta(days=30)).date())
    return {
        "weekly_chart": _counts(weekly, "category"),
        "weekly_total": len(weekly),
        "monthly_chart": _counts(monthly, "category"),
        "monthly_total": len(monthly),
        "monthly_by_meal": _counts(monthly, "meal"),
        "ratings_by_meal": [{"mess_id": r["mess_id"], "meal": r["meal"], "avg": float(r["avg_stars"]),
                             "count": r["ratings"]} for r in per_meal],
    }


@router.get("/trends")
def trends(college_id: Optional[int] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Alerts in the range, plus complaints per month by category."""
    alerts = db.alerts_with_category(college_id=college_id, start_date=start_date, end_date=end_date)
    where, params = ["1=1"], []
    if college_id:
        where.append("college_id = %s")
        params.append(college_id)
    if start_date:
        where.append("DATE(created_at) >= %s")
        params.append(start_date)
    if end_date:
        where.append("DATE(created_at) <= %s")
        params.append(end_date)
    monthly = db.fetch_all(
        "SELECT DATE_FORMAT(created_at, '%%Y-%%m') AS month, category, COUNT(*) AS count FROM complaints "
        "WHERE " + " AND ".join(where) + " GROUP BY month, category ORDER BY month",
        params,
    )
    return {"alerts": alerts, "complaints_by_month": monthly}
