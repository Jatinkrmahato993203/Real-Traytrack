"""
permissions.py — what each staff role may do, in one table.

Scope is separate from capability: every account is limited to one college
(or all colleges, college_id NULL), and a mess head may additionally be
limited to one mess hall (mess_id). See deps.py for how scope is enforced.
"""

ROLES = {
    "admin": "Admin — everything, including colleges, staff and setup",
    "principal": "Principal — oversees the college: handles and verifies alerts, replies to complaints",
    "mess_head": "Mess Head — handles alerts and complaints for their mess hall",
    "inspector": "Inspector — runs inspections and sees student complaints",
    "auditor": "Auditor (e.g. FSSAI officer) — read-only access to everything in scope",
}

# view            see complaints, alerts, inspections, compliance, activity
# view_complaints see complaints only (inspectors, for the hall they inspect)
# respond         reply to / change the status of student complaints
# alert_work      acknowledge, start, mark fixed, add evidence, assign
# alert_verify    verify a fix (close an alert) and reopen alerts
# inspect         submit inspections
# schedule        create/delete scheduled inspections
# compliance_edit add/remove compliance records
# export          download CSV exports
# setup           mess halls, contacts, checklist, kitchen codes
# manage_staff    create and change staff accounts
CAPABILITIES = {
    "admin": {"view", "view_complaints", "respond", "alert_work", "alert_verify", "inspect", "schedule",
              "compliance_edit", "export", "setup", "manage_staff"},
    "principal": {"view", "view_complaints", "respond", "alert_work", "alert_verify", "schedule",
                  "compliance_edit", "export"},
    "mess_head": {"view", "view_complaints", "respond", "alert_work", "compliance_edit"},
    "inspector": {"view_complaints", "inspect"},
    "auditor": {"view", "view_complaints", "export"},
}

# The part of the live activity feed each role may see (None = everything).
ACTIVITY_PREFIXES = {
    "inspector": ("complaint_submitted", "inspection_"),
}


def can(staff, capability):
    return capability in CAPABILITIES.get(staff["role"], set())


def capabilities(staff):
    return sorted(CAPABILITIES.get(staff["role"], set()))
