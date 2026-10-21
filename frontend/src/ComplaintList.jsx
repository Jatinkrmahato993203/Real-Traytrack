import { useEffect, useState } from "react";
import { adminGetComplaints, subscribeToNewActivity } from "./api";
import StaffPhoto from "./StaffPhoto";

const PERIODS = [
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
  { days: 0, label: "All time" },
];

// Every individual student complaint — including ones that haven't formed
// an alert pattern yet. Used by the Admin Panel (all mess halls) and the
// Inspector screen (only the mess hall being inspected).
export default function ComplaintList({ collegeId, messId }) {
  const [days, setDays] = useState(30);
  const [category, setCategory] = useState("");
  const [complaints, setComplaints] = useState(null);
  const [error, setError] = useState("");

  function load() {
    setError("");
    setComplaints(null);
    adminGetComplaints({ collegeId, messId, days })
      .then(setComplaints)
      .catch((err) => setError(err.message));
  }

  useEffect(load, [collegeId, messId, days]);

  // New complaints show up without a manual refresh.
  useEffect(() => subscribeToNewActivity({
    collegeId,
    onEvent: (row) => {
      if (row.event_type !== "complaint_submitted") return;
      if (messId && String(row.mess_id) !== String(messId)) return;
      adminGetComplaints({ collegeId, messId, days }).then(setComplaints).catch(() => {});
    },
  }), [collegeId, messId, days]);

  const categories = [...new Set((complaints || []).map((c) => c.category))].sort();
  const shown = (complaints || []).filter((c) => !category || c.category === category);

  return (
    <>
      <div className="contact-grid">
        <label>Period
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {PERIODS.map((p) => <option key={p.days} value={p.days}>{p.label}</option>)}
          </select>
        </label>
        <label>Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      <button className="link-btn" onClick={load}>↻ Refresh</button>

      {error && <div className="banner error">{error}</div>}
      {!error && !complaints && <p className="hint">Loading…</p>}
      {complaints && (
        <p className="hint">
          {shown.length} complaint{shown.length === 1 ? "" : "s"}. Student emails are masked.
        </p>
      )}
      {complaints && shown.length === 0 && (
        <div className="banner info">No complaints in this period.</div>
      )}

      {shown.map((c) => (
        <div key={c.id} className="report-card">
          <div className="report-card-head">
            <strong>#{c.id} · {c.mess_name} · {c.category}</strong>
            <span className="hint">{String(c.created_at).replace("T", " ")}</span>
          </div>
          {!messId && <p className="hint">{c.college_name}</p>}
          {c.description && <p>{c.description}</p>}
          <p className="hint">Reported by {c.masked_email}</p>
          {c.photo_url && <StaffPhoto photoUrl={c.photo_url} style={{ maxWidth: 240, borderRadius: 8 }} />}
        </div>
      ))}
    </>
  );
}
