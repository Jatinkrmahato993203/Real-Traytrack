import { lazy, Suspense, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getColleges, getDashboardStatus, getOpenAlerts } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { useStudent } from "../lib/session";
import { ErrorBanner, Loading, Severity, StatusPill, useAsync, When } from "../components/ui";
import { formatDate } from "../lib/time";

const ComplaintCharts = lazy(() => import("../components/ComplaintCharts"));

export function useCollegePicker() {
  const { me } = useStudent();
  const colleges = useAsync(getColleges, []);
  const [collegeId, setCollegeId] = useState("");
  useEffect(() => {
    if (!collegeId && colleges.data?.length) {
      // A signed-in student lands on their own college.
      setCollegeId(String(me?.college?.id || colleges.data[0].id));
    }
  }, [colleges.data, me, collegeId]);
  return { colleges, collegeId, setCollegeId };
}

export function CollegeSelect({ colleges, value, onChange }) {
  const { t } = useI18n();
  if (!colleges.data || colleges.data.length < 2) return null;
  return (
    <label className="field inline-field">
      <span className="field-label">{t("common.college")}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {colleges.data.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    </label>
  );
}

function HallCard({ s }) {
  const { t } = useI18n();
  return (
    <article className={`status-card ${s.status}`}>
      <h3>{s.mess.name}</h3>
      {s.status === "clear" ? (
        <p className="status-line"><span aria-hidden="true">✓</span> {t("dash.clear")}</p>
      ) : (
        <>
          <p className="status-line"><Severity level={s.worst_level} /> · {t("dash.openCount", { n: s.open_count })}</p>
          <p className="hint">
            {t("dash.with", { who: t(`authority.${s.authority}`) })} —{" "}
            {s.authority_notified ? t("dash.notified") : <span className="warn-text">{t("dash.notNotified")}</span>}
          </p>
        </>
      )}
      <dl className="mini-stats">
        <div>
          <dt>{t("dash.lastInspection")}</dt>
          <dd>{s.last_inspection ? <>{formatDate(s.last_inspection.at)} · {t("dash.score", { score: s.last_inspection.score })}</> : t("common.never")}</dd>
        </div>
        <div>
          <dt>★</dt>
          <dd>{s.rating ? t("dash.rating", { avg: s.rating.avg.toFixed(1), n: s.rating.count }) : t("dash.noRatings")}</dd>
        </div>
      </dl>
    </article>
  );
}

export default function Dashboard() {
  const { t, tCategory } = useI18n();
  const { colleges, collegeId, setCollegeId } = useCollegePicker();
  const [messFilter, setMessFilter] = useState("");
  const status = useAsync(() => (collegeId ? getDashboardStatus(collegeId) : null), [collegeId]);
  const alerts = useAsync(() => (collegeId ? getOpenAlerts(collegeId, messFilter) : null), [collegeId, messFilter]);

  useEffect(() => setMessFilter(""), [collegeId]);

  return (
    <div className="content wide">
      <div className="page-head">
        <div>
          <h1>{t("dash.title")}</h1>
          <p className="subtitle">{t("dash.subtitle")}</p>
        </div>
        <div className="cta-card">
          <span>{t("dash.reportCta")}</span>
          <Link className="primary-btn" to="/report">{t("dash.reportCtaBtn")}</Link>
        </div>
      </div>

      <ErrorBanner error={colleges.error} onRetry={colleges.reload} />
      <CollegeSelect colleges={colleges} value={collegeId} onChange={setCollegeId} />

      <section aria-labelledby="halls-h">
        <h2 id="halls-h">{t("dash.statusByHall")}</h2>
        <ErrorBanner error={status.error} onRetry={status.reload} />
        {status.loading && !status.data && <Loading />}
        <div className="status-grid">
          {(status.data || []).map((s) => <HallCard key={s.mess.id} s={s} />)}
        </div>
      </section>

      <section aria-labelledby="trends-h">
        <h2 id="trends-h">{t("dash.trends")}</h2>
        <Suspense fallback={<Loading />}>
          {collegeId && <ComplaintCharts collegeId={collegeId} />}
        </Suspense>
      </section>

      <section aria-labelledby="alerts-h">
        <h2 id="alerts-h">{t("dash.openAlerts")}</h2>
        <label className="field inline-field">
          <span className="field-label">{t("dash.filterHall")}</span>
          <select value={messFilter} onChange={(e) => setMessFilter(e.target.value)}>
            <option value="">{t("common.all")}</option>
            {(status.data || []).map((s) => <option key={s.mess.id} value={s.mess.id}>{s.mess.name}</option>)}
          </select>
        </label>
        <ErrorBanner error={alerts.error} onRetry={alerts.reload} />
        {alerts.data && alerts.data.length === 0 && <div className="banner info">{t("dash.noAlerts")}</div>}
        {alerts.data && alerts.data.length > 0 && (
          <table className="data-table responsive">
            <thead>
              <tr><th>{t("th.hall")}</th><th>{t("th.severity")}</th><th>{t("th.status")}</th><th>{t("th.reason")}</th><th>{t("th.raised")}</th></tr>
            </thead>
            <tbody>
              {alerts.data.map((a) => (
                <tr key={a.id}>
                  <td data-label={t("th.hall")}>{a.mess_name}</td>
                  <td data-label={t("th.severity")}><Severity level={a.level} /></td>
                  <td data-label={t("th.status")}><StatusPill status={a.status} /></td>
                  <td data-label={t("th.reason")}>{a.reason.replace(/'([^']+)'/, (_, c) => `'${tCategory(c)}'`)}</td>
                  <td data-label={t("th.raised")}><When value={a.created_at} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
