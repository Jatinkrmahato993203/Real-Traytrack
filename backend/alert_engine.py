"""
alert_engine.py — turns complaints and inspections into alerts, moves
alerts through their workflow, and escalates/reminds when nothing happens.

Complaint patterns (distinct students, never raw complaint counts):
  * Fast lane — safety-critical categories (food poisoning, insects, foreign
    objects): 3 students within 48 hours (tunable per college) -> High.
  * Category pattern — enough students report the same category within the
    window (threshold scales with the hall's capacity) -> base level + 1.
  * Whole-hall pattern — enough students report anything -> High.
While a pattern's alert is open it won't fire again; once resolved it
re-arms, counting only complaints filed after the resolution.

Alert workflow:  open -> acknowledged -> in_progress -> fixed -> resolved
  * Closing (fixed -> resolved) needs alert_verify and proof on file
    (a photo or a follow-up inspection).
  * Students who reported a pattern can also close it by vote.
  * A resolved alert can be reopened.
"""

import logging
from datetime import timedelta
from math import ceil

import db
import fssai_rules as rules
import notify

logger = logging.getLogger("traytrack.alerts")

MAX_COMPLAINTS_PER_STUDENT_PER_MESS_PER_DAY = 3
ESCALATE_AFTER_DAYS = 7
HIGH_REMINDER_EVERY_DAYS = 3
FSSAI_INSPECTION_REF = "FSSAI Schedule 4 — Sanitary & Hygiene Requirements"
FSSAI_COMPLAINT_REF = "FSSAI consumer complaint escalation guidance"


def _since(**delta):
    return db.to_db(db.utcnow() - timedelta(**delta))


def _pattern_window_start(pattern_key, **window):
    """Counts start at the window start or the pattern's last resolution,
    whichever is later — so a resolved alert re-arms instead of re-firing."""
    since = db.utcnow() - timedelta(**window)
    last_resolved = db.last_pattern_resolution(pattern_key)
    if last_resolved and last_resolved > since:
        since = last_resolved
    return db.to_db(since)


def thresholds_for(mess):
    """This hall's thresholds under its college's (tunable) rules."""
    s = db.get_college_settings(mess["college_id"])
    return {
        "category": rules.category_threshold(mess.get("capacity"), s),
        "mess": rules.mess_threshold(mess.get("capacity"), s),
        "fast_lane": s["fast_lane_reporters"],
        "fast_lane_hours": s["fast_lane_hours"],
        "window_days": s["window_days"],
    }


def check_complaint_allowed(college_id, mess_id, student_email):
    """None if the student may file a complaint here, else a reason code."""
    if not db.is_authorized_email(college_id, student_email):
        return "unauthorized"
    mess = db.get_mess_hall(mess_id)
    if not mess or mess["college_id"] != college_id:
        return "unauthorized"
    if db.student_complaint_count_since(student_email, mess_id, _since(days=1)) >= MAX_COMPLAINTS_PER_STUDENT_PER_MESS_PER_DAY:
        return "rate_limited"
    return None


def _raise(mess_id, complaint_id, level, reason, pattern_key):
    alert_id = db.insert_alert(mess_id, "complaint_pattern", complaint_id, level, reason, FSSAI_COMPLAINT_REF, pattern_key)
    notify.alert_raised(alert_id)
    return alert_id


def evaluate_complaint(complaint_id, mess_id, category):
    """After a complaint is stored: does it complete a pattern? Returns a
    dict describing progress and any alert raised."""
    mess = db.get_mess_hall(mess_id)
    t = thresholds_for(mess)
    days = t["window_days"]
    key_category = f"mess{mess_id}_category_{category}"
    key_fast = f"mess{mess_id}_fastlane_{category}"
    key_mess = f"mess{mess_id}_all_categories"

    category_count = db.count_reporters(mess_id, _pattern_window_start(key_category, days=days), category=category)
    mess_count = db.count_reporters(mess_id, _pattern_window_start(key_mess, days=days))
    result = {"alert_id": None, "level": None, "category_count": category_count, "mess_count": mess_count,
              "fast_lane": rules.is_fast_lane(category), **{f"{k}_threshold": v for k, v in t.items()
                                                            if k in ("category", "mess", "fast_lane")},
              "window_days": days, "fast_lane_hours": t["fast_lane_hours"]}

    if rules.is_fast_lane(category):
        fast_count = db.count_reporters(mess_id, _pattern_window_start(key_fast, hours=t["fast_lane_hours"]),
                                        category=category)
        result["fast_lane_count"] = fast_count
        if (fast_count >= t["fast_lane"] and not db.open_pattern_alert_exists(key_fast)
                and not db.open_pattern_alert_exists(key_category)):
            reason = (f"Possible outbreak: {fast_count} students reported '{category}' at this mess hall "
                      f"within {t['fast_lane_hours']} hours.")
            result.update(alert_id=_raise(mess_id, complaint_id, "High", reason, key_fast), level="High", reason=reason)
            return result

    if category_count >= t["category"] and not db.open_pattern_alert_exists(key_category) \
            and not db.open_pattern_alert_exists(key_fast):
        base = rules.COMPLAINT_CATEGORIES.get(category, "Low")
        level = rules.LEVELS[min(rules.LEVELS.index(base) + 1, len(rules.LEVELS) - 1)]
        reason = (f"Pattern confirmed: {category_count} students reported '{category}' at this mess hall "
                  f"in the last {days} days.")
        result.update(alert_id=_raise(mess_id, complaint_id, level, reason, key_category), level=level, reason=reason)
    elif mess_count >= t["mess"] and not db.open_pattern_alert_exists(key_mess):
        reason = (f"Pattern confirmed: {mess_count} students reported problems (all categories) at this mess "
                  f"hall in the last {days} days — broad issue.")
        result.update(alert_id=_raise(mess_id, complaint_id, "High", reason, key_mess), level="High", reason=reason)
    return result


def create_inspection(mess_id, staff, responses, general_notes=None, kitchen_code=None,
                      latitude=None, longitude=None, client_ref=None):
    """Validates and stores an inspection; raises an alert only if something
    failed. Returns (inspection_id, alert_id, level, score, reason) or raises
    ValueError listing unanswered items."""
    mess = db.get_mess_hall(mess_id)
    checklist = db.get_checklist(mess["college_id"])
    normalized, missing = rules.normalize_responses(responses, checklist)
    if missing:
        raise ValueError(missing)
    level, score, reason = rules.compute_inspection_severity(normalized)
    verified = bool(kitchen_code) and kitchen_code.strip().upper() == (mess.get("kitchen_code") or "").upper()
    inspection_id = db.insert_inspection(mess_id, staff, normalized, score, general_notes, verified, latitude,
                                         longitude, client_ref)
    alert_id = None
    if level:
        alert_id = db.insert_alert(mess_id, "inspection", inspection_id, level, reason, FSSAI_INSPECTION_REF)
        notify.alert_raised(alert_id)
    return inspection_id, alert_id, level, score, reason, verified


# ---------- Workflow ----------

TRANSITIONS = {
    # action: (from statuses, to status, capability)
    "acknowledge": (("open",), "acknowledged", "alert_work"),
    "start": (("open", "acknowledged"), "in_progress", "alert_work"),
    "mark_fixed": (("open", "acknowledged", "in_progress"), "fixed", "alert_work"),
    "reject_fix": (("fixed",), "in_progress", "alert_verify"),
    "verify": (("fixed",), "resolved", "alert_verify"),
}


class WorkflowError(Exception):
    pass


def transition(alert, action, note, actor):
    """Applies a workflow action. Raises WorkflowError with a user-facing
    message when it isn't allowed."""
    if action not in TRANSITIONS:
        raise WorkflowError("Unknown action.")
    from_statuses, to_status, _ = TRANSITIONS[action]
    if alert["status"] not in from_statuses:
        raise WorkflowError(f"Can't {action.replace('_', ' ')} an alert that is {alert['status'].replace('_', ' ')}.")
    if action == "mark_fixed" and not db.has_evidence(alert["id"]):
        raise WorkflowError("Add proof first — a photo of the fix or a follow-up inspection.")
    if action in ("mark_fixed", "reject_fix", "verify") and not (note or "").strip():
        raise WorkflowError("Add a note describing what was done (or why the fix was rejected).")
    event_note = note.strip() if note else ""
    if not db.set_status(alert["id"], to_status, event_note, actor, expected_from=from_statuses):
        raise WorkflowError("This alert changed in the meantime — refresh and try again.")


# ---------- Background: escalation & reminders ----------

def escalate_stale_alerts(days=ESCALATE_AFTER_DAYS):
    escalated = 0
    for alert in db.stale_alerts_for_escalation(days):
        idx = rules.LEVELS.index(alert["level"])
        if idx >= len(rules.LEVELS) - 1:
            continue
        new_level = rules.LEVELS[idx + 1]
        why = ("in progress past its due date" if alert["status"] == "in_progress"
               else f"not acted on for {days}+ days")
        db.escalate_alert(alert["id"], new_level,
                          f"Auto-escalated: {why} — now handled by {rules.get_authority(new_level)}")
        notify.alert_raised(alert["id"], kind="alert_escalated")
        escalated += 1
    return escalated


def remind_high_alerts(every_days=HIGH_REMINDER_EVERY_DAYS):
    """High has nowhere further to escalate, so it keeps reminding."""
    reminded = 0
    for alert in db.high_alerts_needing_reminder(every_days):
        age = ceil((db.utcnow() - alert["created_at"]).total_seconds() / 86400)
        db.mark_reminded(alert["id"], alert["level"], f"Still unresolved after {age} days")
        notify.alert_raised(alert["id"], kind="alert_reminder", extra=f"This alert has been open for {age} days.")
        reminded += 1
    return reminded
