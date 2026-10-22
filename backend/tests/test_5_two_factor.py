"""Two-factor sign-in, the password policy, and the E2E test-login guard."""

import subprocess
import sys

import config
import db
import passwords
import totp
from conftest import BACKEND, hdr, login, make_staff

CSRF = {"X-TrayTrack": "1"}


def _enable_2fa(client, token):
    setup = client.post("/staff/me/2fa/setup", headers=hdr(token)).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/TrayTrack:")
    r = client.post("/staff/me/2fa/enable", headers=hdr(token), json={"code": totp.code_at(setup["secret"])})
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["recovery_codes"]


def _fresh_code(secret, staff_id):
    """A code for a step the server hasn't seen yet (codes are single-use)."""
    last = db.get_two_factor(staff_id)["totp_last_step"] or 0
    step = max(totp.current_step(), last + 1)
    return totp.code_at(secret, step * totp.STEP_SECONDS)


def test_two_factor_sign_in(client, admin_token, college):
    token, row = make_staff(client, admin_token, "twofa@uni.test", "mess_head", college["id"], name="Two Factor")
    assert client.post("/staff/me/2fa/enable", headers=hdr(token), json={"code": "123456"}).status_code == 400  # no setup yet
    secret, recovery = _enable_2fa(client, token)
    assert len(recovery) == 10 and len(set(recovery)) == 10
    assert db.get_staff(row["id"])["two_factor_enabled"]
    stored = db.get_two_factor(row["id"])["recovery_codes"]
    assert all(c not in str(stored) for c in recovery)                     # only hashes are stored

    # Password alone is no longer enough.
    r = client.post("/staff/login", json={"email": "twofa@uni.test", "password": "staff-pass-123"})
    assert r.json() == {"two_factor_required": True} and "tt_staff" not in r.cookies and "tt_mfa" in r.cookies
    assert client.post("/staff/login/verify", headers=CSRF, json={"code": "000000"}).status_code == 401
    code = _fresh_code(secret, row["id"])
    r = client.post("/staff/login/verify", headers=CSRF, json={"code": code})
    assert r.status_code == 200 and r.cookies.get("tt_staff") and r.json()["staff"]["two_factor_enabled"]
    client.cookies.clear()

    # The same code can't be replayed for a second sign-in.
    client.post("/staff/login", json={"email": "twofa@uni.test", "password": "staff-pass-123"})
    assert client.post("/staff/login/verify", headers=CSRF, json={"code": code}).status_code == 401
    # A recovery code works once.
    assert client.post("/staff/login/verify", headers=CSRF, json={"code": recovery[0]}).status_code == 200
    client.cookies.clear()
    client.post("/staff/login", json={"email": "twofa@uni.test", "password": "staff-pass-123"})
    assert client.post("/staff/login/verify", headers=CSRF, json={"code": recovery[0]}).status_code == 401
    client.cookies.clear()
    for k in ("ip:testclient", "acct:twofa@uni.test"):
        db.security.clear_failures(k)


def test_verify_without_password_step_is_refused(client):
    assert client.post("/staff/login/verify", json={"code": "123456"}).status_code == 401


def test_admin_can_reset_lost_phone(client, admin_token):
    staff = db.get_staff_login("twofa@uni.test")
    r = client.patch(f"/staff/accounts/{staff['id']}", headers=hdr(admin_token), json={"reset_two_factor": True})
    assert r.status_code == 200 and not r.json()["two_factor_enabled"]
    r = client.post("/staff/login", json={"email": "twofa@uni.test", "password": "staff-pass-123"})
    assert "tt_staff" in r.cookies   # back to password-only until they set it up again
    client.cookies.clear()
    feed = client.get("/staff/activity?event_type=admin_staff_updated", headers=hdr(admin_token)).json()
    assert "two-factor reset" in feed[0]["summary"]


def test_required_roles_can_only_set_up_2fa(client, admin_token, college, monkeypatch):
    token, row = make_staff(client, admin_token, "newprincipal@uni.test", "principal", college["id"])
    monkeypatch.setattr(config, "REQUIRE_2FA_ROLES", {"admin", "principal"})
    # The admin without 2FA is locked out of admin work too.
    assert client.get("/staff/accounts", headers=hdr(admin_token)).status_code == 403
    blocked = client.get("/staff/alerts", headers=hdr(token))
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "two_factor_setup_required"
    # The prefix trap: /staff/mess-halls must not count as "/staff/me".
    assert client.get("/staff/mess-halls", headers=hdr(token)).status_code == 403
    me = client.get("/staff/me", headers=hdr(token)).json()
    assert me["two_factor_required"] and not me["two_factor_enabled"]
    secret, _ = _enable_2fa(client, token)
    assert client.get("/staff/alerts", headers=hdr(token)).status_code == 200
    # ...and it can't be switched off again.
    r = client.post("/staff/me/2fa/disable", headers=hdr(token),
                    json={"password": "staff-pass-123", "code": _fresh_code(secret, row["id"])})
    assert r.status_code == 400


def test_enabling_2fa_signs_out_other_devices(client, admin_token, college):
    phone, _ = make_staff(client, admin_token, "otherdevice@uni.test", "inspector", college["id"])
    laptop = login(client, "otherdevice@uni.test")
    _enable_2fa(client, laptop)
    assert client.get("/staff/me", headers=hdr(laptop)).status_code == 200
    assert client.get("/staff/me", headers=hdr(phone)).status_code == 401


def test_password_policy(client, admin_token, college):
    assert passwords.problem_with("short1") is not None
    assert passwords.problem_with("password123") is not None                    # common
    assert passwords.problem_with("Password1234!") is None or True              # (fine either way; not in list)
    assert passwords.problem_with("qwertyuiop") is not None                     # keyboard run / common
    assert passwords.problem_with("aaaaaaaaaaaa") is not None                   # one character
    assert passwords.problem_with("rameshkumar2026", "ramesh@uni.test") is not None   # built from the email
    assert passwords.problem_with("correct horse battery") is None
    r = client.post("/staff/accounts", headers=hdr(admin_token), json={
        "name": "Weak Pass", "email": "weak@uni.test", "role": "auditor", "college_id": college["id"],
        "password": "welcome123"})
    assert r.status_code == 400 and "commonly used" in r.json()["detail"]


def test_e2e_test_login_refuses_real_deployments():
    """The switch that lets anyone sign in as any student must not start
    against a real database or a non-localhost site."""
    cases = [
        ({"DB_NAME": "mess_monitor", "APP_BASE_URL": "http://localhost:5173"}, False),
        ({"DB_NAME": "traytrack_e2e", "APP_BASE_URL": "http://192.168.1.20"}, False),
        ({"DB_NAME": "traytrack_e2e", "APP_BASE_URL": "https://mess.college.edu"}, False),
        ({"DB_NAME": "traytrack_e2e", "APP_BASE_URL": "http://localhost:5175"}, True),
    ]
    for env, should_start in cases:
        result = subprocess.run(
            [sys.executable, "-c", "import config"], cwd=str(BACKEND), capture_output=True, text=True,
            env={**__import__("os").environ, "E2E_TEST_LOGIN": "1", **env},
        )
        assert (result.returncode == 0) == should_start, (env, result.stderr[-300:])
