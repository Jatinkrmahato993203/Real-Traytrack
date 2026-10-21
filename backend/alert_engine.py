"""
alert_engine.py — turns raw inspection/complaint data into alerts, and
handles the 7-day auto-escalation rule.

Escalation rule: any alert unresolved 7 days after creation (or after its
last escalation) automatically moves up one severity level, which is also
a handoff up the authority chain: Mess Head -> Principal -> FSSAI.
"""

import json
from datetime import datetime, timedelta
import database as db
import fssai_rules as rules
import email_service


def _notify(mess_id, level, reason, fssai_reference=""):
    """Looks up the real contact for this college+level and emails them.
    Never raises — a failed/unconfigured email should never break the
    alert itself from being recorded."""
    try:
        mess = db.get_mess_hall(mess_id)
        if not mess:
            return
        contact_email = db.get_contact_email_for_level(mess["college_id"], level)
        email_service.send_alert_email(contact_email, mess["name"], level, reason, fssai_reference)
    except Exception as e:
        print(f"[alert_engine] Notification failed (alert still recorded): {e}")


def create_inspection_alert(mess_id, inspector_name, responses: dict, inspector_id=None):
    level, score, reason = rules.compute_inspection_severity(responses)
    inspection_id = db.insert_inspection(mess_id, inspector_name, json.dumps(responses), score, inspector_id)
    if level is None:  # clean inspection: recorded, but nothing to alert on
        return None, None, score, reason
    fssai_ref = "FSSAI Schedule 4 — Sanitary & Hygiene Requirements"
    alert_id = db.insert_alert(
        mess_id=mess_id,
        source="inspection",
        source_id=inspection_id,
        level=level,
        reason=reason,
        fssai_reference=fssai_ref,
    )
    _notify(mess_id, level, reason, fssai_ref)
    return alert_id, level, score, reason


CATEGORY_THRESHOLD = 20  # distinct students, same category, same mess, within the window
MESS_THRESHOLD = 45      # distinct students, any category, same mess, within the window
PATTERN_WINDOW_DAYS = 30
MAX_COMPLAINTS_PER_STUDENT_PER_MESS_PER_DAY = 3


def _pattern_window_start(pattern_key):
    """Complaints count toward a pattern only if they're inside the rolling
    window AND newer than the pattern's last resolution. So old complaints
    age out, and a resolved alert re-arms instead of being used up forever."""
    since = datetime.utcnow() - timedelta(days=PATTERN_WINDOW_DAYS)
    last_resolved = db.last_pattern_resolution(pattern_key)
    if last_resolved and last_resolved > since:
        since = last_resolved
    return since.strftime("%Y-%m-%d %H:%M:%S")


def create_complaint_alert(college_id, mess_id, student_email, student_name, category, description, photo_path=None):
    """Validates the student's email domain matches the selected college
    (and that the mess belongs to that college) before accepting the
    complaint. Returns None, None, "unauthorized", None, None if not, or
    None, None, "rate_limited", None, None if this student has hit the
    daily cap for this mess.

    Every valid complaint is always stored (kept as proof/evidence), but an
    alert is only raised once a pattern is confirmed — 20+ DISTINCT
    students reporting the same category at this mess, or 45+ distinct
    students reporting anything at this mess, within the last 30 days. This
    avoids a single complaint (or a single account filing many) triggering
    escalation on its own. While a pattern's alert is open, it won't
    trigger a duplicate; once resolved, it can fire again if the problem
    comes back.

    Returns: (alert_id or None, level or None, reason, category_count, mess_count)
    """
    if not db.is_authorized_email(college_id, student_email):
        return None, None, "unauthorized", None, None

    mess = db.get_mess_hall(mess_id)
    if not mess or mess["college_id"] != college_id:
        return None, None, "unauthorized", None, None

    day_ago = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    if db.student_complaint_count_since(student_email, mess_id, day_ago) >= MAX_COMPLAINTS_PER_STUDENT_PER_MESS_PER_DAY:
        return None, None, "rate_limited", None, None

    complaint_id = db.insert_complaint(
        college_id, mess_id, student_email, student_name, category, description, photo_path
    )

    pattern_key_category = f"mess{mess_id}_category_{category}"
    pattern_key_mess = f"mess{mess_id}_all_categories"

    category_count = db.count_reporters(mess_id, _pattern_window_start(pattern_key_category), category=category)
    mess_count = db.count_reporters(mess_id, _pattern_window_start(pattern_key_mess))

    alert_id = None
    level = None
    reason = (
        f"Complaint recorded ({category_count} of {CATEGORY_THRESHOLD} students needed "
        f"for '{category}' at this mess in the last {PATTERN_WINDOW_DAYS} days)."
    )

    if category_count >= CATEGORY_THRESHOLD and not db.open_pattern_alert_exists(pattern_key_category):
        base_level = rules.COMPLAINT_CATEGORIES.get(category, "Low")
        idx = min(rules.LEVELS.index(base_level) + 1, len(rules.LEVELS) - 1)
        level = rules.LEVELS[idx]
        reason = (
            f"Pattern confirmed: {category_count} students reported '{category}' "
            f"at this mess hall in the last {PATTERN_WINDOW_DAYS} days — treated as a verified issue."
        )
        alert_id = db.insert_alert(
            mess_id=mess_id,
            source="complaint_pattern",
            source_id=complaint_id,
            level=level,
            reason=reason,
            fssai_reference="FSSAI consumer complaint escalation guidance",
            pattern_key=pattern_key_category,
        )
        _notify(mess_id, level, reason, "FSSAI consumer complaint escalation guidance")
    elif mess_count >= MESS_THRESHOLD and not db.open_pattern_alert_exists(pattern_key_mess):
        level = "High"
        reason = (
            f"Pattern confirmed: {mess_count} students reported problems (all categories) "
            f"at this mess hall in the last {PATTERN_WINDOW_DAYS} days — broad issue, treated as verified."
        )
        alert_id = db.insert_alert(
            mess_id=mess_id,
            source="complaint_pattern",
            source_id=complaint_id,
            level=level,
            reason=reason,
            fssai_reference="FSSAI consumer complaint escalation guidance",
            pattern_key=pattern_key_mess,
        )
        _notify(mess_id, level, reason, "FSSAI consumer complaint escalation guidance")

    return alert_id, level, reason, category_count, mess_count


def escalate_stale_alerts(days=7):
    """Call this periodically — cheap query, and guarantees no alert
    silently sits unresolved past the 1-week window."""
    stale = db.get_unresolved_stale_alerts(days=days)
    escalated_count = 0
    for alert in stale:
        idx = rules.LEVELS.index(alert["level"])
        if idx < len(rules.LEVELS) - 1:
            new_level = rules.LEVELS[idx + 1]
            db.escalate_alert(alert["id"], new_level)
            escalated_count += 1
            escalation_reason = (
                f"Auto-escalated: unresolved for {days}+ days. Original reason: {alert['reason']}"
            )
            _notify(alert["mess_id"], new_level, escalation_reason, alert.get("fssai_reference", ""))
    return escalated_count
