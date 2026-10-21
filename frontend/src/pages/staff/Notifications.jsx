import { useState } from "react";
import { Link } from "react-router-dom";
import { listNotifications, setupHealth } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { formatDateTime } from "../../lib/time";
import { ErrorBanner, Loading, Pager, useAsync, When } from "../../components/ui";

const STATUS = {
  sent: ["Sent", "ok-text"],
  skipped_no_contact: ["Not sent — no contact email", "warn-text"],
  skipped_no_smtp: ["Not sent — email not set up", "warn-text"],
  failed: ["Failed", "warn-text"],
};

export default function Notifications() {
  const { can } = useStaff();
  const health = useAsync(setupHealth, []);
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const list = useAsync(() => listNotifications({ status, offset, limit: 50 }), [status, offset]);

  return (
    <>
      <h3>Delivery health</h3>
      {!health.data ? <Loading /> : (
        <>
          <p>{health.data.smtp_configured ? <span className="ok-text">✓ Email sending is configured.</span>
            : <span className="warn-text">✗ Email isn't configured — nothing is being emailed. Set SMTP_EMAIL and SMTP_APP_PASSWORD on the server.</span>}</p>
          <ul className="plain-list">
            {health.data.colleges.map((c) => (
              <li key={c.college_id}>
                <strong>{c.college_name}</strong>:{" "}
                {c.missing_contacts.length ? <span className="warn-text">missing {c.missing_contacts.join(", ").replaceAll("_", " ")}</span> : <span className="ok-text">all contacts set</span>}
                {c.recent_failures > 0 && <span className="warn-text"> · {c.recent_failures} undelivered in the last 7 days</span>}
                {can("setup") && c.missing_contacts.length > 0 && <> · <Link to="/admin/setup">fix in Setup</Link></>}
              </li>
            ))}
          </ul>
          {health.data.jobs?.length > 0 && (
            <details>
              <summary>Background jobs</summary>
              <ul className="plain-list">
                {health.data.jobs.map((j) => <li key={j.job_name}><strong>{j.job_name}</strong> · last ran <When value={j.last_run_at} /> · {j.last_result}</li>)}
              </ul>
            </details>
          )}
        </>
      )}

      <h3>Every notification</h3>
      <label className="field inline-field"><span className="field-label">Show</span>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">All</option>
          {Object.entries(STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </label>
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.data?.items.length === 0 && <div className="banner info">Nothing yet.</div>}
      {list.data?.items.length > 0 && (
        <table className="data-table responsive">
          <thead><tr><th>When</th><th>What</th><th>To</th><th>Result</th></tr></thead>
          <tbody>
            {list.data.items.map((n) => (
              <tr key={n.id}>
                <td data-label="When">{formatDateTime(n.created_at)}</td>
                <td data-label="What">{n.subject || n.kind}{n.alert_id && <> · <Link to={`/admin/alerts?alert=${n.alert_id}`}>alert #{n.alert_id}</Link></>}</td>
                <td data-label="To">{n.recipient_role?.replace("_", " ")} {n.recipient_email && <span className="hint block">{n.recipient_email}</span>}</td>
                <td data-label="Result"><span className={STATUS[n.status]?.[1]}>{STATUS[n.status]?.[0] || n.status}</span>{n.error && <span className="hint block">{n.error}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.data && <Pager offset={offset} limit={50} total={list.data.total} onChange={setOffset} />}
    </>
  );
}
