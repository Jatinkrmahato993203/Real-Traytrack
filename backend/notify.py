"""
notify.py — outgoing email, with every attempt recorded in `notifications`.

Without SMTP settings nothing is sent, but the attempt is still recorded as
"skipped_no_smtp" — so the app never claims an authority was notified when
they weren't, and admins can see what needs fixing (Admin → Notifications).
"""

import logging
import smtplib
from email.mime.text import MIMEText

import config
import db
from auth import mask_email
from fssai_rules import get_authority

logger = logging.getLogger("traytrack.notify")

ROLE_FOR_LEVEL = {"Low": "mess_head", "Medium": "principal", "High": "fssai"}
CONTACT_COLUMN = {"mess_head": "mess_head_email", "principal": "principal_email", "fssai": "fssai_contact_email"}


def smtp_configured():
    return bool(config.SMTP_EMAIL and config.SMTP_APP_PASSWORD)


def send(kind, to_email, subject, body, college_id=None, alert_id=None, recipient_role=None, record_as=None):
    """Sends one email and records the outcome. Never raises. `record_as`
    lets callers store a masked address (for students)."""
    shown = record_as or to_email
    if not to_email:
        db.notifications.record(kind, "skipped_no_contact", college_id, alert_id, recipient_role, None, subject)
        logger.warning("[%s] No %s contact set — not sent: %s", kind, recipient_role, subject)
        return False
    if not smtp_configured():
        db.notifications.record(kind, "skipped_no_smtp", college_id, alert_id, recipient_role, shown, subject)
        logger.warning("[%s] SMTP not configured — would have emailed %s: %s", kind, shown, subject)
        return False
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = config.SMTP_EMAIL
    msg["To"] = to_email
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as server:
            if config.SMTP_STARTTLS:
                server.starttls()
            server.login(config.SMTP_EMAIL, config.SMTP_APP_PASSWORD)
            server.sendmail(config.SMTP_EMAIL, [to_email], msg.as_string())
        db.notifications.record(kind, "sent", college_id, alert_id, recipient_role, shown, subject)
        return True
    except Exception as e:  # network, auth, refused recipient...
        db.notifications.record(kind, "failed", college_id, alert_id, recipient_role, shown, subject, str(e))
        logger.error("[%s] Failed to email %s: %s", kind, shown, e)
        return False


def _contact(college, role):
    return college.get(CONTACT_COLUMN[role]) if college else None


def alert_raised(alert_id, kind="alert_created", extra=""):
    """Emails the authority for the alert's current level. For High alerts
    the principal is copied too, since FSSAI is outside the college."""
    try:
        alert = db.get_alert(alert_id)
        if not alert:
            return
        college = db.get_college(alert["college_id"])
        role = ROLE_FOR_LEVEL.get(alert["level"], "mess_head")
        verb = {"alert_created": "raised", "alert_escalated": "escalated", "alert_reminder": "still unresolved"}[kind]
        subject = f"[TrayTrack] {alert['level']} alert {verb} at {alert['mess_name']} — action needed"
        body = (
            f"Hello,\n\n"
            f"Alert #{alert_id} at {alert['mess_name']} ({alert['college_name']}) is {verb} and is with you as "
            f"the {get_authority(alert['level'])}.\n\n"
            f"Severity: {alert['level']}\nStatus: {alert['status'].replace('_', ' ')}\nReason: {alert['reason']}\n"
            + (f"Reference: {alert['fssai_reference']}\n" if alert.get("fssai_reference") else "")
            + (f"\n{extra}\n" if extra else "")
            + f"\nReview it here: {config.APP_BASE_URL}/admin/alerts?alert={alert_id}\n"
            "Unresolved alerts escalate automatically after 7 days.\n"
        )
        send(kind, _contact(college, role), subject, body, alert["college_id"], alert_id, role)
        if alert["level"] == "High" and role != "principal":
            send(kind, _contact(college, "principal"), subject, body, alert["college_id"], alert_id, "principal")
    except Exception as e:
        logger.error("Notification for alert %s failed: %s", alert_id, e)


def complaint_update(complaint, status, response):
    """Lets the student know their complaint was handled (best effort)."""
    try:
        subject = f"[TrayTrack] Update on your complaint about {complaint['mess_name']}"
        body = (
            f"Hello,\n\nYour complaint ({complaint['category']}) at {complaint['mess_name']} is now: "
            f"{status.replace('_', ' ')}.\n\n"
            + (f"Response from the mess team:\n{response}\n\n" if response else "")
            + f"See all your reports: {config.APP_BASE_URL}/my-reports\n"
        )
        send("complaint_update", complaint["student_email"], subject, body, complaint["college_id"],
             recipient_role="student", record_as=mask_email(complaint["student_email"]))
    except Exception as e:
        logger.error("Student notification failed: %s", e)


def setup_health():
    """Per college: which alert contacts are missing, plus SMTP status."""
    colleges = db.list_colleges()
    return {
        "smtp_configured": smtp_configured(),
        "colleges": [
            {
                "college_id": c["id"], "college_name": c["name"],
                "missing_contacts": [role for role, col in CONTACT_COLUMN.items() if not c.get(col)],
                "recent_failures": db.notifications.recent_failures(c["id"]),
            }
            for c in colleges
        ],
    }
