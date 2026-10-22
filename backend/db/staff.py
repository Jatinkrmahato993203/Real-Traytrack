"""db/staff.py — staff accounts (admins, authorities, inspectors, auditors)."""

from .core import transaction, fetch_all, fetch_one, now_iso

STAFF_PUBLIC_COLUMNS = (
    "staff_users.id, staff_users.name, staff_users.email, staff_users.role, staff_users.college_id, "
    "staff_users.mess_id, staff_users.active, staff_users.created_at, colleges.name AS college_name, "
    "mess_halls.name AS mess_name, staff_users.totp_enabled_at IS NOT NULL AS two_factor_enabled"
)
_FROM = (
    "FROM staff_users LEFT JOIN colleges ON staff_users.college_id = colleges.id "
    "LEFT JOIN mess_halls ON staff_users.mess_id = mess_halls.id "
)


def count_staff():
    return fetch_one("SELECT COUNT(*) AS cnt FROM staff_users")["cnt"]


def count_active_global_admins():
    return fetch_one(
        "SELECT COUNT(*) AS cnt FROM staff_users WHERE role = 'admin' AND college_id IS NULL AND active = 1"
    )["cnt"]


def create_staff(name, email, role, college_id, password_hash, mess_id=None):
    with transaction() as cur:
        cur.execute(
            "INSERT INTO staff_users (name, email, role, college_id, mess_id, password_hash, active, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 1, %s)",
            (name.strip(), email.strip().lower(), role, college_id, mess_id, password_hash, now_iso()),
        )
        return cur.lastrowid


def get_staff(staff_id):
    """Public fields only — never the password hash."""
    return fetch_one(f"SELECT {STAFF_PUBLIC_COLUMNS} {_FROM} WHERE staff_users.id = %s", (staff_id,))


def get_staff_login(email):
    """Includes password_hash — only for checking a login attempt."""
    return fetch_one("SELECT * FROM staff_users WHERE email = %s", ((email or "").strip().lower(),))


def list_staff(college_id=None, roles=None, active_only=False):
    where, params = ["1=1"], []
    if college_id:
        where.append("staff_users.college_id = %s")
        params.append(college_id)
    if roles:
        where.append("staff_users.role IN (" + ", ".join(["%s"] * len(roles)) + ")")
        params += list(roles)
    if active_only:
        where.append("staff_users.active = 1")
    return fetch_all(
        f"SELECT {STAFF_PUBLIC_COLUMNS} {_FROM} WHERE " + " AND ".join(where) +
        " ORDER BY staff_users.active DESC, staff_users.role, staff_users.name",
        params,
    )


def update_staff(staff_id, name=None, role=None, active=None, password_hash=None, mess_id=None, clear_mess=False):
    sets, params = [], []
    if name is not None:
        sets.append("name = %s")
        params.append(name.strip())
    if role is not None:
        sets.append("role = %s")
        params.append(role)
    if active is not None:
        sets.append("active = %s")
        params.append(1 if active else 0)
    if password_hash is not None:
        sets.append("password_hash = %s")
        params.append(password_hash)
    if mess_id is not None or clear_mess:
        sets.append("mess_id = %s")
        params.append(mess_id)
    if sets:
        with transaction() as cur:
            cur.execute(f"UPDATE staff_users SET {', '.join(sets)} WHERE id = %s", params + [staff_id])


# ---------- Two-factor (TOTP) ----------

def get_two_factor(staff_id):
    """Secret material — only for the 2FA code paths, never returned to clients."""
    import json
    row = fetch_one(
        "SELECT totp_secret, totp_pending_secret, totp_enabled_at, totp_last_step, recovery_codes "
        "FROM staff_users WHERE id = %s",
        (staff_id,),
    )
    if row:
        row["recovery_codes"] = json.loads(row["recovery_codes"]) if row["recovery_codes"] else []
    return row


def set_pending_two_factor(staff_id, secret):
    with transaction() as cur:
        cur.execute("UPDATE staff_users SET totp_pending_secret = %s WHERE id = %s", (secret, staff_id))


def enable_two_factor(staff_id, secret, step, recovery_hashes):
    import json
    with transaction() as cur:
        cur.execute(
            "UPDATE staff_users SET totp_secret = %s, totp_pending_secret = NULL, totp_enabled_at = %s, "
            "totp_last_step = %s, recovery_codes = %s WHERE id = %s",
            (secret, now_iso(), step, json.dumps(recovery_hashes), staff_id),
        )


def disable_two_factor(staff_id):
    with transaction() as cur:
        cur.execute(
            "UPDATE staff_users SET totp_secret = NULL, totp_pending_secret = NULL, totp_enabled_at = NULL, "
            "totp_last_step = NULL, recovery_codes = NULL WHERE id = %s",
            (staff_id,),
        )


def record_totp_step(staff_id, step):
    """Remember the last accepted step; returns False if it was already used
    (a concurrent replay of the same code)."""
    with transaction() as cur:
        cur.execute(
            "UPDATE staff_users SET totp_last_step = %s WHERE id = %s AND (totp_last_step IS NULL OR totp_last_step < %s)",
            (step, staff_id, step),
        )
        return cur.rowcount == 1


def use_recovery_code(staff_id, code_hash):
    """Consumes a recovery code; returns how many remain, or None if invalid."""
    import json
    with transaction() as cur:
        cur.execute("SELECT recovery_codes FROM staff_users WHERE id = %s FOR UPDATE", (staff_id,))
        row = cur.fetchone()
        codes = json.loads(row["recovery_codes"]) if row and row["recovery_codes"] else []
        if code_hash not in codes:
            return None
        codes.remove(code_hash)
        cur.execute("UPDATE staff_users SET recovery_codes = %s WHERE id = %s", (json.dumps(codes), staff_id))
        return len(codes)
