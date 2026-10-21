"""
fssai_rules.py — Severity logic aligned to FSSAI's Schedule 4 hygiene &
sanitary requirements (Food Safety and Standards Regulations). This is a
practical checklist inspired by those requirements, not a legal substitute
for an official FSSAI audit.

Items marked critical=True are "must-pass" — failing even one automatically
triggers a High alert regardless of overall score.
"""

CHECKLIST = [
    {"id": "temp_control", "text": "Hot food held above 60°C / cold food below 5°C", "critical": True},
    {"id": "raw_cooked_segregation", "text": "Raw and cooked food stored/prepped separately", "critical": True},
    {"id": "potable_water", "text": "Water used for cooking/drinking is potable & tested", "critical": True},
    {"id": "pest_control", "text": "No pest sighting; pest control measures active", "critical": True},
    {"id": "expiry_check", "text": "All ingredients within expiry, checked before use", "critical": True},
    {"id": "staff_hygiene", "text": "Staff wearing clean aprons, gloves, head cover", "critical": False},
    {"id": "handwash", "text": "Handwashing stations available and used", "critical": False},
    {"id": "waste_disposal", "text": "Waste bins covered, disposed of regularly", "critical": False},
    {"id": "surface_cleanliness", "text": "Cooking surfaces & utensils visibly clean", "critical": False},
    {"id": "floor_walls", "text": "Kitchen floor/walls clean, no water logging", "critical": False},
    {"id": "food_covered", "text": "Food kept covered during serving", "critical": False},
    {"id": "license_displayed", "text": "Valid FSSAI license displayed", "critical": False},
]

# Category -> base severity. Covers both food-safety-critical issues and
# everyday quality complaints.
COMPLAINT_CATEGORIES = {
    "Food poisoning / illness reported": "High",
    "Insect in food": "High",
    "Foreign object (non-insect) in food": "High",
    "Undercooked food": "Medium",
    "Stale or spoiled food": "Medium",
    "Hygiene issue (utensils/serving area)": "Medium",
    "Too oily": "Low",
    "Overcooked / burnt": "Low",
    "Too spicy": "Low",
    "Other": "Low",
}

LEVELS = ["Low", "Medium", "High"]

# Each severity level maps to the authority responsible for handling it.
# Escalation (Low -> Medium -> High) is literally handing the issue up
# this chain of command.
LEVEL_AUTHORITY = {
    "Low": "Mess Head",
    "Medium": "Principal",
    "High": "FSSAI",
}


def get_authority(level: str) -> str:
    return LEVEL_AUTHORITY.get(level, "Unknown")


def compute_inspection_severity(responses: dict):
    """responses: {item_id: bool} — True = passed that check.
    Returns (level, score, reason); level is None when every item passed."""
    failed_critical = [item["text"] for item in CHECKLIST if item["critical"] and not responses.get(item["id"], False)]
    total = len(CHECKLIST)
    passed = sum(1 for item in CHECKLIST if responses.get(item["id"], False))
    score = round((passed / total) * 100, 1)

    if passed == total:
        # Nothing to act on — the inspection is still recorded as evidence,
        # but no alert is opened (it would otherwise sit "open" with nothing
        # for the Mess Head to fix).
        level = None
        reason = "All checklist items passed — no issues found"
    elif failed_critical:
        level = "High"
        reason = "Critical FSSAI non-conformance: " + "; ".join(failed_critical)
    elif score < 60:
        level = "High"
        reason = f"Overall hygiene score {score}% — below acceptable threshold (60%)"
    elif score < 85:
        level = "Medium"
        reason = f"Overall hygiene score {score}% — minor non-conformances present"
    else:
        level = "Low"
        reason = f"Overall hygiene score {score}% — compliant, minor observations only"

    return level, score, reason


def compute_complaint_severity(category: str, recent_count: int):
    """Base severity from category, escalated by one level if 3+ similar
    complaints land in the same mess within 24 hours (pattern signal)."""
    base_level = COMPLAINT_CATEGORIES.get(category, "Low")
    idx = LEVELS.index(base_level)

    escalated = False
    if recent_count >= 3 and idx < len(LEVELS) - 1:
        idx += 1
        escalated = True

    level = LEVELS[idx]
    reason = f"Complaint category: {category}"
    if escalated:
        reason += f" — escalated: {recent_count} similar complaints in past 24h"
    return level, reason
