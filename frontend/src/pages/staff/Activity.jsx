import { useEffect, useRef, useState } from "react";
import { getActivity, streamActivity } from "../../lib/api";
import { formatDateTime, timeAgo } from "../../lib/time";
import { ErrorBanner, Loading, Severity, StaffPhoto } from "../../components/ui";
import { ScopeFilters, useScope } from "./common";

const TYPE_FILTERS = [
  ["", "Everything"], ["complaint", "Complaints"], ["inspection", "Inspections"], ["alert", "Alerts"],
  ["resolution", "Student votes"], ["compliance", "Compliance"], ["admin", "Admin changes"],
];

const META = {
  complaint_submitted: ["📝", "Complaint"], complaint_rejected: ["⛔", "Rejected complaint"],
  complaint_responded: ["💬", "Reply to student"], inspection_submitted: ["🔍", "Inspection"],
  inspection_scheduled: ["📅", "Inspection scheduled"], alert_created: ["🚨", "Alert raised"],
  alert_escalated: ["⏫", "Alert escalated"], alert_resolved: ["✅", "Alert resolved"],
  alert_reminder: ["⏰", "Reminder"], alert_reopened: ["↩️", "Alert reopened"], resolution_vote: ["🗳️", "Student vote"],
  compliance_added: ["📄", "Compliance"], compliance_deleted: ["📄", "Compliance"],
  student_data_erased: ["🧹", "Privacy"],
};
const meta = (type) => META[type] || (type.startsWith("alert_") ? ["🚨", "Alert update"] : ["🛠️", "Admin change"]);
const STATUS_TEXT = { connecting: "Connecting…", live: "Live", reconnecting: "Reconnecting…", expired: "Session expired" };
const PAGE = 50;

function Details({ row }) {
  const d = row.details || {};
  if (row.event_type === "complaint_submitted") {
    return (
      <>
        {(d.meal || d.dish) && <p className="hint">{[d.meal, d.dish].filter(Boolean).join(" · ")}</p>}
        {d.description && <p>{d.description}</p>}
        <p className="hint">Reported by {d.masked_email}</p>
        {d.photo_url && <StaffPhoto url={d.photo_url} />}
      </>
    );
  }
  if (row.event_type === "inspection_submitted") {
    return (
      <>
        <p className="hint">
          {d.passed}/{d.total} applicable items passed{d.na ? ` · ${d.na} N/A` : ""} ·{" "}
          {d.verified_onsite ? "✓ verified on site" : "not verified on site"}
        </p>
        {d.failed_items?.length > 0 && (
          <ul className="failed-list">
            {d.failed_items.map((f) => (
              <li key={f.text}>{f.critical && <strong>Critical: </strong>}{f.text}{f.note && <span className="hint"> — {f.note}</span>}</li>
            ))}
          </ul>
        )}
      </>
    );
  }
  if (row.event_type.startsWith("alert_")) {
    return (
      <>
        {d.level && <p className="hint"><Severity level={d.level} /> → {d.authority}</p>}
        {d.note && <p>{d.note}</p>}
      </>
    );
  }
  if (d.response) return <p>{d.response}</p>;
  return null;
}

export default function Activity() {
  const scope = useScope();
  const { collegeId, messId } = scope;
  const [type, setType] = useState("");
  const [rows, setRows] = useState([]);
  const [fresh, setFresh] = useState(new Set());
  const [status, setStatus] = useState("connecting");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const typeRef = useRef(type);
  typeRef.current = type;

  useEffect(() => {
    let stop = () => {};
    let cancelled = false;
    setRows([]);
    setLoading(true);
    setError(null);
    setStatus("connecting");
    getActivity({ college_id: collegeId, mess_id: messId, event_type: type, limit: PAGE })
      .then((initial) => {
        if (cancelled) return;
        setRows(initial);
        setHasMore(initial.length === PAGE);
        setLoading(false);
        stop = streamActivity({
          afterId: initial[0]?.id || 0, collegeId, messId, onStatus: setStatus,
          onEvent: (row) => {
            if (typeRef.current && !row.event_type.startsWith(typeRef.current)) return;
            setRows((prev) => (prev.some((r) => r.id === row.id) ? prev : [row, ...prev]));
            setFresh((prev) => new Set(prev).add(row.id));
            setTimeout(() => setFresh((prev) => { const n = new Set(prev); n.delete(row.id); return n; }), 4000);
          },
        });
      })
      .catch((e) => { if (!cancelled) { setError(e); setLoading(false); } });
    return () => { cancelled = true; stop(); };
  }, [collegeId, messId, type]);

  async function loadOlder() {
    const older = await getActivity({ college_id: collegeId, mess_id: messId, event_type: type, before_id: rows[rows.length - 1].id, limit: PAGE });
    setRows((prev) => [...prev, ...older]);
    setHasMore(older.length === PAGE);
  }

  return (
    <>
      <div className="activity-toolbar">
        <span className={`live-pill ${status}`} role="status"><span className="live-dot" /> {STATUS_TEXT[status]}</span>
        <span className="hint">Every complaint, inspection, alert change and admin action — updates the moment it happens.</span>
      </div>
      <ScopeFilters scope={scope}>
        <label className="field inline-field">
          <span className="field-label">Show</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {TYPE_FILTERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      </ScopeFilters>
      <ErrorBanner error={error} />
      {loading && <Loading />}
      {!loading && !error && rows.length === 0 && <div className="banner info">Nothing yet. New activity appears here automatically.</div>}
      {rows.map((row) => {
        const [icon, label] = meta(row.event_type);
        return (
          <article key={row.id} className={`report-card activity-item ${fresh.has(row.id) ? "activity-new" : ""}`}>
            <div className="report-card-head">
              <strong><span aria-hidden="true">{icon}</span> {row.summary}</strong>
              <time className="hint" dateTime={row.created_at} title={formatDateTime(row.created_at)}>{timeAgo(row.created_at)}</time>
            </div>
            <p className="hint">{label}{row.college_name ? ` · ${row.college_name}` : ""}</p>
            <Details row={row} />
          </article>
        );
      })}
      {hasMore && <button type="button" className="secondary-btn" onClick={loadOlder}>Load older</button>}
    </>
  );
}
