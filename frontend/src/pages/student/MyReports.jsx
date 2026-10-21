import { useState } from "react";
import { downloadStudentData, eraseMyData, getMyComplaints, voteFixed } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { useStudent } from "../../lib/session";
import { formatDateTime, parseUtc } from "../../lib/time";
import { EmptyState, ErrorBanner, Loading, Severity, StatusPill, useAsync, When } from "../../components/ui";
import StudentGate from "./StudentGate";

const VOTE_AFTER_HOURS = 48;
const STEPS = ["received", "acknowledged", "action_taken", "closed"];

function hoursUntilVote(lastEscalatedAt) {
  const since = parseUtc(lastEscalatedAt);
  if (!since) return 0;
  return Math.max(0, Math.ceil((since.getTime() + VOTE_AFTER_HOURS * 3600e3 - Date.now()) / 3600e3));
}

// received → seen → action taken → closed, so students can see their report
// is moving instead of disappearing into a void.
function Progress({ status }) {
  const { t } = useI18n();
  if (status === "dismissed") return <StatusPill status="dismissed" prefix="my.status" />;
  const at = STEPS.indexOf(status);
  return (
    <ol className="progress" aria-label={t(`my.status.${status}`)}>
      {STEPS.map((s, i) => (
        <li key={s} className={i <= at ? "done" : ""} aria-current={i === at ? "step" : undefined}>
          {t(`my.status.${s}`)}
        </li>
      ))}
    </ol>
  );
}

function ReportCard({ c, onVoted }) {
  const { t, tCategory } = useI18n();
  const [error, setError] = useState(null);
  const a = c.alert;
  const wait = a ? hoursUntilVote(a.last_escalated_at) : 0;
  return (
    <article className="report-card">
      <div className="report-card-head">
        <strong>{c.mess_name} · {tCategory(c.category)}</strong>
        <When value={c.created_at} />
      </div>
      <p className="hint">
        {c.meal && t(`meal.${c.meal}`)}{c.dish && ` · ${c.dish}`}{c.anonymous && ` · ${t("my.anon")}`}
      </p>
      {c.description && <p>{c.description}</p>}
      <Progress status={c.status} />
      {c.staff_response ? (
        <div className="response">
          <strong>{t("my.response")}</strong> <span className="hint">({formatDateTime(c.responded_at)})</span>
          <p>{c.staff_response}</p>
        </div>
      ) : c.status === "received" && <p className="hint">{t("my.waiting")}</p>}

      {a && !a.resolved && (
        <div className="banner info">
          <strong><Severity level={a.level} /> {t("my.partOfAlert", { level: t(`level.${a.level}`) })}</strong> · <StatusPill status={a.status} />
          <p className="hint">{t("my.votes", { v: a.resolve_votes, n: a.resolve_votes_needed })}</p>
          {a.you_voted ? (
            <p className="hint">{t("my.voted")}</p>
          ) : wait === 0 ? (
            <button type="button" className="secondary-btn" onClick={async () => {
              setError(null);
              try { await voteFixed(a.id); onVoted(); } catch (e) { setError(e); }
            }}>
              ✓ {t("my.voteFixed")}
            </button>
          ) : (
            <p className="hint">{t("my.voteWait", { h: wait })}</p>
          )}
          <ErrorBanner error={error} />
        </div>
      )}
      {a && !!a.resolved && (
        <div className="banner success">{t("my.resolvedOn", { when: formatDateTime(a.resolved_at) })}</div>
      )}
    </article>
  );
}

function YourData() {
  const { t } = useI18n();
  const { refreshMe } = useStudent();
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  return (
    <section className="form-card">
      <h2 className="h3">{t("my.dataTitle")}</h2>
      <p className="hint">{t("my.dataText")}</p>
      <ErrorBanner error={error} />
      {done && <div className="banner success">{t("my.deleted")}</div>}
      <div className="button-row">
        <button type="button" className="secondary-btn" onClick={() => downloadStudentData().catch(setError)}>
          {t("my.download")}
        </button>
        <button type="button" className="danger-btn" onClick={async () => {
          if (!window.confirm(t("my.deleteConfirm"))) return;
          try {
            await eraseMyData();
            setDone(true);
            refreshMe();
          } catch (e) {
            setError(e);
          }
        }}>
          {t("my.delete")}
        </button>
      </div>
    </section>
  );
}

function MyReportsList() {
  const { t } = useI18n();
  const reports = useAsync(getMyComplaints, []);
  return (
    <div className="content">
      <h1>{t("my.title")}</h1>
      <p className="subtitle">{t("my.subtitle")}</p>
      <ErrorBanner error={reports.error} onRetry={reports.reload} />
      {reports.loading && !reports.data && <Loading />}
      {reports.data?.length === 0 && <EmptyState>{t("my.none")}</EmptyState>}
      {(reports.data || []).map((c) => <ReportCard key={c.id} c={c} onVoted={reports.reload} />)}
      <YourData />
    </div>
  );
}

export default function MyReports() {
  return <StudentGate requireCollege={false}><MyReportsList /></StudentGate>;
}
