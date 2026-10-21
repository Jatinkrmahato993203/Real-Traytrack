import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { getAnalytics } from "./api";

// Category counts only — complaint text stays behind staff login.
function ChartBlock({ title, chartData, total }) {
  return (
    <div className="analytics-block">
      <h3>{title}</h3>

      {chartData.length === 0 ? (
        <p className="hint">No complaints in this period.</p>
      ) : (
        <div style={{ width: "100%", height: 240 }}>
          <ResponsiveContainer>
            <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#DADCD6" />
              <XAxis dataKey="category" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={60} />
              <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#3F6259" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {total > 0 && (
        <p className="hint" style={{ marginTop: 8 }}>
          {total} complaint{total === 1 ? "" : "s"} in this period.
        </p>
      )}
    </div>
  );
}

export default function AnalyticsCharts({ collegeId }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!collegeId) return;
    getAnalytics(collegeId).then(setData);
    // auto-refresh every 60s so the dashboard stays live without manual upkeep
    const interval = setInterval(() => getAnalytics(collegeId).then(setData), 60000);
    return () => clearInterval(interval);
  }, [collegeId]);

  if (!data) return <p className="hint">Loading analytics…</p>;

  return (
    <div className="analytics-grid">
      <ChartBlock title="This week" chartData={data.weekly_chart} total={data.weekly_total} />
      <ChartBlock title="This month" chartData={data.monthly_chart} total={data.monthly_total} />
    </div>
  );
}
