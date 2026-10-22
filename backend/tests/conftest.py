"""
Test setup: every test session runs against a brand-new MySQL/MariaDB
database (default `traytrack_test`, dropped and recreated), using the real
app — migrations, seed data, routers — through FastAPI's TestClient.

Needs a reachable MySQL/MariaDB server. Connection settings come from
backend/.env (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD); override the test
database name with TEST_DB_NAME. Background jobs are disabled; tests call
them directly.
"""

import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

TEST_DB = os.environ.get("TEST_DB_NAME", "traytrack_test")
os.environ["DB_NAME"] = TEST_DB
os.environ["JOBS_ENABLED"] = "0"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="traytrack-uploads-")
os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="traytrack-logs-")
os.environ["SMTP_EMAIL"] = ""          # never send real email from tests
os.environ["SMTP_APP_PASSWORD"] = ""
os.environ["MESS_ADMIN_EMAIL"] = "admin@traytrack.test"
os.environ["MESS_ADMIN_PASSWORD"] = "bootstrap-pass-123"
os.environ["RATE_LIMIT_SCALE"] = "100"   # tests make many requests from one "IP"
os.environ["REQUIRE_2FA_ROLES"] = ""      # test_5 switches it on

import config  # noqa: E402  (reads the env above)
import pymysql  # noqa: E402


def _recreate_database():
    conn = pymysql.connect(host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER,
                           password=config.DB_PASSWORD, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        cur.execute(f"CREATE DATABASE `{TEST_DB}` CHARACTER SET utf8mb4")
    conn.close()


@pytest.fixture(scope="session")
def client():
    _recreate_database()
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:   # runs startup: migrations + seed
        yield c


@pytest.fixture(autouse=True)
def _no_leftover_cookies(request):
    """Each test starts signed out; tests authenticate explicitly with a
    Bearer token, so a cookie from an earlier login can't leak in."""
    if "client" in request.fixturenames:
        request.getfixturevalue("client").cookies.clear()
    yield


def login(client, email, password="staff-pass-123"):
    """Signs in through the real endpoint and returns the session token
    from its HttpOnly cookie (then forgets the cookie)."""
    r = client.post("/staff/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.cookies.get("tt_staff")
    assert token and "token" not in r.json()
    client.cookies.clear()
    return token


@pytest.fixture(scope="session")
def admin_token(client):
    return login(client, "admin@traytrack.test", "bootstrap-pass-123")


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def college(client, admin_token):
    """A college with two halls (one with a small capacity) and contacts."""
    r = client.post("/staff/colleges", headers=hdr(admin_token), json={
        "name": "Test University", "email_domain": "uni.test", "mess_head_email": None,
        "principal_email": None, "fssai_contact_email": None})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    big = client.post("/staff/mess-halls", headers=hdr(admin_token), json={"college_id": cid, "name": "Big Mess"}).json()["id"]
    small = client.post("/staff/mess-halls", headers=hdr(admin_token),
                        json={"college_id": cid, "name": "Small Mess", "capacity": 100}).json()["id"]
    other = client.post("/staff/colleges", headers=hdr(admin_token),
                        json={"name": "Other College", "email_domain": "other.test"}).json()["id"]
    other_mess = client.post("/staff/mess-halls", headers=hdr(admin_token),
                             json={"college_id": other, "name": "Other Mess"}).json()["id"]
    return {"id": cid, "big": big, "small": small, "other_id": other, "other_mess": other_mess}


def student_token(email, name="Test Student"):
    """A real server-side student session (what /auth/google creates after
    Google verifies the account)."""
    import auth
    return auth.start_student_session(email, name)


def consented_student(client, email, name="Test Student"):
    import config as cfg
    token = student_token(email, name)
    r = client.post("/me/consent", headers=hdr(token), json={"version": cfg.PRIVACY_NOTICE_VERSION})
    assert r.status_code == 200, r.text
    return token


def make_staff(client, admin_token, email, role, college_id=None, mess_id=None, name=None):
    r = client.post("/staff/accounts", headers=hdr(admin_token), json={
        "name": name or email.split("@")[0].title(), "email": email, "role": role,
        "college_id": college_id, "mess_id": mess_id, "password": "staff-pass-123"})
    assert r.status_code == 200, r.text
    return login(client, email), r.json()


def jpeg_bytes(with_gps=False):
    from PIL import Image
    img = Image.new("RGB", (64, 48), (200, 50, 50))
    out = io.BytesIO()
    if with_gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (12.0, 58.0, 0.0), 3: "E", 4: (77.0, 35.0, 0.0)}  # GPS IFD
        exif[0x010F] = "PhoneMaker"
        img.save(out, "JPEG", exif=exif)
    else:
        img.save(out, "JPEG")
    return out.getvalue()
