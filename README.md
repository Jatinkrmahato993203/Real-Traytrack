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
cp .env.example .env      # set DB_PASSWORD, ADMIN_TOKEN_SECRET, ...
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
pip install -r requirements-dev.txt
python -m pytest
```
The suite creates and drops its own database (`traytrack_test`, override with
`TEST_DB_NAME`) on the server in `backend/.env`. CI runs it on every push
(`.github/workflows/ci.yml`), plus frontend lint and build.

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
cp backend/.env.example backend/.env # app settings: ADMIN_TOKEN_SECRET, SMTP, ...
docker compose up -d --build
```
Serves everything on `http://localhost:8080`: nginx serves the app and proxies
`/api` to the backend (same origin, no CORS), with SSE buffering disabled.
Put HTTPS in front (Caddy, a cloud load balancer, or certbot).

### Before real use — checklist
- [ ] `ADMIN_TOKEN_SECRET` set to a long random value.
- [ ] Bootstrap admin password changed; real per-person accounts created.
- [ ] `SMTP_EMAIL` / `SMTP_APP_PASSWORD` set; **Admin → Notifications** shows
      all contacts present and emails sending.
- [ ] Google OAuth consent screen published; origin added for the real domain.
- [ ] HTTPS.
- [ ] Daily backups scheduled **and copied off the server**:
      `python scripts/backup.py --keep 30` (see the script for restore steps).
- [ ] Privacy notice reviewed by the institution.
- [ ] Optional: `SENTRY_DSN` + `pip install sentry-sdk` for error tracking.

### Operations notes
- Several backend workers are safe: migrations, background jobs and login
  lockouts coordinate through MySQL locks/tables.
- Logs: console + `LOG_DIR/traytrack.log` (rotating). Every response carries an
  `X-Request-ID`; error messages shown to users quote it.
- `GET /health` for uptime monitoring.
