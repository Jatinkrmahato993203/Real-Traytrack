import { useEffect } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getAnalytics } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { ErrorBanner, Loading, useAsync } from "./ui";

function Chart({ title, total, data, labelKey, translate }) {
  const { t } = useI18n();
  const rows = data.map((d) => ({ ...d, label: translate(d[labelKey]) }));
  return (
    <figure className="analytics-block">
      <figcaption>
        <h3>{title}</h3>
        {total !== undefined && <p className="hint">{t("dash.total", { n: total })}</p>}
      </figcaption>
      {rows.length === 0 ? (
        <p className="hint">{t("dash.noComplaints")}</p>
      ) : (
        <>
          <div style={{ width: "100%", height: Math.max(160, rows.length * 34 + 40) }} aria-hidden="true">
            <ResponsiveContainer>
              <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: "var(--muted)" }} />
                <YAxis type="category" dataKey="label" width={150} tick={{ fontSize: 12, fill: "var(--ink)" }} />
                <Tooltip />
                <Bar dataKey="count" fill="var(--moss)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          {/* The same numbers as text, for screen readers and small screens. */}
          <ul className="sr-only">
            {rows.map((r) => <li key={r.label}>{r.label}: {r.count}</li>)}
          </ul>
        </>
      )}
    </figure>
  );
}

export default function ComplaintCharts({ collegeId }) {
  const { t, tCategory } = useI18n();
  const analytics = useAsync(() => getAnalytics(collegeId), [collegeId]);

  // Keep the dashboard current without anyone refreshing.
  useEffect(() => {
    const id = setInterval(analytics.reload, 60000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collegeId]);

  if (analytics.error) return <ErrorBanner error={analytics.error} onRetry={analytics.reload} />;
  if (!analytics.data) return <Loading />;
  const d = analytics.data;
  return (
    <div className="analytics-grid">
      <Chart title={t("dash.thisWeek")} total={d.weekly_total} data={d.weekly_chart} labelKey="category" translate={tCategory} />
      <Chart title={t("dash.last30")} total={d.monthly_total} data={d.monthly_chart} labelKey="category" translate={tCategory} />
      <Chart title={t("dash.byMeal")} data={d.monthly_by_meal} labelKey="meal" translate={(m) => t(`meal.${m}`)} />
    </div>
  );
}
