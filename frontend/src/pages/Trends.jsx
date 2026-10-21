import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getTrends } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { daysFromToday, formatDate, todayIso } from "../lib/time";
import { ErrorBanner, Loading, Severity, StatusPill, useAsync } from "../components/ui";
import { CollegeSelect, useCollegePicker } from "./Dashboard";

const PRESETS = { "6m": -183, "12m": -365, all: null };
const SERIES_COLORS = ["#3F6259", "#C77D2E", "#6B7FA8", "#A13939", "#7A8F3C", "#8C5A9E", "#4E9AA8", "#B5734F"];

export default function Trends() {
  const { t, tCategory } = useI18n();
  const { colleges, collegeId, setCollegeId } = useCollegePicker();
  const [preset, setPreset] = useState("6m");
  const [custom, setCustom] = useState({ from: daysFromToday(-30), to: todayIso() });

  const range = preset === "custom"
    ? custom
    : { from: PRESETS[preset] === null ? "" : daysFromToday(PRESETS[preset]), to: PRESETS[preset] === null ? "" : todayIso() };
  const data = useAsync(() => (collegeId ? getTrends(collegeId, range.from, range.to) : null), [collegeId, range.from, range.to]);

  // Complaints per month, one bar segment per category (top 7 + "Other").
  const { months, categories } = useMemo(() => {
    const rows = data.data?.complaints_by_month || [];
    const totals = {};
    rows.forEach((r) => { totals[r.category] = (totals[r.category] || 0) + r.count; });
    const top = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 7).map(([c]) => c);
    const byMonth = {};
    rows.forEach((r) => {
      const key = top.includes(r.category) ? r.category : "Other";
      byMonth[r.month] = byMonth[r.month] || { month: r.month };
      byMonth[r.month][key] = (byMonth[r.month][key] || 0) + r.count;
    });
    const cats = rows.some((r) => !top.includes(r.category)) ? [...top, "Other"] : top;
    return { months: Object.values(byMonth), categories: cats };
  }, [data.data]);

  const alertsByCause = useMemo(() => {
    const out = {};
    (data.data?.alerts || []).forEach((a) => {
      const key = a.complaint_category ? tCategory(a.complaint_category) : t("trends.inspection");
      out[key] = (out[key] || 0) + 1;
    });
    return Object.entries(out).sort((a, b) => b[1] - a[1]);
  }, [data.data, t, tCategory]);

  return (
    <div className="content wide">
      <h1>{t("trends.title")}</h1>
      <p className="subtitle">{t("trends.subtitle")}</p>

      <div className="tab-row" role="group" aria-label="Time range">
        {["6m", "12m", "all", "custom"].map((p) => (
          <button key={p} type="button" aria-pressed={preset === p} className={`tab-btn ${preset === p ? "active" : ""}`} onClick={() => setPreset(p)}>
            {t(`trends.${p}`)}
          </button>
        ))}
      </div>
      <div className="filters-row">
        <CollegeSelect colleges={colleges} value={collegeId} onChange={setCollegeId} />
        {preset === "custom" && (
          <>
            <label className="field inline-field"><span className="field-label">{t("trends.from")}</span>
              <input type="date" value={custom.from} max={custom.to} onChange={(e) => setCustom({ ...custom, from: e.target.value })} />
            </label>
            <label className="field inline-field"><span className="field-label">{t("trends.to")}</span>
              <input type="date" value={custom.to} min={custom.from} onChange={(e) => setCustom({ ...custom, to: e.target.value })} />
            </label>
          </>
        )}
      </div>

      <ErrorBanner error={data.error} onRetry={data.reload} />
      {data.loading && !data.data && <Loading />}

      {data.data && (
        <>
          <section>
            <h2>{t("trends.complaintsByMonth")}</h2>
            {months.length === 0 ? <p className="hint">{t("trends.none")}</p> : (
              <div style={{ width: "100%", height: 320 }} aria-hidden="true">
                <ResponsiveContainer>
                  <BarChart data={months} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" vertical={false} />
                    <XAxis dataKey="month" tick={{ fontSize: 12, fill: "var(--muted)" }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "var(--muted)" }} />
                    <Tooltip formatter={(v, name) => [v, tCategory(name)]} />
                    <Legend formatter={(name) => tCategory(name)} />
                    {categories.map((c, i) => (
                      <Bar key={c} dataKey={c} stackId="a" fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <table className="sr-only">
              <tbody>{months.map((m) => <tr key={m.month}><th>{m.month}</th>{categories.map((c) => <td key={c}>{tCategory(c)}: {m[c] || 0}</td>)}</tr>)}</tbody>
            </table>
          </section>

          <section>
            <h2>{t("trends.alertSummary")}</h2>
            {alertsByCause.length === 0 ? <p className="hint">{t("trends.none")}</p> : (
              <div className="status-grid">
                {alertsByCause.map(([cause, n]) => (
                  <div key={cause} className="status-card clear"><h3>{cause}</h3><p className="status-line">{n}</p></div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h2>{t("trends.alertsInRange")}</h2>
            {data.data.alerts.length === 0 ? <p className="hint">{t("trends.none")}</p> : (
              <table className="data-table responsive">
                <thead><tr><th>{t("th.hall")}</th><th>{t("th.severity")}</th><th>{t("th.category")}</th><th>{t("th.status")}</th><th>{t("th.raised")}</th></tr></thead>
                <tbody>
                  {data.data.alerts.map((a) => (
                    <tr key={a.id}>
                      <td data-label={t("th.hall")}>{a.mess_name}</td>
                      <td data-label={t("th.severity")}><Severity level={a.level} /></td>
                      <td data-label={t("th.category")}>{a.complaint_category ? tCategory(a.complaint_category) : t("trends.inspection")}</td>
                      <td data-label={t("th.status")}><StatusPill status={a.status} /></td>
                      <td data-label={t("th.raised")}>{formatDate(a.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
