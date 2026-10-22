"""
main.py — TrayTrack API (FastAPI): app setup only. The endpoints live in
routers/, the storage layer in db/, and the business rules in
alert_engine.py / fssai_rules.py / permissions.py.

  routers/public.py         reference data, public dashboard, trends, health
  routers/student.py        sign-in, complaints, ratings, my reports, my data
  routers/staff_setup.py    staff sign-in & accounts, colleges, halls, checklist
  routers/staff_cases.py    complaints & alerts workflow, CSV exports
  routers/staff_records.py  inspections, schedule, compliance, photos, live feed
"""

import logging
import sys
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import auth
import config
import db
import deps
import jobs
from broadcaster import broadcaster
from routers import public, staff_cases, staff_records, staff_setup, student

# Windows consoles default to a legacy code page; log text has — and ₹.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

config.LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(config.LOG_DIR / "traytrack.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
    ],
)
logger = logging.getLogger("traytrack")

if config.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=config.SENTRY_DSN, traces_sample_rate=0.0, send_default_pii=False)
        logger.info("Error tracking enabled (Sentry)")
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk isn't installed — `pip install sentry-sdk`")


@asynccontextmanager
async def lifespan(app: FastAPI):
    version = db.run_migrations()
    db.seed(auth.ADMIN_EMAIL, auth.hash_password(auth.ADMIN_PASSWORD))
    logger.info("Database ready (schema version %s)", version)
    if auth.ADMIN_PASSWORD == "changeme123":
        logger.warning("MESS_ADMIN_PASSWORD is the default. If the bootstrap admin still uses it, change it now.")
    if config.E2E_TEST_LOGIN:
        logger.warning("E2E_TEST_LOGIN is ON — anyone can sign in as any student. Test environments only!")
    broadcaster.start()
    jobs.start()
    yield


app = FastAPI(title="TrayTrack API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After"],
)


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-traytrack"

# Cheap per-process limit for anonymous reads (the dashboard, reference
# data). Writes and sign-ins use the shared database limiter in deps.py.
PUBLIC_READS_PER_MINUTE = 300
_public_hits = defaultdict(deque)


def _public_read_allowed(ip):
    now = time.monotonic()
    hits = _public_hits[ip]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= PUBLIC_READS_PER_MINUTE * config.RATE_LIMIT_SCALE:
        return False
    hits.append(now)
    if len(_public_hits) > 50_000:  # don't grow forever
        _public_hits.clear()
    return True


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    # The API only ever returns JSON/CSV/images — nothing may execute.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-site",
}


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Tags every request with an id (returned as X-Request-ID and written to
    the log), logs slow requests, and turns unexpected errors into a clean
    500 that quotes the id — so a user's screenshot is enough to find the
    stack trace."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    path = request.url.path
    # CSRF: a browser request authenticated by cookie must carry our custom
    # header. Other sites can't add it (CORS blocks it), so a forged form
    # post from elsewhere is refused even if SameSite were bypassed.
    has_cookie = auth.STAFF_COOKIE in request.cookies or auth.STUDENT_COOKIE in request.cookies
    has_bearer = request.headers.get("authorization", "").startswith("Bearer ")
    if request.method in UNSAFE_METHODS and has_cookie and not has_bearer and request.headers.get(CSRF_HEADER) != "1":
        response = JSONResponse(status_code=403, content={"detail": "Missing X-TrayTrack header."})
        response.headers["X-Request-ID"] = request_id
        return response
    anonymous_read = request.method == "GET" and not path.startswith("/staff") and not has_cookie and not has_bearer
    if anonymous_read and not _public_read_allowed(deps.client_ip(request)):
        return JSONResponse(status_code=429, content={"detail": "Too many requests — please slow down."},
                            headers={"Retry-After": "60", "X-Request-ID": request_id})
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error [%s] %s %s", request_id, request.method, request.url.path)
        response = JSONResponse(status_code=500, content={
            "detail": f"Something went wrong on our side. Reference: {request_id}", "request_id": request_id})
    elapsed = time.perf_counter() - started
    if elapsed > 2 and not request.url.path.endswith("/stream"):
        logger.warning("Slow request [%s] %s %s took %.1fs", request_id, request.method, request.url.path, elapsed)
    response.headers["X-Request-ID"] = request_id
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if config.COOKIE_SECURE_FLAG:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.include_router(public.router)
app.include_router(student.router)
app.include_router(staff_setup.router)
app.include_router(staff_cases.router)
app.include_router(staff_records.router)


@app.get("/admin/complaint-photos/{filename}", include_in_schema=False)
def legacy_photo_path(filename: str, request: Request):
    """Older activity-log entries link here."""
    return staff_records.get_photo(filename, deps.current_staff(request))
