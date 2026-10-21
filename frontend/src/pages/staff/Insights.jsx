import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getInsights } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { ErrorBanner, Loading, useAsync } from "../../components/ui";
import { useScope } from "./common";

function Stat({ label, value, hint }) {
  return (
    <div className="stat">
      <div className="stat-value">{value ?? "—"}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="hint small">{hint}</div>}
    </div>
  );
}

const hours = (h) => (h == null ? "—" : h < 48 ? `${h} h` : `${Math.round(h / 24)} days`);

function Curve({ data, current, title, xLabel }) {
  return (
    <figure className="analytics-block">
      <figcaption><h3>{title}</h3><p className="hint">{xLabel}. The dashed line is your current setting.</p></figcaption>
      <div style={{ width: "100%", height: 220 }} aria-hidden="true">
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 8, right: 12, left: -12, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
            <XAxis dataKey="threshold" tick={{ fontSize: 12 }} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
            <Tooltip formatter={(v) => [v, "alerts"]} labelFormatter={(t) => `threshold ${t}`} />
            <ReferenceLine x={current} stroke="var(--danger)" strokeDasharray="4 3" />
            <Bar dataKey="alerts" fill="var(--moss)" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="sr-only">{data.map((d) => `threshold ${d.threshold}: ${d.alerts} alerts`).join("; ")}</p>
    </figure>
  );
}

export default function Insights() {
  const scope = useScope({ withMess: false });
  const { can } = useStaff();
  const [days, setDays] = useState(90);
  const collegeId = scope.collegeId || scope.colleges.data?.[0]?.id;
  const data = useAsync(() => (collegeId ? getInsights(collegeId, days) : null), [collegeId, days]);
  const d = data.data;

  return (
    <>
      <p className="hint">
        For running a pilot: how much is being reported, how fast alerts are handled, and what different alert
        thresholds would have produced on this college's own data.
      </p>
      <div className="filters-row">
        {!scope.staff.college_id && (
          <label className="field inline-field"><span className="field-label">College</span>
            <select value={collegeId || ""} onChange={(e) => scope.setCollegeId(e.target.value)}>
              {(scope.colleges.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        )}
        <label className="field inline-field"><span className="field-label">Period</span>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={180}>Last 6 months</option><option value={365}>Last year</option>
          </select>
        </label>
      </div>
      <ErrorBanner error={data.error} onRetry={data.reload} />
      {data.loading && !d && <Loading />}
      {d && (
        <>
          <div className="stat-grid">
            <Stat label="Complaints" value={d.totals.complaints} hint={`from ${d.totals.reporters} different students`} />
            <Stat label="Alerts raised" value={d.totals.alerts} hint={Object.entries(d.totals.alerts_by_source).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ")} />
            <Stat label="Median time to first action" value={hours(d.totals.median_hours_to_first_action)} />
            <Stat label="Median time to resolve" value={hours(d.totals.median_hours_to_resolve)} />
            <Stat label="Never acted on" value={d.totals.never_actioned} hint="open alerts nobody has touched" />
            <Stat label="Reopened" value={d.totals.reopened} hint="fixes that didn't hold" />
            <Stat label="Authority notified" value={d.totals.notified_pct == null ? "—" : `${d.totals.notified_pct}%`} hint="alerts with a delivered email" />
          </div>

          <h2>Tuning the alert thresholds</h2>
          <p className="hint">{d.simulation.note}</p>
          <div className="analytics-grid">
            <Curve data={d.simulation.category_curve} current={d.settings.category_max} title="Same-category alerts"
              xLabel={`Different students reporting the same thing at one hall within ${d.settings.window_days} days`} />
            <Curve data={d.simulation.fast_lane_curve} current={d.settings.fast_lane_reporters} title="Safety fast lane"
              xLabel={`Students reporting food poisoning / insects / foreign objects within ${d.settings.fast_lane_hours} hours`} />
          </div>
          <p className="hint">
            Too many alerts and people stop reading them; too few and real problems are missed. Aim for a level the
            mess team can actually act on.{" "}
            {can("setup") && <Link to="/admin/setup">Change the rules in Setup → Alert rules.</Link>}
          </p>

          {d.simulation.top_patterns.length > 0 && (
            <>
              <h3>Biggest patterns in this period</h3>
              <table className="data-table responsive">
                <thead><tr><th>Hall</th><th>Category</th><th>Peak reporters</th><th>Current threshold</th></tr></thead>
                <tbody>
                  {d.simulation.top_patterns.map((p) => (
                    <tr key={`${p.mess_id}-${p.category}`}>
                      <td data-label="Hall">{p.mess_name}</td>
                      <td data-label="Category">{p.category}</td>
                      <td data-label="Peak reporters">{p.peak_reporters}</td>
                      <td data-label="Current threshold">{p.current_threshold}{p.peak_reporters >= p.current_threshold ? " — reached" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <h3>Weekly volume</h3>
          {d.volume.length === 0 ? <p className="hint">No complaints in this period.</p> : (
            <table className="data-table responsive">
              <thead><tr><th>Week of</th><th>Complaints</th><th>Different students</th></tr></thead>
              <tbody>{d.volume.map((v) => <tr key={v.week}><td data-label="Week of">{v.week}</td><td data-label="Complaints">{v.complaints}</td><td data-label="Students">{v.reporters}</td></tr>)}</tbody>
            </table>
          )}
        </>
      )}
    </>
  );
}
