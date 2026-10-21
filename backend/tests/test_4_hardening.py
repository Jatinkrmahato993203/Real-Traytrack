"""Sessions in HttpOnly cookies, CSRF, revocation, expiry, rate limits,
security headers, tunable rules, insights, my-work, moderation, search,
and real SMTP delivery."""

import hashlib
import socket
import time

import pytest

import config
import db
import notify
from conftest import consented_student, hdr, jpeg_bytes, login, make_staff


# ---------- Sessions & cookies ----------

def test_login_sets_httponly_cookie_and_never_returns_the_token(client):
    r = client.post("/staff/login", json={"email": "admin@traytrack.test", "password": "bootstrap-pass-123"})
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200 and "token" not in r.json()
    assert "tt_staff=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    token = r.cookies["tt_staff"]
    # Only a hash is stored — a database leak doesn't leak usable sessions.
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sessions WHERE token_hash = %s", (token,))["n"] == 0
    # The cookie alone authenticates GETs.
    assert client.get("/staff/me").status_code == 200


def test_cookie_writes_need_the_csrf_header(client, college):
    login_resp = client.post("/staff/login", json={"email": "admin@traytrack.test", "password": "bootstrap-pass-123"})
    assert login_resp.status_code == 200
    body = {"college_id": college["id"], "name": "CSRF Hall"}
    forged = client.post("/staff/mess-halls", json=body)          # what a forged cross-site form would look like
    assert forged.status_code == 403 and "X-TrayTrack" in forged.json()["detail"]
    ok = client.post("/staff/mess-halls", json=body, headers={"X-TrayTrack": "1"})
    assert ok.status_code == 200
    client.delete(f"/staff/mess-halls/{ok.json()['id']}", headers={"X-TrayTrack": "1"})


def test_logout_revokes_the_session(client):
    r = client.post("/staff/login", json={"email": "admin@traytrack.test", "password": "bootstrap-pass-123"})
    token = r.cookies["tt_staff"]
    assert client.post("/staff/logout", headers={"X-TrayTrack": "1"}).status_code == 200
    client.cookies.clear()
    assert client.get("/staff/me", headers=hdr(token)).status_code == 401


def test_password_change_signs_out_other_devices_only(client, admin_token, college):
    phone, _ = make_staff(client, admin_token, "twodevices@uni.test", "auditor", college["id"])
    laptop = login(client, "twodevices@uni.test")
    r = client.post("/staff/me/password", headers=hdr(laptop),
                    json={"current_password": "staff-pass-123", "new_password": "brand-new-pass-1"})
    assert r.status_code == 200
    assert client.get("/staff/me", headers=hdr(laptop)).status_code == 200
    assert client.get("/staff/me", headers=hdr(phone)).status_code == 401


def test_deactivation_and_password_reset_end_every_session(client, admin_token, college):
    token, row = make_staff(client, admin_token, "revoked@uni.test", "inspector", college["id"])
    client.patch(f"/staff/accounts/{row['id']}", headers=hdr(admin_token), json={"active": False})
    client.patch(f"/staff/accounts/{row['id']}", headers=hdr(admin_token), json={"active": True})
    # Reactivating doesn't bring the old session back.
    assert client.get("/staff/me", headers=hdr(token)).status_code == 401
    token2 = login(client, "revoked@uni.test")
    client.patch(f"/staff/accounts/{row['id']}", headers=hdr(admin_token), json={"password": "admin-reset-123"})
    assert client.get("/staff/me", headers=hdr(token2)).status_code == 401


def test_idle_and_absolute_expiry(client, admin_token):
    import auth
    token = login(client, "admin@traytrack.test", "bootstrap-pass-123")
    h = hashlib.sha256(token.encode()).hexdigest()
    db.execute("UPDATE sessions SET expires_at = UTC_TIMESTAMP() - INTERVAL 1 MINUTE WHERE token_hash = %s", (h,))
    assert client.get("/staff/me", headers=hdr(token)).status_code == 401
    # Sliding: activity pushes expiry out, but never past created_at + max.
    token = login(client, "admin@traytrack.test", "bootstrap-pass-123")
    h = hashlib.sha256(token.encode()).hexdigest()
    db.execute("UPDATE sessions SET last_seen_at = UTC_TIMESTAMP() - INTERVAL 1 HOUR, "
               "created_at = UTC_TIMESTAMP() - INTERVAL 7 DAY + INTERVAL 30 MINUTE WHERE token_hash = %s", (h,))
    assert client.get("/staff/me", headers=hdr(token)).status_code == 200
    row = db.fetch_one("SELECT created_at, expires_at FROM sessions WHERE token_hash = %s", (h,))
    assert row["expires_at"] <= row["created_at"] + auth.STAFF_MAX


# ---------- Rate limits & headers ----------

def test_login_rate_limit(client, monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_SCALE", 1)
    db.execute("DELETE FROM rate_limits")
    # The app always sends X-TrayTrack (a cookie from the previous login is present).
    csrf = {"X-TrayTrack": "1"}
    codes = [client.post("/staff/login", headers=csrf,
                         json={"email": "admin@traytrack.test", "password": "bootstrap-pass-123"}).status_code
             for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429
    last = client.post("/staff/login", headers=csrf, json={"email": "admin@traytrack.test", "password": "bootstrap-pass-123"})
    assert int(last.headers["retry-after"]) >= 1
    db.execute("DELETE FROM rate_limits")


def test_public_read_limit(client, monkeypatch):
    import main
    monkeypatch.setattr(config, "RATE_LIMIT_SCALE", 0.01)   # 3 per minute
    main._public_hits.clear()
    codes = [client.get("/colleges").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    main._public_hits.clear()


def test_security_headers(client, admin_token):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    photo = db.fetch_one("SELECT file_name FROM inspection_photos WHERE file_name IS NOT NULL LIMIT 1")["file_name"]
    p = client.get(f"/staff/photos/{photo}", headers=hdr(admin_token))
    assert p.status_code == 200 and "sandbox" in p.headers["content-security-policy"]


# ---------- Tunable rules, insights, my-work ----------

def test_college_rules_are_tunable_and_validated(client, college, admin_token):
    base = f"/staff/colleges/{college['id']}/settings"
    r = client.get(base, headers=hdr(admin_token)).json()
    assert r["settings"]["fast_lane_reporters"] == 3
    assert client.patch(base, headers=hdr(admin_token), json={"fast_lane_reporters": 1}).status_code == 400
    assert client.patch(base, headers=hdr(admin_token), json={"category_min": 30, "category_max": 10}).status_code == 400
    assert client.patch(base, headers=hdr(admin_token), json={"nonsense": 4}).status_code == 400
    r = client.patch(base, headers=hdr(admin_token), json={"fast_lane_reporters": 2, "category_max": 6})
    assert r.status_code == 200 and r.json()["settings"]["fast_lane_reporters"] == 2
    # A new hall with no capacity now uses category_max = 6.
    hall = client.post("/staff/mess-halls", headers=hdr(admin_token), json={"college_id": college["id"], "name": "Tuned Hall"}).json()["id"]
    s = consented_student(client, "tuned@uni.test")
    r = client.post("/complaints", headers=hdr(s), data={"mess_id": hall, "category": "Too spicy"}).json()
    assert r["category_threshold"] == 6 and r["fast_lane_threshold"] == 2
    feed = client.get("/staff/activity?event_type=admin_settings", headers=hdr(admin_token)).json()
    assert "fast_lane_reporters 3→2" in feed[0]["summary"]
    # null resets to the default
    client.patch(base, headers=hdr(admin_token), json={"fast_lane_reporters": None, "category_max": None})
    assert client.get(base, headers=hdr(admin_token)).json()["settings"]["fast_lane_reporters"] == 3
    # mess heads can't change the rules
    head = login(client, "head@uni.test")
    assert client.patch(base, headers=hdr(head), json={"votes_needed": 1}).status_code == 403


def test_insights_and_threshold_simulation(client, college, admin_token):
    r = client.get(f"/staff/insights?college_id={college['id']}", headers=hdr(admin_token))
    assert r.status_code == 200
    data = r.json()
    assert data["totals"]["complaints"] > 0 and data["totals"]["alerts"] > 0
    curve = [p["alerts"] for p in data["simulation"]["category_curve"]]
    assert curve == sorted(curve, reverse=True)   # higher threshold, never more alerts
    fast = {p["threshold"]: p["alerts"] for p in data["simulation"]["fast_lane_curve"]}
    assert fast[3] >= 1                            # the food-poisoning outbreak in test_2
    assert data["totals"]["median_hours_to_first_action"] is not None


def test_my_work_counts(client, college, admin_token):
    principal = login(client, "principal@uni.test")
    work = client.get("/staff/my-work", headers=hdr(principal)).json()
    assert {"fixes_to_verify", "complaints_unanswered", "alerts_untouched"} <= set(work)
    inspector = login(client, "inspector@uni.test")
    work = client.get("/staff/my-work", headers=hdr(inspector)).json()
    assert set(work) == {"inspections_due", "inspections_assigned"}


# ---------- Moderation & search ----------

def test_staff_can_hide_abusive_text(client, college, admin_token):
    s = consented_student(client, "angry@uni.test")
    cid = client.post("/complaints", headers=hdr(s), data={
        "mess_id": college["big"], "category": "Staff behaviour", "description": "abusive words about a named cook"}).json()["complaint_id"]
    head = login(client, "head@uni.test")
    assert client.post(f"/staff/complaints/{cid}/hide", headers=hdr(head), json={"reason": "x"}).status_code == 403
    principal = login(client, "principal@uni.test")
    assert client.post(f"/staff/complaints/{cid}/hide", headers=hdr(principal), json={"reason": "Names a staff member"}).status_code == 200
    item = next(c for c in client.get("/staff/complaints?days=0&limit=200", headers=hdr(admin_token)).json()["items"] if c["id"] == cid)
    assert item["description"] is None and item["hidden_reason"] == "Names a staff member"
    feed = client.get("/staff/activity?event_type=complaint&limit=200", headers=hdr(admin_token)).text
    assert "abusive words" not in feed
    mine = next(c for c in client.get("/my-complaints", headers=hdr(s)).json() if c["id"] == cid)
    assert mine["hidden_reason"] == "Names a staff member"


def test_full_text_search(client, college, admin_token):
    s = consented_student(client, "searcher@uni.test")
    client.post("/complaints", headers=hdr(s), data={
        "mess_id": college["big"], "category": "Other", "description": "Found a cockroach near the chutney"})
    hits = client.get("/staff/complaints?q=cockroa&days=0", headers=hdr(admin_token)).json()
    assert hits["total"] >= 1 and all("cockroach" in (c["description"] or "") for c in hits["items"])
    assert client.get("/staff/complaints?q=zzzqqq&days=0", headers=hdr(admin_token)).json()["total"] == 0


# ---------- Real SMTP delivery (local test mail server) ----------

def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def smtp_server(monkeypatch):
    from aiosmtpd.controller import Controller
    from aiosmtpd.smtp import AuthResult, LoginPassword

    received = []

    class Handler:
        async def handle_DATA(self, server, session, envelope):
            received.append(envelope)
            return "250 OK"

    def authenticator(server, session, envelope, mechanism, auth_data):
        ok = isinstance(auth_data, LoginPassword) and auth_data.password == b"app-password"
        return AuthResult(success=ok)

    port = _free_port()
    controller = Controller(Handler(), hostname="127.0.0.1", port=port, authenticator=authenticator,
                            auth_require_tls=False)
    controller.start()
    monkeypatch.setattr(config, "SMTP_EMAIL", "alerts@traytrack.test")
    monkeypatch.setattr(config, "SMTP_APP_PASSWORD", "app-password")
    monkeypatch.setattr(config, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "SMTP_PORT", port)
    monkeypatch.setattr(config, "SMTP_STARTTLS", False)
    yield received, port
    controller.stop()


def test_email_is_really_sent_and_recorded(client, college, smtp_server):
    received, _ = smtp_server
    assert notify.send("test_mail", "principal@uni.test", "[TrayTrack] Test subject", "Hello — ₹ and हिंदी work",
                       college["id"], recipient_role="principal") is True
    for _ in range(50):
        if received:
            break
        time.sleep(0.05)
    assert received and received[0].rcpt_tos == ["principal@uni.test"]
    assert b"Test subject" in received[0].content
    rows, _ = db.notifications.list_notifications(college_id=college["id"], status="sent")
    assert any(r["kind"] == "test_mail" for r in rows)


def test_failed_email_is_recorded_not_raised(client, college, smtp_server, monkeypatch):
    monkeypatch.setattr(config, "SMTP_APP_PASSWORD", "wrong-password")
    assert notify.send("test_mail_fail", "principal@uni.test", "Should fail", "x", college["id"]) is False
    rows, _ = db.notifications.list_notifications(college_id=college["id"], status="failed")
    assert any(r["kind"] == "test_mail_fail" and r["error"] for r in rows)


def test_alert_email_reaches_the_authority(client, college, admin_token, smtp_server):
    received, _ = smtp_server
    client.patch(f"/staff/colleges/{college['id']}/contacts", headers=hdr(admin_token),
                 json={"mess_head_email": "messhead@uni.test", "principal_email": "principal@uni.test",
                       "fssai_contact_email": "fssai@gov.test"})
    aid = db.insert_alert(college["small"], "inspection", None, "High", "smtp alert test", "ref")
    notify.alert_raised(aid)
    time.sleep(0.3)
    recipients = sorted(r for env in received for r in env.rcpt_tos)
    assert recipients == ["fssai@gov.test", "principal@uni.test"]   # High: FSSAI + principal copied
    public = next(a for a in client.get(f"/alerts?college_id={college['id']}").json() if a["id"] == aid)
    assert public["authority_notified"] is True
