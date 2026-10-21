# Privacy notice — brief for legal / institutional review

The privacy notice students see is in `frontend/src/pages/Privacy.jsx` (English
and Hindi), with a short version shown before a student's first report
(`frontend/src/lib/i18n.jsx`, keys `consent.*`). It was written to describe
what the software actually does; **it has not been reviewed by a lawyer.**
This brief lists every fact a reviewer needs and the questions to answer.

## What is collected, and where it goes

| Data | From | Stored | Who can see it | Removed |
|---|---|---|---|---|
| College email, name | Google Sign-In | `complaints`, `meal_ratings`, `sessions`, `student_consents` | Staff see a **masked** email (`ra*****@college.edu`) or nothing (anonymous reports). Never public. | Automatically after `RETENTION_DAYS` (default 365); immediately on "Delete my data" |
| Report: hall, category, meal, dish, description, time | Student | `complaints` | Staff of that college. Public sees **counts only**. | Description/dish/photo/identity removed at retention or deletion; category/hall/time kept as anonymous counts |
| Photo | Student (optional) | Re-encoded JPEG on the server (EXIF/GPS stripped) | Signed-in staff of that college only | Deleted at retention or deletion |
| Meal rating + comment | Student | `meal_ratings` | Averages are public; individual ratings are not shown | Identity + comment removed at retention or deletion |
| IP address, browser | Every sign-in | `sessions` (for security) | Not shown in the app | Session rows purged 30 days after they end |
| Staff name, email | Admin creates account | `staff_users` | Other staff of the college | When the account is removed by an admin |
| Inspector location (optional) | Inspector's device, opt-in per inspection | `inspections` | Staff of that college | Kept with the inspection record |

Alert emails go to the college's Mess Head / Principal / FSSAI contact addresses
and contain the hall, severity and reason — **no student identity**. Replies to
a student's complaint are emailed to that student's college address.

## Students' controls
- Consent screen before the first report (version recorded per student).
- "Report anonymously" — staff see "Anonymous student". The notice says the
  account is still used to stop duplicate reports.
- Download all their data (JSON) and delete it, from **My reports**.
- Grievance contact per college, shown on the privacy page (set by admins in
  Setup → Contacts).

## Questions for the reviewer
1. **Lawful basis / consent (DPDP Act 2023):** is the consent screen sufficient
   as notice + consent, or does the institution prefer "legitimate use"
   (Section 7) for food-safety reporting? Does the wording need changing?
2. **Data Fiduciary:** the college (not the software author) is the fiduciary —
   should the notice name the college and a Data Protection Officer/grievance
   officer explicitly? (Currently: per-college grievance contact field.)
3. **Retention period:** is 365 days appropriate? (`RETENTION_DAYS` in `backend/.env`.)
4. **Minors:** some first-year students may be under 18. Does the institution
   need verifiable parental consent, or is the college relationship sufficient?
5. **Staff-named complaints:** complaints can mention mess staff. Staff with
   the right role can hide such text; is that process adequate (defamation risk)?
6. **Email to authorities:** is sending alert details to an external FSSAI contact
   covered, and should the notice mention it more prominently?
7. **Hosting location:** where will the server/database live, and does that need
   stating?

## Hindi
The Hindi text (notice and all student screens) was machine-written and needs a
native speaker's review: `docs/review/hindi-review.csv` lists every string with
columns for corrections. Regenerate it after changes with
`node docs/review/export-hindi.mjs`.
