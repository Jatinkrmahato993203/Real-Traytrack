"""
email_service.py — sends real alert emails to the Mess Head / Principal /
FSSAI contact when an alert is created or escalated.

Uses a Gmail account (via an App Password, not the real account password)
as the sender. Set these in .env:
  SMTP_EMAIL=your-sending-account@gmail.com
  SMTP_APP_PASSWORD=your16charapppassword

If these aren't set, sending is silently skipped (logged, not crashed) —
so the rest of the app keeps working even before email is configured.
"""

import os
import smtplib
from email.mime.text import MIMEText

SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD", "")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

LEVEL_ROLE = {"Low": "Mess Head", "Medium": "Principal", "High": "FSSAI"}


def send_alert_email(to_email: str, mess_name: str, level: str, reason: str, fssai_reference: str = ""):
    if not to_email:
        print(f"[email_service] No contact email set for this college/level ({level}) — skipping send.")
        return False

    if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        print(f"[email_service] SMTP not configured — would have emailed {to_email}: {reason}")
        return False

    role = LEVEL_ROLE.get(level, "Admin")
    subject = f"[TrayTrack] {level} alert at {mess_name} — action needed"
    body = (
        f"Hello,\n\n"
        f"An alert has been raised at {mess_name}, escalated to you as the {role}.\n\n"
        f"Severity: {level}\n"
        f"Reason: {reason}\n"
    )
    if fssai_reference:
        body += f"Reference: {fssai_reference}\n"
    body += (
        "\nPlease log into the TrayTrack Admin Panel to review and resolve this alert.\n"
        "If it remains unresolved for 7 days, it will auto-escalate further.\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.sendmail(SMTP_EMAIL, [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"[email_service] Failed to send to {to_email}: {e}")
        return False
