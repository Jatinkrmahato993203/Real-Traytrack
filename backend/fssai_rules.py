"""
fssai_rules.py — severity logic aligned to FSSAI's Schedule 4 hygiene &
sanitary requirements (Food Safety and Standards Regulations). This is a
practical checklist inspired by those requirements, not a legal substitute
for an official FSSAI audit.

Items marked critical=True are "must-pass" — failing even one automatically
triggers a High alert regardless of overall score.
"""

import math

# Seeds the database's default checklist (checklist_items, college_id NULL).
# After the first start, admins edit the checklist in the Admin Panel.
DEFAULT_CHECKLIST = [
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
    "Drinking water quality": "Medium",
    "Too oily": "Low",
    "Overcooked / burnt": "Low",
    "Too spicy": "Low",
    "Quantity / portion size": "Low",
    "Staff behaviour": "Low",
    "Other": "Low",
}

MEALS = ["breakfast", "lunch", "snacks", "dinner"]

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


# ---------- Complaint pattern thresholds ----------

PATTERN_WINDOW_DAYS = 30
# Safety-critical categories don't wait for 20 people: a few independent
# reports in a short window is already an outbreak signal.
FAST_LANE_REPORTERS = 3
FAST_LANE_HOURS = 48
DEFAULT_CATEGORY_THRESHOLD = 20
DEFAULT_MESS_THRESHOLD = 45


def is_fast_lane(category: str) -> bool:
    return COMPLAINT_CATEGORIES.get(category) == "High"


def category_threshold(capacity):
    """Distinct reporters needed in one category within the window. Scales
    with how many people eat at the hall (5% of diners, between 5 and 20),
    so a 150-seat hall isn't held to the same bar as a 2,000-seat one."""
    if not capacity:
        return DEFAULT_CATEGORY_THRESHOLD
    return max(5, min(DEFAULT_CATEGORY_THRESHOLD, math.ceil(capacity * 0.05)))


def mess_threshold(capacity):
    """Distinct reporters of anything at the hall (10% of diners, 10–45)."""
    if not capacity:
        return DEFAULT_MESS_THRESHOLD
    return max(10, min(DEFAULT_MESS_THRESHOLD, math.ceil(capacity * 0.10)))


# ---------- Inspections ----------

RESULTS = ("pass", "fail", "na")


def normalize_responses(responses: dict, checklist: list):
    """Turns submitted answers into {item_key: {result, note, text, critical}}
    for exactly the items on the checklist. Accepts the old format
    ({key: bool}) too. Returns (normalized, missing_keys) — every item must be
    answered explicitly; nothing is assumed to pass."""
    normalized, missing = {}, []
    for item in checklist:
        raw = responses.get(item["item_key"])
        if isinstance(raw, bool):
            raw = {"result": "pass" if raw else "fail"}
        if not isinstance(raw, dict) or raw.get("result") not in RESULTS:
            missing.append(item["item_key"])
            continue
        normalized[item["item_key"]] = {
            "result": raw["result"],
            "note": str(raw.get("note") or "")[:500],
            "text": item["text"],
            "critical": bool(item["critical"]),
        }
    return normalized, missing


def compute_inspection_severity(normalized: dict):
    """normalized: output of normalize_responses. N/A items don't count
    either way. Returns (level, score, reason); level is None when nothing
    failed (no alert needed)."""
    applicable = [r for r in normalized.values() if r["result"] != "na"]
    failed = [r for r in applicable if r["result"] == "fail"]
    failed_critical = [r["text"] for r in failed if r["critical"]]
    score = round(100 * (len(applicable) - len(failed)) / len(applicable), 1) if applicable else 100.0

    if not failed:
        # Nothing to act on — the inspection is still recorded as evidence,
        # but no alert is opened.
        return None, score, "All applicable checklist items passed — no issues found"
    if failed_critical:
        return "High", score, "Critical FSSAI non-conformance: " + "; ".join(failed_critical)
    if score < 60:
        return "High", score, f"Overall hygiene score {score}% — below acceptable threshold (60%)"
    if score < 85:
        return "Medium", score, f"Overall hygiene score {score}% — minor non-conformances present"
    return "Low", score, f"Overall hygiene score {score}% — minor observations: " + "; ".join(r["text"] for r in failed)
