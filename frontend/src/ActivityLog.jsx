import { useEffect, useRef, useState } from "react";
import { adminGetActivity, streamAdminActivity } from "./api";
import StaffPhoto from "./StaffPhoto";

const TYPE_FILTERS = [
  { value: "", label: "Everything" },
  { value: "complaint", label: "Complaints" },
  { value: "inspection", label: "Inspections" },
  { value: "alert", label: "Alerts" },
  { value: "resolution", label: "Resolution votes" },
  { value: "admin", label: "Admin changes" },
];

const TYPE_META = {
  complaint_submitted: { icon: "📝", label: "Complaint" },
  complaint_rejected: { icon: "⛔", label: "Rejected complaint" },
  inspection_submitted: { icon: "🔍", label: "Inspection" },
  alert_created: { icon: "🚨", label: "Alert raised" },
  alert_escalated: { icon: "⏫", label: "Alert escalated" },
  alert_resolved: { icon: "✅", label: "Alert resolved" },
  resolution_vote: { icon: "🗳️", label: "Resolution vote" },
};

const LEVEL_DOT = { Low: "🟢", Medium: "🟡", High: "🔴" };

const STATUS_TEXT = {
  connecting: "Connecting…",
  live: "Live",
  reconnecting: "Reconnecting…",
  expired: "Session expired",
};

function meta(type) {
  return TYPE_META[type] || { icon: "🛠️", label: "Admin change" };
}

function Details({ row }) {
  const d = row.details || {};
  if (row.event_type === "complaint_submitted") {
    return (
      <>
        {d.description && <p>{d.description}</p>}
        <p className="hint">Reported by {d.masked_email}</p>
        {d.photo_url && <StaffPhoto photoUrl={d.photo_url} className="activity-photo" />}
      </>
    );
  }
  if (row.event_type === "complaint_rejected") {
    return <p className="hint">{d.category} · from {d.masked_email}</p>;
  }
  if (row.event_type === "inspection_submitted") {
    return (
      <>
        <p className="hint">
          {d.passed}/{d.total} checklist items passed · inspector {d.inspector_name}
        </p>
        {d.failed_items?.length > 0 && (
          <ul className="activity-failed">
            {d.failed_items.map((f) => (
              <li key={f.text}>{f.critical ? "⚠️ " : ""}{f.text}{f.critical ? " (critical)" : ""}</li>
            ))}
          </ul>
        )}
      </>
    );
  }
  if (row.event_type.startsWith("alert_")) {
    return (
      <>
        <p className="hint">{LEVEL_DOT[d.level]} {d.level} → {d.authority}</p>
        {d.note && <p>{d.note}</p>}
      </>
    );
  }
  return null;
}

// Everything that happens in the system, newest first, updating in real
// time as students file complaints, inspectors submit checklists, alerts
// move, and admins make changes.
export default function ActivityLog({ colleges, onSessionExpired }) {
  const [collegeId, setCollegeId] = useState("");
  const [eventType, setEventType] = useState("");
  const [rows, setRows] = useState([]);
  const [freshIds, setFreshIds] = useState(new Set());
  const [status, setStatus] = useState("connecting");
  const [error, setError] = useState("");
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const eventTypeRef = useRef(eventType);
  eventTypeRef.current = eventType;

  useEffect(() => {
    let stop = () => {};
    let cancelled = false;
    setRows([]);
    setLoading(true);
    setError("");
    setStatus("connecting");

    adminGetActivity({ collegeId, eventType, limit: 50 })
      .then((initial) => {
        if (cancelled) return;
        setRows(initial);
        setHasMore(initial.length === 50);
        setLoading(false);
        // Stream everything after the newest row we already have. The
        // backend's id order is the source of truth, so nothing that
        // happens between the fetch and the stream connecting is missed.
        const newestId = initial.length ? initial[0].id : 0;
        stop = streamAdminActivity({
          afterId: newestId,
          collegeId,
          onStatus: (s) => {
            setStatus(s);
            if (s === "expired") onSessionExpired?.();
          },
          onEvent: (row) => {
            const filter = eventTypeRef.current;
            if (filter && !row.event_type.startsWith(filter)) return;
            setRows((prev) => (prev.some((r) => r.id === row.id) ? prev : [row, ...prev]));
            setFreshIds((prev) => new Set(prev).add(row.id));
            setTimeout(() => {
              setFreshIds((prev) => {
                const next = new Set(prev);
                next.delete(row.id);
                return next;
              });
            }, 4000);
          },
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setLoading(false);
        if (err.status === 401) onSessionExpired?.();
        else setError(err.message);
      });

    return () => {
      cancelled = true;
      stop();
    };
  }, [collegeId, eventType]);

  async function loadOlder() {
    const oldest = rows[rows.length - 1];
    if (!oldest) return;
    const older = await adminGetActivity({ collegeId, eventType, beforeId: oldest.id, limit: 50 });
    setRows((prev) => [...prev, ...older]);
    setHasMore(older.length === 50);
  }

  return (
    <>
      <div className="activity-toolbar">
        <span className={`live-pill ${status}`}>
          <span className="live-dot" /> {STATUS_TEXT[status]}
        </span>
        <span className="hint">
          Every complaint, inspection, alert change and admin action — updates the moment it happens.
        </span>
      </div>

      <div className="contact-grid">
        <label>College
          <select value={collegeId} onChange={(e) => setCollegeId(e.target.value)}>
            <option value="">All colleges</option>
            {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>Show
          <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
            {TYPE_FILTERS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
      </div>

      {error && <div className="banner error">{error}</div>}
      {loading && <p className="hint">Loading…</p>}
      {!loading && !error && rows.length === 0 && (
        <div className="banner info">Nothing has happened yet. New activity will appear here automatically.</div>
      )}

      {rows.map((row) => {
        const m = meta(row.event_type);
        return (
          <div key={row.id} className={`report-card activity-item ${freshIds.has(row.id) ? "activity-new" : ""}`}>
            <div className="report-card-head">
              <strong>{m.icon} {row.summary}</strong>
              <span className="hint">{String(row.created_at).replace("T", " ")} UTC</span>
            </div>
            <p className="hint">
              {m.label}
              {row.college_name ? ` · ${row.college_name}` : ""}
            </p>
            <Details row={row} />
          </div>
        );
      })}

      {!loading && hasMore && rows.length > 0 && (
        <button className="link-btn" style={{ marginTop: 14 }} onClick={loadOlder}>Load older activity</button>
      )}
    </>
  );
}
