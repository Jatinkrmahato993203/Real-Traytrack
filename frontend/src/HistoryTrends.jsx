import { useEffect, useState } from "react";
import { getColleges, getTrends } from "./api";

const LEVEL_COLOR = { Low: "🟢", Medium: "🟡", High: "🔴" };

function toDateInputValue(date) {
  return date.toISOString().split("T")[0];
}

function rangeForPreset(preset) {
  const today = new Date();
  if (preset === "half-yearly") {
    const start = new Date(today);
    start.setMonth(start.getMonth() - 6);
    return { startDate: toDateInputValue(start), endDate: toDateInputValue(today) };
  }
  if (preset === "yearly") {
    const start = new Date(today);
    start.setFullYear(start.getFullYear() - 1);
    return { startDate: toDateInputValue(start), endDate: toDateInputValue(today) };
  }
  if (preset === "all") {
    return { startDate: "", endDate: "" };
  }
  return { startDate: "", endDate: "" };
}

export default function HistoryTrends() {
  const [colleges, setColleges] = useState([]);
  const [collegeId, setCollegeId] = useState("");
  const [preset, setPreset] = useState("half-yearly");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [rows, setRows] = useState([]);

  useEffect(() => {
    getColleges().then((cs) => {
      setColleges(cs);
      if (cs.length) setCollegeId(cs[0].id);
    });
  }, []);

  useEffect(() => {
    const { startDate: s, endDate: e } = rangeForPreset(preset);
    setStartDate(s);
    setEndDate(e);
  }, [preset]);

  useEffect(() => {
    if (!collegeId) return;
    getTrends(collegeId, startDate, endDate).then(setRows);
  }, [collegeId, startDate, endDate]);

  const byCategory = {};
  rows.forEach((r) => {
    const key = r.complaint_category || "(inspection)";
    byCategory[key] = (byCategory[key] || 0) + 1;
  });

  return (
    <div className="content wide">
      <h1>History &amp; trends</h1>
      <p className="subtitle">Aggregate view over time — public.</p>

      <div className="tab-row">
        <button className={`tab-btn ${preset === "half-yearly" ? "active" : ""}`} onClick={() => setPreset("half-yearly")}>
          Half-yearly (6 mo)
        </button>
        <button className={`tab-btn ${preset === "yearly" ? "active" : ""}`} onClick={() => setPreset("yearly")}>
          Yearly (12 mo)
        </button>
        <button className={`tab-btn ${preset === "all" ? "active" : ""}`} onClick={() => setPreset("all")}>
          All past data
        </button>
        <button className={`tab-btn ${preset === "custom" ? "active" : ""}`} onClick={() => setPreset("custom")}>
          Custom range
        </button>
      </div>

      <div className="filters-row">
        <label>
          College
          <select value={collegeId} onChange={(e) => setCollegeId(Number(e.target.value))}>
            {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        {preset === "custom" && (
          <>
            <label>
              From
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </label>
            <label>
              To
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </label>
          </>
        )}
      </div>

      {preset !== "custom" && (
        <p className="hint">
          Showing {preset === "all" ? "all past data" : preset === "half-yearly" ? "the last 6 months" : "the last 12 months"}
          {startDate && ` (from ${startDate})`}.
        </p>
      )}

      <h2 style={{ marginTop: 28 }}>Breakdown by category</h2>
      <div className="status-grid">
        {Object.entries(byCategory).map(([cat, count]) => (
          <div key={cat} className="status-card clear">
            <strong>{cat}</strong>
            <div className="status-line">{count} alert(s)</div>
          </div>
        ))}
        {rows.length === 0 && <p className="hint">No alerts in this range.</p>}
      </div>

      <h2 style={{ marginTop: 28 }}>All alerts in range</h2>
      <table className="data-table">
        <thead>
          <tr><th>Mess Hall</th><th>Severity</th><th>Category</th><th>Resolved</th><th>Created</th></tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{a.mess_name}</td>
              <td>{LEVEL_COLOR[a.level]} {a.level}</td>
              <td>{a.complaint_category || "—"}</td>
              <td>{a.resolved ? "Yes" : "No"}</td>
              <td>{a.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
