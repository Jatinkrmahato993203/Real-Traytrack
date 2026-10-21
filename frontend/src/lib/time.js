// The backend stores and returns UTC without a timezone suffix
// ("2026-10-21 13:53:32" or "2026-10-21T13:53:32"). Show everything in the
// viewer's local time (IST for most users), never raw UTC.

export function parseUtc(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const s = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return null; // a plain date — see formatDate
  const iso = s.replace(" ", "T");
  const d = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

// Follows the page language (set by the language switch), e.g. hi-IN.
const locale = () => (document.documentElement.lang === "hi" ? "hi-IN" : "en-IN");
const fmtCache = {};
function fmt(kind) {
  const key = `${kind}-${locale()}`;
  if (!fmtCache[key]) {
    fmtCache[key] = kind === "rtf"
      ? new Intl.RelativeTimeFormat(locale(), { numeric: "auto" })
      : new Intl.DateTimeFormat(locale(), kind === "dt" ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
  }
  return fmtCache[key];
}

export function formatDateTime(value) {
  const d = parseUtc(value);
  return d ? fmt("dt").format(d) : value ? String(value) : "—";
}

// Calendar dates ("2026-11-03") have no time or zone — format as-is.
export function formatDate(value) {
  if (!value) return "—";
  const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return fmt("d").format(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  const d = parseUtc(value);
  return d ? fmt("d").format(d) : String(value);
}

export function timeAgo(value) {
  const d = parseUtc(value);
  if (!d) return "";
  const secs = Math.round((d.getTime() - Date.now()) / 1000);
  const abs = Math.abs(secs);
  const rtf = fmt("rtf");
  if (abs < 60) return rtf.format(secs, "second");
  if (abs < 3600) return rtf.format(Math.round(secs / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(secs / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(secs / 86400), "day");
  return formatDate(value);
}

export function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function daysFromToday(n) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
