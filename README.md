# TrayTrack

Food-safety monitoring for college mess halls, aligned to FSSAI Schedule 4
hygiene requirements. Students report problems in under a minute (from a QR
code on the table), confirmed patterns become alerts routed to the right
authority, and every alert moves through a tracked workflow until someone
proves it's fixed. Built to start with one college and scale to many.

**Stack:** React 19 + Vite (frontend) · FastAPI (backend) · MySQL 8 / MariaDB ·
Google Sign-In for students · per-person accounts for staff.

---

## What it does

### Students
- **Sign in with the college Google account.** The college is detected from
  the email domain; the name comes from Google — nothing to type.
- **Privacy notice first.** Students accept a plain-language notice (English
  or Hindi) before their first report.
- **Report a problem**: hall (pre-filled from a table QR code), meal (pre-picked
  by time of day), dish, category, description, photo from the camera.
  Photos are re-encoded server-side (no hidden HTML, no GPS location).
- **Report anonymously**: staff see "Anonymous student" — not even a masked email.
- **Rate meals** (1–5 stars) so the mess hears what works, not only what's wrong.
- **My reports**: a status timeline (received → seen → action taken → closed)
  with the mess team's written reply, the alert each report is part of, and
  a "it's fixed" vote once an alert has been open 2+ days.
- **Own their data**: download everything as JSON, or erase their identity,
  text and photos from all of it.
- English and **Hindi** throughout the student and public screens.

### Alerts (from complaints)
Counting is always **distinct students**, never raw complaints, and one
student can file at most 3 complaints per hall per day.
- **Fast lane** — food poisoning, insects, foreign objects: **3 students in
  48 hours → High alert**.
- **Category pattern** — enough students report the same category within
  30 days → alert one level above the category's base severity. The threshold
  scales with the hall's capacity (5% of diners, between 5 and 20).
- **Whole-hall pattern** — 10% of diners (10–45) report anything → High.
- A pattern doesn't fire twice while open; once resolved it re-arms.

### Inspections
- Every checklist item must be answered **Pass / Fail / N/A** — nothing
  defaults to passing. Failed items take a note and a photo.
- **On-site check-in**: each kitchen has a printed code/QR; scanning it marks
  the inspection "verified on site". Location can be attached.
- Answers are **saved on the device as you go**; with no signal the inspection
  is queued and sent automatically when back online (no duplicates).
- Clean inspections raise no alert; a critical failure is always High.
- Each college can **edit its checklist** (add items, mark critical, hide).
- **To-do list and schedule**: halls are due every 30 days or by a scheduled
  date; overdue and assigned-to-you first.

### Alert workflow
`open → acknowledged → in progress → fixed → resolved`, with owner and due date.
- **Mark fixed** needs proof (a photo or a follow-up inspection) and a note.
- **Verify & close** is done by a principal/admin, not by whoever fixed it —
  or by 3 students who reported it.
- Resolved alerts can be **reopened**.
- **Escalation**: open/acknowledged for 7 days, or in progress past the due date →
  next level (Mess Head → Principal → FSSAI). High alerts send reminders every
  3 days instead of stopping.

### Staff roles
Every person has their own account (scrypt-hashed password), limited to one
college or all colleges; a mess head can be limited to one hall.

| Role | Can |
|---|---|
| Admin | everything: setup, staff, alerts, inspections, exports |
| Principal | work on and verify alerts, reply to students, schedule inspections, compliance, exports |
| Mess Head | work on alerts and reply to students for their hall, compliance records |
| Inspector | inspections and student complaints only |
| Auditor (e.g. FSSAI officer) | read-only access to everything in scope, exports |

Deactivating an account or changing its role takes effect immediately.

### Admin panel
Live activity feed (Server-Sent Events) · alerts with history, evidence and
notification log · complaint search with replies · inspections, history and
schedule · **compliance records** (FSSAI licence, medical certificates, FoSTaC
training, water tests, pest control) with expiry reminders at 30 days, 7 days
and on expiry · setup (halls, capacity, **printable QR sheets**, kitchen codes,
alert contacts, checklist) · staff accounts · notification delivery health ·
**CSV exports** for audits.

### Security
- **Sessions** are server-side and live in **HttpOnly cookies**: page scripts
  can't read them, the database stores only a hash, they expire after inactivity
  (staff 8 h, students 7 days) and at an absolute maximum, and they can be
  revoked — sign out, "sign out everywhere", password change (other devices),
  deactivation and data erasure all end sessions immediately.
- **Two-factor sign-in** (authenticator app, RFC 6238) for staff. Roles in
  `REQUIRE_2FA_ROLES` (default admin, principal) must set it up before they can
  do anything else. 10 single-use recovery codes; codes can't be replayed;
  turning it on signs out other devices; an admin can reset a lost phone.
- **Passwords**: at least 10 characters (`MIN_PASSWORD_LENGTH`), not a common
  password, keyboard run, or the person's own name/email; optional
  breached-password check (`PWNED_PASSWORD_CHECK=1`, k-anonymity — only 5
  hash characters leave the server).
- **CSRF**: cookie-authenticated writes must carry an `X-TrayTrack` header that
  other sites can't send.
- **Rate limits** on sign-in, complaints and ratings (shared across server
  processes) and on anonymous reads; `429` with `Retry-After`.
- **Content-Security-Policy** and other security headers on the app (nginx /
  `vite preview`) and on every API response. No inline scripts or `<style>`
  blocks: Google Sign-In's stylesheet gets a fresh per-request nonce (nginx
  stamps `$request_id` into the page and the header), and Google's script loads
  only on the student sign-in page. The browser tests run under the production
  CSP, so a policy mistake fails CI.
- **Supply chain**: Python dependencies are hash-pinned (`requirements.lock`,
  installed with `--require-hashes`), npm uses `package-lock.json`; CI runs
  `pip-audit` and `npm audit`, and Dependabot proposes updates weekly.
- `E2E_TEST_LOGIN` (sign in as anyone, for browser tests) refuses to start
  unless the database is a `traytrack_e2e*`/`traytrack_test*` one and the site
  is on localhost.

### Pilot tuning
The alert thresholds are starting guesses. Each college can tune them in
**Admin → Setup → Alert rules** (every change logged), and **Admin → Insights**
shows, from the college's own history, how many alerts each threshold value
would have raised — plus response times, reopen rate and notification
delivery. Recommended: run one hall for 4 weeks, then tune.

### Honest notifications
Every email attempt is recorded (sent / no contact / email not set up / failed).
The public dashboard only says an authority was notified when an email was
actually delivered. Admins see missing contacts and failures in one place.
Principals get a **weekly summary** (Monday 9:00 local time).

### Privacy
- The public dashboard shows counts, levels and statuses only — never complaint
  text, identities, or contact emails.
- Staff see masked emails (`ra*****@college.edu`) or nothing for anonymous reports.
- Photos are served only to signed-in staff of the right college, with
  `nosniff` and a sandboxing CSP.
- Student identity is **anonymized automatically after `RETENTION_DAYS`**
  (default 365); photos are deleted.
- Have the privacy notice (`frontend/src/pages/Privacy.jsx`) reviewed by your
  institution before relying on it as a legal document.

---

## Project structure

```
backend/
  main.py              app setup, logging, request ids, startup
  config.py            every environment setting
  routers/             public · student · staff_setup · staff_cases · staff_records
  db/                  core (pool, transactions, UTC) · migrations · one module per area
  alert_engine.py      thresholds, inspections → alerts, workflow, escalation
  fssai_rules.py       checklist defaults, categories, scoring, thresholds
  permissions.py       role → capability table
  deps.py              who is calling, and their scope
  notify.py            email + delivery records
  jobs.py              background jobs (escalation, reminders, compliance, retention, digest)
  broadcaster.py       one shared poller fanning the live feed out to clients
  photos.py            upload validation + re-encoding
  scripts/backup.py    database + uploads snapshot with rotation
  tests/               pytest suite against a real throwaway database
frontend/src/
  lib/                 api client, sessions, i18n (en/hi), time formatting
  components/          shared UI, charts, QR scanner
  pages/               public, student/, staff/
```

---

## Running it locally

### 1. Database
MySQL 8 or MariaDB 10.6+:
```sql
CREATE DATABASE mess_monitor CHARACTER SET utf8mb4;
```
Tables are created and upgraded automatically on startup (versioned
migrations; existing databases upgrade in place).

### 2. Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env      # set DB_PASSWORD, SMTP, ...
uvicorn main:app --reload
```
Runs at `http://localhost:8000` (`/health` shows database, schema version
and email status). On first start it creates an admin account from
`MESS_ADMIN_EMAIL` / `MESS_ADMIN_PASSWORD` — sign in at `/admin` and change
its password under **My account**.

### 3. Frontend
```bash
cd frontend
npm install
cp .env.example .env.local   # VITE_API_BASE, VITE_GOOGLE_CLIENT_ID
npm run dev
```
Runs at `http://localhost:5173`.

### 4. Google Sign-In (one-time, Google Cloud Console)
1. **APIs & Services → Google Auth Platform**: set up the consent screen.
2. **Credentials → Create OAuth Client ID → Web application**.
3. Authorized JavaScript origins: `http://localhost:5173` (and your real domain).
4. Put the Client ID in `backend/.env` (`GOOGLE_CLIENT_ID`) and
   `frontend/.env.local` (`VITE_GOOGLE_CLIENT_ID`).
5. Publish the app (Audience → Publish) so every student, not just test
   users, can sign in.

### 5. Tests
```bash
cd backend
pip install --require-hashes -r requirements-dev.lock
python -m pytest                 # 74 API tests, incl. real SMTP, 2FA, ops alerts, backup→restore
```
The suite creates and drops its own database (`traytrack_test`, override with
`TEST_DB_NAME`) on the server in `backend/.env`. The backup→restore test needs
the `mysqldump`/`mysql` clients on PATH (or `MYSQLDUMP`/`MYSQL`); it's skipped
otherwise.

Frontend unit tests (Vitest) and lint:
```bash
cd frontend
npm test
npm run lint
```

Browser tests (Playwright) start a fresh backend + the production build and
drive them in a real browser — report → alert → fix with proof → verify,
inspections, live feed, cookie/CSRF security, Hindi, and phone layouts
(screenshots saved to `frontend/e2e-screenshots/`):
```bash
cd frontend
npx playwright install webkit    # once, for the iPhone (Safari engine) project
npx playwright test              # desktop + Android on installed Microsoft Edge, iPhone 14 on WebKit
PW_CHANNEL=chromium npx playwright test   # or Playwright's Chromium (npx playwright install chromium)
```
QR scanning uses the browser's `BarcodeDetector` where it exists (Chrome on
Android) and falls back to `jsqr` on iPhone/Safari and Firefox. It needs HTTPS
(or localhost) for camera access.

Load test — a lunch rush against a throwaway database (one API worker):
```bash
cd backend
python scripts/load_test.py --students 400 --concurrency 40
```
On a laptop: 400 students sign in, accept the notice and complain in ~12 s
with 20 dashboard readers polling — 0 errors, complaint p95 ≈ 0.6 s.

Docker end-to-end check (builds the images, then checks headers, the CSP
nonce, sessions through nginx, metrics, and a backup → lose a table → restore
drill):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\docker-smoke.ps1
```

Updating Python dependencies: edit `requirements.txt` / `requirements-dev.txt`,
then regenerate the locks (CI fails if they're stale):
```bash
docker run --rm -v "$PWD/backend:/w" -w /w python:3.12-slim sh -c "pip install -q pip-tools && pip-compile -q --generate-hashes -o requirements.lock requirements.txt && pip-compile -q --generate-hashes -o requirements-dev.lock requirements-dev.txt"
```
CI (`.github/workflows/ci.yml`) runs backend tests + `pip-audit` + a lock
freshness check, frontend `npm audit` + lint + unit tests + build, and the
browser tests (Chromium and WebKit) on every push.

### 6. Things that need people, not code
`docs/review/` has what a reviewer needs:
- `privacy-review.md` — every data flow and the questions for a legal review.
- `hindi-review.csv` — every Hindi string with columns for a native speaker's
  corrections (`node docs/review/export-hindi.mjs` regenerates it).

---

## Setting up a college

In **Admin → Setup**:
1. Add the college and its student email domain (e.g. `nitrkl.ac.in`).
2. Add each mess hall with its number of diners (scales alert thresholds).
3. **QR codes** → print the student sheet for the tables and the kitchen
   sheet for the kitchen wall.
4. **Alert contacts** → Mess Head, Principal and FSSAI contact emails.
5. Optionally adjust the **inspection checklist**.

Then in **Admin → Staff**, create accounts for the principal, mess heads,
inspectors and anyone read-only.

---

## Deploying

### Docker (recommended)
```bash
cp .env.example .env                 # compose settings: DB passwords, public URL, Google client id
cp backend/.env.example backend/.env # app settings: SMTP, retention, ...
docker compose up -d --build
```
Serves everything on `http://localhost:8080`: nginx serves the app and proxies
`/api` to the backend (same origin, no CORS), with SSE buffering disabled.
Put HTTPS in front (Caddy, a cloud load balancer, or certbot).

### Before real use — checklist
- [ ] `E2E_TEST_LOGIN` is **not** set (it's refused on HTTPS anyway).
- [ ] Bootstrap admin password changed; real per-person accounts created.
- [ ] `SMTP_EMAIL` / `SMTP_APP_PASSWORD` set; **Admin → Notifications** shows
      all contacts present and emails sending.
- [ ] Google OAuth consent screen published; origin added for the real domain.
- [ ] HTTPS.
- [ ] Nightly backups on (`BACKUPS_ENABLED=1`, the Docker default) **and the
      backups volume copied off the server**. Do one restore drill:
      `python scripts/restore.py --force` into a scratch database.
- [ ] Every admin and principal has two-factor sign-in on (enforced).
- [ ] Uptime monitor (UptimeRobot, Better Stack, …) on `https://<site>/api/health`
      — it returns 503 if the database is down or background jobs stall.
- [ ] `OPS_ALERT_EMAIL` and/or `OPS_WEBHOOK_URL` set, so failed backups, failed
      jobs and bursts of server errors reach a person.
- [ ] Privacy notice reviewed by the institution.
- [ ] Optional: `SENTRY_DSN` + `pip install sentry-sdk` for error tracking.

### Operations notes
- Several backend workers are safe: migrations, background jobs and login
  lockouts coordinate through MySQL locks/tables.
- Logs: console + `LOG_DIR/traytrack.log` (rotating). Every response carries an
  `X-Request-ID`; error messages shown to users quote it.
- `GET /health` for uptime monitoring: 200 when healthy; 503 with
  `stale_jobs` when the database is down or the escalation/reminder jobs
  haven't run on time.
- `GET /metrics` (Prometheus text) when `METRICS_TOKEN` is set; scrape with
  `Authorization: Bearer <token>`. Request counts and latency, database up,
  open alerts by level, undelivered notifications, job ages.
- Ops alerts go to `OPS_ALERT_EMAIL` (needs SMTP) and/or `OPS_WEBHOOK_URL`
  (Slack/Discord/Teams-style JSON `{"text": ...}`), at most one per kind per
  hour, and are recorded under Admin → Notifications either way.
- Backups: a verified dump (complete, essential tables present) plus a zip of
  photos, nightly at `BACKUP_HOUR` (local time), keeping `BACKUP_KEEP`. A failed backup
  raises an ops alert. `scripts/restore.py` refuses to overwrite data without
  `--force`; migrations bring an older backup up to date on next start.
