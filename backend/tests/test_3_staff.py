"""Roles, scope, inspections, alert workflow, escalation, compliance,
notifications, exports."""

from datetime import date, timedelta

import alert_engine
import db
import jobs
from conftest import consented_student, hdr, jpeg_bytes, login, make_staff


def answers(checklist, fail=(), na=()):
    return {i["item_key"]: {"result": "fail" if i["item_key"] in fail else "na" if i["item_key"] in na else "pass",
                            "note": "needs fixing" if i["item_key"] in fail else ""} for i in checklist}


def test_roles_and_scope(client, college, admin_token):
    insp, _ = make_staff(client, admin_token, "inspector@uni.test", "inspector", college["id"])
    head, _ = make_staff(client, admin_token, "head@uni.test", "mess_head", college["id"], college["big"])
    auditor, _ = make_staff(client, admin_token, "auditor@uni.test", "auditor", college["id"])
    # inspectors: no alerts, no setup
    assert client.get("/staff/alerts", headers=hdr(insp)).status_code == 403
    assert client.post("/staff/mess-halls", headers=hdr(insp), json={"college_id": college["id"], "name": "x"}).status_code == 403
    # mess head: only their hall
    assert client.get(f"/staff/complaints?mess_id={college['small']}", headers=hdr(head)).status_code == 403
    items = client.get("/staff/complaints?days=0&limit=200", headers=hdr(head)).json()["items"]
    assert items and {c["mess_id"] for c in items} == {college["big"]}
    # other college is off limits for everyone college-scoped
    assert client.get(f"/staff/complaints?college_id={college['other_id']}", headers=hdr(auditor)).status_code == 403
    # auditor: read-only
    assert client.get("/staff/alerts", headers=hdr(auditor)).status_code == 200
    assert client.post(f"/staff/complaints/{items[0]['id']}/respond", headers=hdr(auditor),
                       json={"status": "acknowledged"}).status_code == 403
    # mess heads need a college
    r = client.post("/staff/accounts", headers=hdr(admin_token), json={
        "name": "No College", "email": "nocol@uni.test", "role": "mess_head", "password": "staff-pass-123"})
    assert r.status_code == 400


def test_inspection_requires_every_answer(client, college, admin_token):
    insp = login(client, "inspector@uni.test")
    checklist = client.get(f"/staff/checklist?mess_id={college['big']}", headers=hdr(insp)).json()
    partial = answers(checklist)
    partial.pop(checklist[0]["item_key"])
    r = client.post("/staff/inspections", headers=hdr(insp), json={"mess_id": college["big"], "responses": partial})
    assert r.status_code == 400 and checklist[0]["item_key"] in r.json()["detail"]["missing"]


def test_clean_inspection_raises_no_alert_and_na_is_ignored(client, college):
    insp = login(client, "inspector@uni.test")
    checklist = client.get(f"/staff/checklist?mess_id={college['big']}", headers=hdr(insp)).json()
    r = client.post("/staff/inspections", headers=hdr(insp), json={
        "mess_id": college["big"], "responses": answers(checklist, na=("license_displayed",))}).json()
    assert r["alert_id"] is None and r["score"] == 100.0


def test_kitchen_code_verifies_visit_and_retries_are_idempotent(client, college, admin_token):
    insp = login(client, "inspector@uni.test")
    code = next(h for h in client.get(f"/staff/mess-halls?college_id={college['id']}", headers=hdr(insp)).json()
                if h["id"] == college["small"])["kitchen_code"]
    checklist = client.get(f"/staff/checklist?mess_id={college['small']}", headers=hdr(insp)).json()
    body = {"mess_id": college["small"], "responses": answers(checklist, fail=("pest_control",)),
            "kitchen_code": code.lower(), "client_ref": "device-1-abc"}
    first = client.post("/staff/inspections", headers=hdr(insp), json=body).json()
    assert first["verified_onsite"] is True and first["level"] == "High"
    again = client.post("/staff/inspections", headers=hdr(insp), json=body).json()
    assert again == {"inspection_id": first["inspection_id"], "duplicate": True}
    # photo evidence for the failed item
    r = client.post(f"/staff/inspections/{first['inspection_id']}/photos", headers=hdr(insp),
                    data={"item_key": "pest_control"}, files={"photo": ("p.jpg", jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200
    detail = client.get(f"/staff/inspections/{first['inspection_id']}", headers=hdr(insp)).json()
    assert detail["responses"]["pest_control"]["note"] == "needs fixing" and detail["photos"][0]["photo_url"]
    assert client.get(detail["photos"][0]["photo_url"], headers=hdr(insp)).headers["content-type"] == "image/jpeg"
    wrong = client.post("/staff/inspections", headers=hdr(insp), json={**body, "client_ref": "x2", "kitchen_code": "ZZZZZZ"}).json()
    assert wrong["verified_onsite"] is False


def test_photos_are_scoped(client, college, admin_token):
    other_admin, _ = make_staff(client, admin_token, "otheradmin@other.test", "admin", college["other_id"])
    photo_url = db.fetch_one("SELECT photo_path FROM inspection_photos ORDER BY id DESC LIMIT 1")["photo_path"]
    url = db.complaint_photo_url(photo_url)
    assert client.get(url, headers=hdr(other_admin)).status_code == 403
    assert client.get(url).status_code == 401
    assert client.get("/staff/photos/..%2Fsecret.jpg", headers=hdr(admin_token)).status_code == 404


def test_checklist_is_editable_per_college(client, college, admin_token):
    r = client.post("/staff/checklist-items", headers=hdr(admin_token),
                    json={"college_id": college["id"], "text": "Allergen board displayed", "critical": False})
    assert r.status_code == 200
    items = client.get(f"/staff/checklist?college_id={college['id']}", headers=hdr(admin_token)).json()
    assert any(i["text"] == "Allergen board displayed" for i in items) and items[0]["is_default"] is False
    # other colleges keep the default
    assert len(db.get_checklist(college["other_id"])) == 12
    item = next(i for i in items if i["item_key"] == "license_displayed")
    client.patch(f"/staff/checklist-items/{item['id']}", headers=hdr(admin_token),
                 json={"college_id": college["id"], "active": False})
    keys = [i["item_key"] for i in client.get(f"/staff/checklist?college_id={college['id']}", headers=hdr(admin_token)).json()]
    assert "license_displayed" not in keys


def test_alert_workflow_needs_evidence_and_verification(client, college, admin_token):
    head = login(client, "head@uni.test")
    principal, principal_row = make_staff(client, admin_token, "principal@uni.test", "principal", college["id"])
    alert = next(a for a in client.get("/staff/alerts?status=active", headers=hdr(head)).json()["items"]
                 if a["mess_id"] == college["big"])
    aid = alert["id"]
    act = lambda tok, action, note="": client.post(f"/staff/alerts/{aid}/action", headers=hdr(tok),
                                                   json={"action": action, "note": note})
    assert act(head, "acknowledge").status_code == 200
    assert client.post(f"/staff/alerts/{aid}/assign", headers=hdr(principal),
                       json={"owner_staff_id": principal_row["id"], "due_date": str(date.today() + timedelta(days=3))}).status_code == 200
    assert act(head, "start").status_code == 200
    r = act(head, "mark_fixed", "Cleaned")
    assert r.status_code == 400 and "proof" in r.json()["detail"]
    r = client.post(f"/staff/alerts/{aid}/evidence", headers=hdr(head), data={"note": "after cleaning"},
                    files={"photo": ("after.jpg", jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200
    assert act(head, "mark_fixed", "").status_code == 400  # a note is required
    assert act(head, "mark_fixed", "Deep-cleaned kitchen, new supplier").status_code == 200
    assert act(head, "verify", "ok").status_code == 403    # mess heads can't verify their own fix
    assert act(principal, "verify", "Checked in person").status_code == 200
    detail = client.get(f"/staff/alerts/{aid}", headers=hdr(principal)).json()
    assert detail["alert"]["status"] == "resolved" and detail["alert"]["resolved"] == 1
    events = [h["event"] for h in detail["history"]]
    assert events[-1] == "resolved" and "fixed" in events and detail["history"][-1]["actor_name"] == "Principal"
    assert detail["can_reopen"] is True and detail["evidence"][0]["photo_url"]
    # reopen
    assert client.post(f"/staff/alerts/{aid}/reopen", headers=hdr(principal), json={"note": "Came back"}).status_code == 200
    assert db.get_alert(aid)["status"] == "open" and db.get_alert(aid)["reopened_count"] == 1


def test_escalation_reminders_and_honest_notifications(client, college):
    alerts = db.get_alerts(college_id=college["id"], resolved=False)
    low = db.insert_alert(college["small"], "inspection", None, "Low", "test low", "ref")
    db.execute("UPDATE alerts SET last_escalated_at = %s WHERE id = %s",
               (db.to_db(db.utcnow() - timedelta(days=8)), low))
    assert alert_engine.escalate_stale_alerts() >= 1
    assert db.get_alert(low)["level"] == "Medium"
    # contacts are missing, so nothing was delivered — and the public page says so
    public = client.get(f"/alerts?college_id={college['id']}").json()
    assert next(a for a in public if a["id"] == low)["authority_notified"] is False
    rows, _ = db.notifications.list_notifications(alert_id=low)
    assert rows and all(r["status"] == "skipped_no_contact" for r in rows)
    # High alerts get reminders instead of escalating further
    high = db.insert_alert(college["small"], "inspection", None, "High", "test high", "ref")
    db.execute("UPDATE alerts SET last_escalated_at = %s, created_at = %s WHERE id = %s",
               (db.to_db(db.utcnow() - timedelta(days=4)), db.to_db(db.utcnow() - timedelta(days=4)), high))
    assert alert_engine.remind_high_alerts() >= 1
    assert db.get_alert(high)["last_reminder_at"] is not None
    assert alert_engine.remind_high_alerts() == 0  # not again until 3 more days


def test_jobs_run_once_and_record(client):
    jobs.run_due_jobs()
    names = {r["job_name"] for r in db.security.all_job_runs()}
    assert {"escalation", "high_reminders", "compliance", "retention"} <= names
    with db.security.job_lock("escalation") as got:
        assert got
        with db.security.job_lock("escalation") as again:  # a second worker can't take it
            assert not again


def test_compliance_records_and_reminders(client, college, admin_token):
    r = client.post("/staff/compliance", headers=hdr(admin_token), data={
        "college_id": college["id"], "mess_id": college["big"], "doc_type": "medical_certificate",
        "title": "Cook medical fitness", "person_name": "Ramesh", "expires_on": str(date.today() + timedelta(days=5))})
    assert r.status_code == 200, r.text
    expiring = client.get(f"/staff/compliance?college_id={college['id']}&expiring_within_days=30", headers=hdr(admin_token)).json()
    assert any(d["title"] == "Cook medical fitness" and d["days_left"] == 5 for d in expiring)
    assert jobs.compliance_reminders() >= 1
    doc = db.compliance.get_document(r.json()["id"])
    assert doc["last_reminder_window"] == 7
    assert jobs.compliance_reminders() == 0  # same window, not repeated
    bad = client.post("/staff/compliance", headers=hdr(admin_token), data={
        "college_id": college["id"], "doc_type": "fssai_license", "title": "x",
        "issued_on": "2026-05-01", "expires_on": "2026-01-01"})
    assert bad.status_code == 400


def test_schedule_and_overview(client, college, admin_token):
    insp_row = db.get_staff_login("inspector@uni.test")
    r = client.post("/staff/schedule", headers=hdr(admin_token), json={
        "mess_id": college["big"], "due_date": str(date.today() - timedelta(days=1)), "assigned_staff_id": insp_row["id"]})
    assert r.status_code == 200
    insp = login(client, "inspector@uni.test")
    overview = client.get("/staff/inspection-overview", headers=hdr(insp)).json()
    first = overview["halls"][0]
    assert first["overdue"] and first["assigned_to_me"] and first["mess_id"] == college["big"]
    head = login(client, "head@uni.test")
    assert client.post("/staff/schedule", headers=hdr(head), json={
        "mess_id": college["big"], "due_date": str(date.today())}).status_code == 403


def test_deactivation_is_immediate(client, college, admin_token):
    tok, row = make_staff(client, admin_token, "temp@uni.test", "inspector", college["id"])
    assert client.get("/staff/me", headers=hdr(tok)).status_code == 200
    client.patch(f"/staff/accounts/{row['id']}", headers=hdr(admin_token), json={"active": False})
    assert client.get("/staff/me", headers=hdr(tok)).status_code == 401


def test_last_global_admin_is_protected(client, admin_token):
    me = client.get("/staff/me", headers=hdr(admin_token)).json()
    assert client.patch(f"/staff/accounts/{me['id']}", headers=hdr(admin_token), json={"active": False}).status_code == 400


def test_csv_exports(client, college, admin_token):
    r = client.get(f"/staff/export/complaints.csv?college_id={college['id']}", headers=hdr(admin_token))
    assert r.status_code == 200 and r.text.startswith("﻿id,created_at_utc")
    assert "Anonymous student" in r.text and "shy@" not in r.text
    for path in ("alerts", "inspections"):
        assert client.get(f"/staff/export/{path}.csv", headers=hdr(admin_token)).status_code == 200
    insp = login(client, "inspector@uni.test")
    assert client.get("/staff/export/alerts.csv", headers=hdr(insp)).status_code == 403


def test_complaint_search_and_paging(client, college, admin_token):
    page1 = client.get(f"/staff/complaints?college_id={college['id']}&days=0&limit=5", headers=hdr(admin_token)).json()
    page2 = client.get(f"/staff/complaints?college_id={college['id']}&days=0&limit=5&offset=5", headers=hdr(admin_token)).json()
    assert page1["total"] > 5 and len(page1["items"]) == 5
    assert not {c["id"] for c in page1["items"]} & {c["id"] for c in page2["items"]}
    found = client.get("/staff/complaints?q=Rajma&days=0", headers=hdr(admin_token)).json()
    assert found["total"] == 1 and found["items"][0]["dish"] == "Rajma"


def test_inspector_activity_feed_is_limited(client, admin_token):
    insp = login(client, "inspector@uni.test")
    types = {r["event_type"] for r in client.get("/staff/activity?limit=500", headers=hdr(insp)).json()}
    assert types and types <= {"complaint_submitted", "inspection_submitted", "inspection_scheduled"}


def test_broadcaster_filters():
    from broadcaster import Subscriber
    s = Subscriber(college_id=1, mess_id=2, prefixes=("complaint_submitted",))
    assert s.wants({"college_id": 1, "mess_id": 2, "event_type": "complaint_submitted"})
    assert not s.wants({"college_id": 9, "mess_id": 2, "event_type": "complaint_submitted"})
    assert not s.wants({"college_id": 1, "mess_id": 3, "event_type": "complaint_submitted"})
    assert not s.wants({"college_id": 1, "mess_id": 2, "event_type": "alert_created"})


def test_never_inspected_hall_is_due_now(client, college, admin_token):
    halls = client.get("/staff/inspection-overview", headers=hdr(admin_token)).json()["halls"]
    other = next(h for h in halls if h["mess_id"] == college["other_mess"])
    assert other["never_inspected"] and other["overdue"] and other["next_due"] == str(date.today())


def test_weekly_digest_runs_and_is_recorded(client, college):
    assert jobs.weekly_digest() >= 2
    rows, _ = db.notifications.list_notifications(college_id=college["id"])
    assert any(n["kind"] == "weekly_digest" for n in rows)
