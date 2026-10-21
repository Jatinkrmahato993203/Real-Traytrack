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
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import auth
import config
import db
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
    if auth.TOKEN_SECRET == "dev-secret-change-me":
        logger.warning("ADMIN_TOKEN_SECRET is the default — set a long random value before real use.")
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
    expose_headers=["X-Request-ID", "Content-Disposition"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Tags every request with an id (returned as X-Request-ID and written to
    the log), logs slow requests, and turns unexpected errors into a clean
    500 that quotes the id — so a user's screenshot is enough to find the
    stack trace."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
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
    return response


app.include_router(public.router)
app.include_router(student.router)
app.include_router(staff_setup.router)
app.include_router(staff_cases.router)
app.include_router(staff_records.router)


@app.get("/admin/complaint-photos/{filename}", include_in_schema=False)
def legacy_photo_path(filename: str, authorization: str = Header(None)):
    """Older activity-log entries link here."""
    return staff_records.get_photo(filename, authorization)
