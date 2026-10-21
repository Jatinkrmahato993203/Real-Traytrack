"""Migrations, seed data, public endpoints, staff sign-in and lockout."""

import db
from conftest import hdr


def test_fresh_database_is_fully_migrated(client):
    assert db.current_version() == 4
    tables = {r["t"] for r in db.fetch_all(
        "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = DATABASE()")}
    for t in ("complaints", "alerts", "staff_users", "activity_log", "meal_ratings", "notifications",
              "checklist_items", "inspection_schedule", "alert_evidence", "compliance_documents", "job_runs"):
        assert t in tables


def test_migrations_are_idempotent(client):
    assert db.run_migrations() == 4


def test_seed_creates_default_checklist_and_kitchen_codes(client):
    items = db.get_checklist(None)
    assert len(items) == 12 and sum(i["critical"] for i in items) == 5
    assert all(h["kitchen_code"] for h in db.list_mess_halls(include_codes=True))


def test_health(client):
    r = client.get("/health").json()
    assert r["database"] is True and r["schema_version"] == 4 and r["email_configured"] is False


def test_public_colleges_hide_contact_emails(client, college, admin_token):
    client.patch(f"/staff/colleges/{college['id']}/contacts", headers=hdr(admin_token),
                 json={"principal_email": "principal@uni.test"})
    public = client.get("/colleges").json()
    assert all(set(c) == {"id", "name", "email_domain"} for c in public)
    assert "principal@uni.test" not in str(public)
    # staff still see them
    staff_view = client.get("/staff/colleges", headers=hdr(admin_token)).json()
    assert any(c.get("principal_email") == "principal@uni.test" for c in staff_view)
    client.patch(f"/staff/colleges/{college['id']}/contacts", headers=hdr(admin_token), json={})


def test_public_mess_hall_lookup_for_qr(client, college):
    r = client.get(f"/mess-halls/{college['small']}").json()
    assert r == {"id": college["small"], "name": "Small Mess", "college_id": college["id"], "college_name": "Test University"}
    assert "kitchen_code" not in client.get(f"/mess-halls?college_id={college['id']}").text


def test_staff_login_and_me(client, admin_token):
    me = client.get("/staff/me", headers=hdr(admin_token)).json()
    assert me["role"] == "admin" and "manage_staff" in me["capabilities"]


def test_lockout_is_stored_in_database(client):
    for _ in range(4):
        r = client.post("/staff/login", json={"email": "nobody@x.test", "password": "wrong-pass"})
        assert r.status_code == 401
    r = client.post("/staff/login", json={"email": "nobody@x.test", "password": "wrong-pass"})
    assert r.status_code == 429
    assert db.security.lockout_remaining("ip:testclient") > 0
    # even the right password is refused while locked
    r = client.post("/staff/login", json={"email": "admin@traytrack.test", "password": "bootstrap-pass-123"})
    assert r.status_code == 429
    db.security.clear_failures("ip:testclient")
    db.security.clear_failures("acct:nobody@x.test")


def test_wrong_password_and_unknown_email_look_the_same(client):
    a = client.post("/staff/login", json={"email": "admin@traytrack.test", "password": "nope-nope"}).json()["detail"]
    b = client.post("/staff/login", json={"email": "ghost@x.test", "password": "nope-nope"}).json()["detail"]
    assert a.split(".")[0] == b.split(".")[0]
    for k in ("ip:testclient", "acct:admin@traytrack.test", "acct:ghost@x.test"):
        db.security.clear_failures(k)


def test_change_own_password(client, admin_token):
    from conftest import make_staff
    token, _ = make_staff(client, admin_token, "pwchange@uni.test", "auditor")
    r = client.post("/staff/me/password", headers=hdr(token),
                    json={"current_password": "wrong", "new_password": "new-pass-999"})
    assert r.status_code == 400
    r = client.post("/staff/me/password", headers=hdr(token),
                    json={"current_password": "staff-pass-123", "new_password": "new-pass-999"})
    assert r.status_code == 200
    assert client.post("/staff/login", json={"email": "pwchange@uni.test", "password": "new-pass-999"}).status_code == 200


def test_request_id_header(client):
    r = client.get("/health")
    assert r.headers.get("X-Request-ID")
