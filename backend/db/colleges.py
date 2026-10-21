"""db/colleges.py — colleges, their alert contacts, and mess halls."""

import secrets

from .core import transaction, fetch_all, fetch_one

# No 0/O/1/I so codes are easy to read off a printed sheet.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_kitchen_code():
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


# ---------- Colleges ----------

def list_colleges():
    return fetch_all("SELECT * FROM colleges ORDER BY name")


def list_colleges_public():
    """Only what students/the public need — no contact emails."""
    return fetch_all("SELECT id, name, email_domain, grievance_contact FROM colleges ORDER BY name")


def get_college(college_id):
    return fetch_one("SELECT * FROM colleges WHERE id = %s", (college_id,))


def get_college_by_domain(domain):
    return fetch_one("SELECT * FROM colleges WHERE email_domain = %s", (domain.strip().lower(),))


def add_college(name, email_domain, mess_head_email=None, principal_email=None, fssai_contact_email=None):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO colleges (name, email_domain, mess_head_email, principal_email, fssai_contact_email) "
            "VALUES (%s, %s, %s, %s, %s)",
            (name.strip(), email_domain.strip().lower().lstrip("@"),
             mess_head_email or None, principal_email or None, fssai_contact_email or None),
        )
        return cur.lastrowid


def update_college_contacts(college_id, mess_head_email=None, principal_email=None, fssai_contact_email=None):
    with transaction() as cur:
        cur.execute(
            "UPDATE colleges SET mess_head_email = %s, principal_email = %s, fssai_contact_email = %s WHERE id = %s",
            (mess_head_email or None, principal_email or None, fssai_contact_email or None, college_id),
        )


def delete_college(college_id):
    """Fails (foreign key) while mess halls still exist — callers surface that."""
    with transaction() as cur:
        cur.execute("DELETE FROM colleges WHERE id = %s", (college_id,))


def get_college_settings(college_id):
    """The college's alert rules: defaults overlaid with its own values."""
    import json
    from fssai_rules import merge_settings
    row = fetch_one("SELECT settings FROM colleges WHERE id = %s", (college_id,))
    return merge_settings(json.loads(row["settings"]) if row and row["settings"] else {})


def update_college_settings(college_id, changes):
    """Merges `changes` into the stored settings; a None value resets that
    setting to the default."""
    import json
    with transaction() as cur:
        cur.execute("SELECT settings FROM colleges WHERE id = %s FOR UPDATE", (college_id,))
        row = cur.fetchone()
        stored = json.loads(row["settings"]) if row and row["settings"] else {}
        for k, v in changes.items():
            if v is None:
                stored.pop(k, None)
            else:
                stored[k] = v
        cur.execute("UPDATE colleges SET settings = %s WHERE id = %s", (json.dumps(stored), college_id))


def update_grievance_contact(college_id, contact):
    with transaction() as cur:
        cur.execute("UPDATE colleges SET grievance_contact = %s WHERE id = %s",
                    ((contact or "").strip() or None, college_id))


CONTACT_FOR_LEVEL = {"Low": "mess_head_email", "Medium": "principal_email", "High": "fssai_contact_email"}


def get_contact_email_for_level(college_id, level):
    college = get_college(college_id)
    return college.get(CONTACT_FOR_LEVEL.get(level)) if college else None


def is_authorized_email(college_id, email):
    """A student is authorized if their email domain matches the college's
    registered domain — no per-student roster to maintain."""
    college = get_college(college_id)
    email = (email or "").strip().lower()
    return bool(college and "@" in email and email.split("@")[-1] == college["email_domain"])


# ---------- Mess halls ----------

def list_mess_halls(college_id=None, include_codes=False):
    cols = "*" if include_codes else "id, college_id, name, capacity"
    if college_id:
        return fetch_all(f"SELECT {cols} FROM mess_halls WHERE college_id = %s ORDER BY name", (college_id,))
    return fetch_all(f"SELECT {cols} FROM mess_halls ORDER BY name")


def get_mess_hall(mess_id):
    return fetch_one(
        "SELECT mess_halls.*, colleges.name AS college_name FROM mess_halls "
        "JOIN colleges ON mess_halls.college_id = colleges.id WHERE mess_halls.id = %s",
        (mess_id,),
    )


def add_mess_hall(college_id, name, capacity=None):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO mess_halls (college_id, name, capacity, kitchen_code) VALUES (%s, %s, %s, %s)",
            (college_id, name.strip(), capacity, new_kitchen_code()),
        )
        return cur.lastrowid


def update_mess_hall(mess_id, name=None, capacity=None, clear_capacity=False):
    sets, params = [], []
    if name is not None:
        sets.append("name = %s")
        params.append(name.strip())
    if capacity is not None or clear_capacity:
        sets.append("capacity = %s")
        params.append(capacity)
    if sets:
        with transaction() as cur:
            cur.execute(f"UPDATE mess_halls SET {', '.join(sets)} WHERE id = %s", params + [mess_id])


def ensure_kitchen_code(mess_id, regenerate=False):
    """Returns the hall's kitchen code, creating one if it has none."""
    with transaction() as cur:
        cur.execute("SELECT kitchen_code FROM mess_halls WHERE id = %s", (mess_id,))
        row = cur.fetchone()
        if not row:
            return None
        if row["kitchen_code"] and not regenerate:
            return row["kitchen_code"]
        code = new_kitchen_code()
        cur.execute("UPDATE mess_halls SET kitchen_code = %s WHERE id = %s", (code, mess_id))
        return code


def delete_mess_hall(mess_id):
    """Fails (foreign key) while complaints/inspections/alerts reference it."""
    with transaction() as cur:
        cur.execute("DELETE FROM mess_halls WHERE id = %s", (mess_id,))
