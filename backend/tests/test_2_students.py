"""Student flows: consent, complaints, thresholds, anonymity, follow-up,
ratings, data export/erasure and retention."""

from datetime import timedelta

import config
import db
from conftest import consented_student, hdr, jpeg_bytes, make_staff, student_token


def complain(client, token, mess_id, category="Too oily", **extra):
    data = {"mess_id": mess_id, "category": category, "description": extra.pop("description", "test")}
    data.update({k: str(v).lower() if isinstance(v, bool) else v for k, v in extra.items() if k != "files"})
    return client.post("/complaints", headers=hdr(token), data=data, files=extra.get("files"))


def test_sign_in_detects_college_and_requires_consent(client, college):
    token = student_token("asha@uni.test", "Asha")
    me = client.get("/me", headers=hdr(token)).json()
    assert me["college"]["name"] == "Test University" and me["consent_needed"] is True
    assert complain(client, token, college["big"]).status_code == 428
    client.post("/me/consent", headers=hdr(token), json={"version": config.PRIVACY_NOTICE_VERSION})
    assert client.get("/me", headers=hdr(token)).json()["consent_needed"] is False


def test_unknown_college_and_wrong_hall(client, college):
    outsider = consented_student(client, "x@nowhere.test")
    assert complain(client, outsider, college["big"]).status_code == 403
    s = consented_student(client, "hall@uni.test")
    assert complain(client, s, college["other_mess"]).status_code == 403


def test_complaint_uses_name_from_token_and_meal_fields(client, college, admin_token):
    s = consented_student(client, "ravi@uni.test", "Ravi Kumar")
    r = complain(client, s, college["big"], category="Undercooked food", meal="lunch", dish="Rajma")
    assert r.status_code == 200, r.text
    row = db.get_complaint(r.json()["complaint_id"])
    assert row["student_name"] == "Ravi Kumar" and row["meal"] == "lunch" and row["dish"] == "Rajma"
    assert complain(client, s, college["big"], meal="brunch").status_code == 400


def test_rate_limit(client, college):
    s = consented_student(client, "spam@uni.test")
    codes = [complain(client, s, college["big"], category="Too spicy").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_fast_lane_food_poisoning(client, college):
    hall = college["big"]
    results = [complain(client, consented_student(client, f"fp{i}@uni.test"), hall,
                        category="Food poisoning / illness reported").json() for i in range(3)]
    assert [r["alert_created"] for r in results] == [False, False, True]
    assert results[2]["level"] == "High" and "outbreak" in results[2]["reason"]
    # a 4th report doesn't duplicate the open alert
    r = complain(client, consented_student(client, "fp9@uni.test"), hall, category="Food poisoning / illness reported").json()
    assert r["alert_created"] is False


def test_threshold_scales_with_capacity(client, college):
    """Small Mess has capacity 100 -> category threshold max(5, 5%) = 5."""
    out = None
    for i in range(5):
        out = complain(client, consented_student(client, f"oily{i}@uni.test"), college["small"], category="Too oily").json()
    assert out["category_threshold"] == 5 and out["alert_created"] and out["level"] == "Medium"


def test_anonymous_complaint_hides_identity_from_staff(client, college, admin_token):
    s = consented_student(client, "shy@uni.test")
    cid = complain(client, s, college["big"], category="Staff behaviour", anonymous=True,
                   description="anon test").json()["complaint_id"]
    items = client.get(f"/staff/complaints?q=anon%20test", headers=hdr(admin_token)).json()["items"]
    mine = next(c for c in items if c["id"] == cid)
    assert mine["reporter"] == "Anonymous student" and "sh*" not in str(mine)
    feed = client.get("/staff/activity?event_type=complaint_submitted", headers=hdr(admin_token)).json()
    assert "shy@" not in str(feed) and "sh**" not in str(feed)


def test_staff_reply_reaches_student(client, college, admin_token):
    s = consented_student(client, "follow@uni.test")
    cid = complain(client, s, college["big"], category="Quantity / portion size").json()["complaint_id"]
    r = client.post(f"/staff/complaints/{cid}/respond", headers=hdr(admin_token), json={"status": "action_taken"})
    assert r.status_code == 400  # must say what was done
    r = client.post(f"/staff/complaints/{cid}/respond", headers=hdr(admin_token),
                    json={"status": "action_taken", "response": "Portion size increased from Monday."})
    assert r.status_code == 200
    mine = next(c for c in client.get("/my-complaints", headers=hdr(s)).json() if c["id"] == cid)
    assert mine["status"] == "action_taken" and "Monday" in mine["staff_response"]
    # the student notification attempt is recorded, with a masked address
    rows, _ = db.notifications.list_notifications(status="skipped_no_smtp")
    assert any(n["kind"] == "complaint_update" and n["recipient_email"].startswith("fo*") for n in rows)


def test_photo_upload_strips_gps_and_rejects_html(client, college):
    from PIL import Image
    s = consented_student(client, "photo@uni.test")
    r = complain(client, s, college["big"], category="Insect in food",
                 files={"photo": ("bug.jpg", jpeg_bytes(with_gps=True), "image/jpeg")})
    assert r.status_code == 200, r.text
    path = db.get_complaint(r.json()["complaint_id"])["photo_path"]
    with Image.open(path) as img:
        assert img.format == "JPEG" and not img.getexif()
    r = complain(client, s, college["big"], category="Insect in food",
                 files={"photo": ("x.html", b"<script>alert(1)</script>", "image/png")})
    assert r.status_code == 400


def test_ratings(client, college):
    s = consented_student(client, "rater@uni.test")
    assert client.post("/ratings", headers=hdr(s), json={"mess_id": college["big"], "meal": "dinner", "stars": 2}).status_code == 200
    assert client.post("/ratings", headers=hdr(s), json={"mess_id": college["big"], "meal": "dinner", "stars": 4}).status_code == 200
    assert client.post("/ratings", headers=hdr(s), json={"mess_id": college["big"], "meal": "dinner", "stars": 9}).status_code == 422
    mine = client.get("/my-ratings", headers=hdr(s)).json()
    assert len(mine) == 1 and mine[0]["stars"] == 4  # re-rating overwrites
    status = client.get(f"/dashboard-status?college_id={college['id']}").json()
    big = next(h for h in status if h["mess"]["id"] == college["big"])
    assert big["rating"]["count"] >= 1


def test_export_and_erase_my_data(client, college):
    s = consented_student(client, "leaver@uni.test", "Leaver")
    complain(client, s, college["big"], category="Other", description="my private words",
             files={"photo": ("p.jpg", jpeg_bytes(), "image/jpeg")})
    export = client.get("/me/data", headers=hdr(s))
    assert export.status_code == 200 and "attachment" in export.headers["content-disposition"]
    assert export.json()["complaints"][0]["description"] == "my private words"
    photo = db.fetch_one("SELECT photo_path FROM complaints WHERE student_email = 'leaver@uni.test'")["photo_path"]

    assert client.delete("/me/data", headers=hdr(s)).json()["photos_deleted"] == 1
    assert db.fetch_one("SELECT COUNT(*) AS n FROM complaints WHERE student_email = 'leaver@uni.test'")["n"] == 0
    erased = db.fetch_one("SELECT * FROM complaints WHERE description IS NULL AND category = 'Other' "
                          "AND student_email LIKE 'anon-%%'")
    assert erased and erased["student_name"] is None
    import os
    assert not os.path.exists(photo)
    assert client.get("/me", headers=hdr(s)).json()["consent_needed"] is True


def test_retention_anonymizes_old_complaints(client, college):
    s = consented_student(client, "old@uni.test")
    cid = complain(client, s, college["big"], category="Other", description="ancient").json()["complaint_id"]
    db.execute("UPDATE complaints SET created_at = %s WHERE id = %s",
               (db.to_db(db.utcnow() - timedelta(days=config.RETENTION_DAYS + 1)), cid))
    db.apply_retention(config.RETENTION_DAYS)
    row = db.get_complaint(cid)
    assert row["student_email"].startswith("anon-") and row["description"] is None and row["anonymized_at"]


def test_public_endpoints_never_return_complaint_text(client, college):
    for path in (f"/analytics?college_id={college['id']}", f"/trends?college_id={college['id']}",
                 f"/alerts?college_id={college['id']}", f"/dashboard-status?college_id={college['id']}"):
        body = client.get(path).text
        assert "Portion size increased" not in body and "@uni.test" not in body
