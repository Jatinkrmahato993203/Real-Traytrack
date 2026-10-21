import { useEffect, useState } from "react";
import { getColleges, getDashboardStatus, getOpenAlerts, getMessHalls } from "./api";
import AnalyticsCharts from "./AnalyticsCharts";

const LEVEL_COLOR = { Low: "🟢", Medium: "🟡", High: "🔴" };

export default function PublicDashboard() {
  const [colleges, setColleges] = useState([]);
  const [collegeId, setCollegeId] = useState("");
  const [statusList, setStatusList] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [messHalls, setMessHalls] = useState([]);
  const [messFilter, setMessFilter] = useState("");

  useEffect(() => {
    getColleges().then((cs) => {
      setColleges(cs);
      if (cs.length) setCollegeId(cs[0].id);
    });
  }, []);

  useEffect(() => {
    if (!collegeId) return;
    getDashboardStatus(collegeId).then(setStatusList);
    getMessHalls(collegeId).then(setMessHalls);
    getOpenAlerts(collegeId).then(setAlerts);
    setMessFilter("");
  }, [collegeId]);

  useEffect(() => {
    if (!collegeId) return;
    getOpenAlerts(collegeId, messFilter || undefined).then(setAlerts);
  }, [messFilter]);

  return (
    <div className="content wide">
      <h1>Public dashboard</h1>
      <p className="subtitle">Live food safety status — no student or inspector identity is shown here.</p>

      <label style={{ maxWidth: 320 }}>
        College
        <select value={collegeId} onChange={(e) => setCollegeId(Number(e.target.value))}>
          {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>

      <h2 style={{ marginTop: 32 }}>Current status by mess hall</h2>
      <div className="status-grid">
        {statusList.map((s) => (
          <div key={s.mess.id} className={`status-card ${s.status}`}>
            <strong>{s.mess.name}</strong>
            {s.status === "clear" ? (
              <div className="status-line">🟢 No open alerts</div>
            ) : (
              <>
                <div className="status-line">{LEVEL_COLOR[s.worst_level]} {s.worst_level}</div>
                <div className="hint">With: {s.authority} · {s.open_count} open alert(s)</div>
              </>
            )}
          </div>
        ))}
      </div>

      <h2 style={{ marginTop: 32 }}>Complaint trends</h2>
      <p className="hint">Auto-updates from live data — no manual upkeep needed.</p>
      <AnalyticsCharts collegeId={collegeId} />

      <h2 style={{ marginTop: 32 }}>Open alerts</h2>
      <label style={{ maxWidth: 320 }}>
        Filter by mess hall
        <select value={messFilter} onChange={(e) => setMessFilter(e.target.value)}>
          <option value="">All</option>
          {messHalls.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
      </label>

      {alerts.length === 0 ? (
        <div className="banner info" style={{ marginTop: 16 }}>No open alerts right now.</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>Mess Hall</th><th>Severity</th><th>Reason</th><th>FSSAI Reference</th><th>Reported At</th></tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id}>
                <td>{a.mess_name}</td>
                <td>{LEVEL_COLOR[a.level]} {a.level}</td>
                <td>{a.reason}</td>
                <td>{a.fssai_reference}</td>
                <td>{a.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
