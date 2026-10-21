# TrayTrack

A mess/canteen food safety monitoring system, aligned to FSSAI-style hygiene
requirements, with a 3-level alert system, an authority escalation chain, and
a public dashboard. Built to start with one college and scale to many.

**Stack:** React (frontend) + FastAPI (backend) + MySQL (database) +
Google Sign-In (student identity verification).

## Features

- **Multi-college ready** — each college has an authorized email domain
  (e.g. `nitrkl.ac.in`). Any student whose email matches that domain is
  automatically recognized — no manual roster to maintain. Mess halls
  belong to a specific college, so complaints/inspections are always
  correctly scoped.
- **Google Sign-In** — students sign in with their real college Google
  account (works because college emails are Google Workspace accounts).
  After Google verifies the email, the backend issues a signed session
  token (24 hours); every student request is identified only by that
  token, so nobody can submit or act as someone else by sending a
  different email.
- **Student complaints** — tied to the signed-in student's verified email,
  with an optional photo upload as evidence (max 4MB, JPEG/PNG/WEBP only,
  validated both client- and server-side; the server decodes the image and
  re-encodes it as a fresh JPEG, which drops EXIF/GPS metadata). Categories: food poisoning,
  insect in food, foreign object, undercooked, stale/spoiled, hygiene issue,
  too oily, overcooked/burnt, too spicy, other.
- **Pattern-verified alerts** — every complaint is recorded immediately as
  evidence, but an alert only fires once a pattern is confirmed within a
  rolling **30-day window**:
  - **20+ different students** reporting the same category at a mess hall, or
  - **45+ different students** reporting any category at a mess hall.
  Counting distinct students (not rows) means one account can't fake a
  pattern, and each student is limited to **3 complaints per mess hall per
  24 hours**. While a pattern's alert is open, later complaints are recorded
  but don't create duplicates. Once it's resolved, the pattern re-arms:
  only complaints filed after the resolution count, so it fires again if
  the problem comes back.
- **My Reports** — students can see their own complaint history and the
  alert each complaint is part of. Once an alert has been escalating for
  **2+ days**, students who reported it can vote that it's fixed; it
  closes when **3 different reporting students** agree.
- **Inspector checklist entry** — inspectors log in with their own account,
  and each inspection is recorded under that account. FSSAI-aligned hygiene
  checklist, auto-scored. Failing any *critical* item (temperature control,
  cross-contamination, potable water, pest control, expiry checks) triggers
  a **High** alert regardless of overall score.
- **3-level alerts mapped to an authority chain**:
  - 🟢 Low → **Mess Head**
  - 🟡 Medium → **Principal**
  - 🔴 High → **FSSAI**
- **Auto-escalation** — any alert unresolved for **7 days** automatically
  moves up the chain.
- **Staff accounts** — every admin and inspector has their own email +
  password (scrypt-hashed), managed in **Admin Panel → 👥 Staff**:
  - **Inspector** — submits inspections and sees student complaints. Can't
    open the Admin Panel or call any admin endpoint.
  - **Admin** — full Admin Panel.
  - Either role can be limited to **one college** or cover **all colleges**.
    A college-limited account only ever sees and changes its own college's
    mess halls, complaints, alerts, activity and staff. Only an all-colleges
    admin can add or delete colleges.
  - Inspections and alert resolutions record **who** did them; the Live
    activity feed names the person behind every staff action.
  - Deactivating an account or changing its role takes effect immediately,
    even for someone already logged in. You can't deactivate or demote
    yourself, or remove the last all-colleges admin.
  - The password is sent only once at login; the backend then issues a
    signed, expiring token (8 hours). 5 failed login attempts locks that IP
    out for 6 hours.
- **Admin Panel** — add/remove colleges and mess halls, set alert contacts,
  resolve alerts, view attached photos, manage staff.
- **Live activity log (Admin Panel)** — every complaint (accepted *and*
  rejected), inspection with its failed checklist items, alert raised /
  escalated / resolved, student resolution vote and admin change is written
  to an append-only `activity_log` table in the same transaction as the
  change itself. The Admin Panel's **Live activity** tab streams new
  entries the moment they happen (Server-Sent Events, auto-reconnecting),
  and the **Open alerts** and **All complaints** tabs refresh themselves
  from the same stream. Each entry is also mirrored to the console and to
  `backend/logs/traytrack.log` (rotating, 5 × 5 MB). Pre-existing data is
  backfilled into the log the first time the backend starts.
- **Privacy** — student email is stored only in the private `complaints`
  table and is never shown on the public dashboard. Even the password-gated
  Admin Panel only shows a **masked** email
  (`john.doe@college.edu` → `jo******@college.edu`). Complaint photos are
  also only visible to signed-in staff of the same college (served through
  an authenticated endpoint, never as public static files), and complaint
  text never appears on the public dashboard — only category counts.

## Project structure

```
traytrack/
├── backend/                       FastAPI + MySQL
│   ├── main.py                    All API endpoints
│   ├── database.py                MySQL schema + queries
│   ├── alert_engine.py            Alert creation + pattern thresholds + escalation
│   ├── fssai_rules.py             Checklist + severity + authority mapping
│   ├── auth.py                    Email masking + admin password check
│   ├── uploads/complaints/        Complaint photo storage
│   ├── requirements.txt
│   └── .env.example               DB credentials + Google Client ID template
└── frontend/                      React (Vite)
    └── src/
        ├── App.jsx                Top nav + tab routing
        ├── api.js                 All backend API calls
        ├── Login.jsx              Google Sign-In screen
        ├── SubmitComplaint.jsx    Complaint form (+ photo upload)
        ├── MyReports.jsx          Student's own history + resolve button
        ├── PublicDashboard.jsx    Public: status per mess hall + open alerts
        ├── HistoryTrends.jsx      Public: aggregate trends over time
        ├── InspectorEntry.jsx     Password-gated: hygiene checklist entry
        ├── AdminPanel.jsx         Password-gated: manage colleges/mess halls, resolve alerts
        └── index.css              Styling
```

## Setup

### 1. Database
```sql
CREATE DATABASE mess_monitor;
```
Tables are created automatically the first time the backend starts.

### 2. Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # then fill in your real MySQL password
uvicorn main:app --reload
```
Runs at `http://localhost:8000`.

### 3. Frontend
```bash
cd frontend
npm install
npm run dev
```
Runs at `http://localhost:5173`.

### 4. Google Sign-In setup (one-time, in Google Cloud Console)
1. Create a project → **APIs & Services → Google Auth Platform** → set up
   the consent screen (External, add your app name + support email).
2. **APIs & Services → Credentials → Create Credentials → OAuth Client ID**
   → Application type: **Web application**.
3. Add an **Authorized JavaScript origin**: `http://localhost:5173`
4. Copy the **Client ID** and **Client Secret** into:
   - `backend/.env` → `GOOGLE_CLIENT_ID`
   - `frontend/src/App.jsx` → `GOOGLE_CLIENT_ID` constant

**Note:** while the app is in "Testing" mode in Google Cloud Console, only
the test users you've explicitly added can sign in. Publish the app
(Google Auth Platform → Audience → Publish) to let any student sign in —
this is free and doesn't require verification for basic email sign-in.

## Adding your real college(s)

The first time the backend starts with an empty staff table it creates one
all-colleges admin: email `MESS_ADMIN_EMAIL` (default
`admin@traytrack.local`), password `MESS_ADMIN_PASSWORD` (default
`changeme123`). Log in to the **Admin Panel** with it, then in **👥 Staff**
change its password and create real accounts for each admin and inspector.

Then go to **Manage colleges & mess halls**:
1. Add your college with its real student email domain.
2. Add each mess hall under that college.
3. Repeat for additional colleges whenever you're ready to expand.

Students then just sign in with their real college Google account — no
separate registration step needed.

## Before real deployment

- **Change the bootstrap admin's password and the token secret** — change
  the first admin's password in **Admin Panel → 👥 Staff** (or set
  `MESS_ADMIN_EMAIL` / `MESS_ADMIN_PASSWORD` before the first start), and
  set `ADMIN_TOKEN_SECRET` to a real, random value instead of the default.
- **Publish the Google OAuth consent screen** (see above) so real students
  (not just test users) can sign in.
- **Host MySQL somewhere reachable from your deployed backend** — not just
  `localhost` — if you deploy the backend to a server (e.g. PlanetScale,
  Railway MySQL, AWS RDS).
- Consider running the 7-day escalation check via a scheduled job rather
  than only when a page loads, if the app might go untouched for stretches
  of time.
