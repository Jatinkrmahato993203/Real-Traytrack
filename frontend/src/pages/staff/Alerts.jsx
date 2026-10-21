import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  addEvidence, alertAction, assignAlert, downloadStaffFile, getAlertDetail, listInspections, listStaff,
  onNewActivity, reopenAlert, searchAlerts,
} from "../../lib/api";
import { useStaff } from "../../lib/session";
import { formatDate, formatDateTime } from "../../lib/time";
import { ErrorBanner, Field, Loading, Pager, Severity, StaffPhoto, StatusPill, useAsync, When } from "../../components/ui";
import { ScopeFilters, useScope } from "./common";

const ACTION_LABEL = {
  acknowledge: ["Acknowledge", "We've seen it and are looking into it."],
  start: ["Start work", "Work on the fix has begun."],
  mark_fixed: ["Mark fixed", "Needs proof first (a photo or a follow-up inspection) and a note on what was done."],
  reject_fix: ["Reject fix", "The fix didn't hold up — send it back with a note."],
  verify: ["Verify & close", "You've checked the fix yourself. This closes the alert."],
};
const NOTE_REQUIRED = new Set(["mark_fixed", "reject_fix", "verify"]);
const EVENT_LABEL = {
  created: "Raised", escalated: "Escalated", acknowledged: "Acknowledged", in_progress: "Work started",
  fixed: "Marked fixed", fix_rejected: "Fix rejected", resolved: "Resolved", reopened: "Reopened",
  assigned: "Assigned", reminder: "Reminder sent",
};

function AlertList({ onOpen }) {
  const scope = useScope();
  const { can } = useStaff();
  const [status, setStatus] = useState("active");
  const [level, setLevel] = useState("");
  const [offset, setOffset] = useState(0);
  const list = useAsync(
    () => searchAlerts({ college_id: scope.collegeId, mess_id: scope.messId, status: status === "all" ? "" : status, level, offset, limit: 25 }),
    [scope.collegeId, scope.messId, status, level, offset],
  );

  useEffect(() => setOffset(0), [scope.collegeId, scope.messId, status, level]);
  // Refresh when any alert changes anywhere.
  useEffect(() => onNewActivity({
    collegeId: scope.collegeId, messId: scope.messId,
    onEvent: (row) => row.event_type.startsWith("alert_") && list.reload(),
  }), [scope.collegeId, scope.messId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <ScopeFilters scope={scope}>
        <label className="field inline-field"><span className="field-label">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="active">Not resolved</option>
            <option value="open">Open (untouched)</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="in_progress">In progress</option>
            <option value="fixed">Fixed — awaiting verification</option>
            <option value="resolved">Resolved</option>
            <option value="all">All</option>
          </select>
        </label>
        <label className="field inline-field"><span className="field-label">Severity</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">Any</option><option>High</option><option>Medium</option><option>Low</option>
          </select>
        </label>
        {can("export") && (
          <button type="button" className="secondary-btn" onClick={() => downloadStaffFile(`/staff/export/alerts.csv${scope.collegeId ? `?college_id=${scope.collegeId}` : ""}`, "alerts.csv")}>
            ⬇ Export CSV
          </button>
        )}
      </ScopeFilters>
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data?.items.length === 0 && <div className="banner info">No alerts match these filters.</div>}
      {list.data?.items.length > 0 && (
        <table className="data-table responsive clickable">
          <thead><tr><th>#</th><th>Hall</th><th>Severity</th><th>Status</th><th>Owner / due</th><th>Raised</th></tr></thead>
          <tbody>
            {list.data.items.map((a) => (
              <tr key={a.id} onClick={() => onOpen(a.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen(a.id)}>
                <td data-label="#">{a.id}</td>
                <td data-label="Hall">{a.mess_name}{!scope.staff.college_id && <span className="hint block">{a.college_name}</span>}</td>
                <td data-label="Severity"><Severity level={a.level} /></td>
                <td data-label="Status"><StatusPill status={a.status} />{!a.authority_notified && !a.resolved && <span className="warn-text block small">not notified</span>}</td>
                <td data-label="Owner / due">
                  {a.owner_name || <span className="hint">unassigned</span>}
                  {a.due_date && <span className={`block small ${a.overdue ? "warn-text" : "hint"}`}>due {formatDate(a.due_date)}{a.overdue ? " — overdue" : ""}</span>}
                </td>
                <td data-label="Raised"><When value={a.created_at} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.data && <Pager offset={offset} limit={25} total={list.data.total} onChange={setOffset} />}
    </>
  );
}

function AlertDetail({ id, onBack }) {
  const { staff } = useStaff();
  const detail = useAsync(() => getAlertDetail(id), [id]);
  const owners = useAsync(() => listStaff("mess_head").then(async (heads) => [
    ...heads, ...(await listStaff("principal")), ...(await listStaff("admin")),
  ]), []);
  const inspections = useAsync(() => (detail.data ? listInspections({ mess_id: detail.data.alert.mess_id, limit: 10 }) : null), [detail.data?.alert.mess_id]);
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [evNote, setEvNote] = useState("");
  const [evPhoto, setEvPhoto] = useState(null);
  const [evInspection, setEvInspection] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");

  useEffect(() => {
    if (detail.data) {
      setOwner(detail.data.alert.owner_staff_id ? String(detail.data.alert.owner_staff_id) : "");
      setDue(detail.data.alert.due_date || "");
    }
  }, [detail.data]);

  async function run(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setNote("");
      detail.reload();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (detail.error) return <ErrorBanner error={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return <Loading />;
  const { alert: a, source, history, evidence, notifications, allowed_actions, can_reopen, can_assign } = detail.data;

  return (
    <div className="detail">
      <button type="button" className="link-btn" onClick={onBack}>← All alerts</button>
      <h2>Alert #{a.id} · {a.mess_name}</h2>
      <p><Severity level={a.level} /> · <StatusPill status={a.status} /> · raised {formatDateTime(a.created_at)}{a.reopened_count ? ` · reopened ${a.reopened_count}×` : ""}</p>
      <p>{a.reason}</p>
      {!a.authority_notified && !a.resolved && (
        <div className="banner warn">No notification for this alert has been delivered. Check <Link to="/admin/notifications">Notifications</Link> for missing contacts or email setup.</div>
      )}

      {source && (
        <section className="form-card">
          <h3>What raised it</h3>
          {source.inspection_id ? (
            <>
              <p className="hint">Inspection #{source.inspection_id} by {source.inspector_name} · {source.score}%</p>
              <ul className="failed-list">{source.failed.map((f) => <li key={f.text}>{f.critical && <strong>Critical: </strong>}{f.text}{f.note && <span className="hint"> — {f.note}</span>}</li>)}</ul>
            </>
          ) : (
            <>
              <p className="hint">Latest report: {source.category}{source.meal ? ` · ${source.meal}` : ""}{source.dish ? ` · ${source.dish}` : ""} · {source.reporter}</p>
              {source.description && <p>{source.description}</p>}
              {source.photo_url && <StaffPhoto url={source.photo_url} />}
            </>
          )}
        </section>
      )}

      {(allowed_actions.length > 0 || can_reopen) && (
        <section className="form-card">
          <h3>Next step</h3>
          <Field label="Note" hint="Recorded in the alert's history (and shown to the next person).">
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="button-row">
            {allowed_actions.map((action) => (
              <button key={action} type="button" className={action === "verify" ? "primary-btn" : "secondary-btn"} disabled={busy || (NOTE_REQUIRED.has(action) && !note.trim())}
                title={ACTION_LABEL[action][1]} onClick={() => run(() => alertAction(a.id, action, note))}>
                {ACTION_LABEL[action][0]}
              </button>
            ))}
            {can_reopen && (
              <button type="button" className="danger-btn" disabled={busy || !note.trim()} onClick={() => run(() => reopenAlert(a.id, note))}>Reopen</button>
            )}
          </div>
          <ul className="hint small">{allowed_actions.map((x) => <li key={x}><strong>{ACTION_LABEL[x][0]}:</strong> {ACTION_LABEL[x][1]}</li>)}</ul>
          <ErrorBanner error={error} />
        </section>
      )}

      {can_assign && (
        <section className="form-card">
          <h3>Owner & due date</h3>
          <div className="filters-row">
            <label className="field inline-field"><span className="field-label">Owner</span>
              <select value={owner} onChange={(e) => setOwner(e.target.value)}>
                <option value="">Unassigned</option>
                {(owners.data || []).filter((p) => !p.college_id || p.college_id === a.college_id).map((p) => (
                  <option key={p.id} value={p.id}>{p.name} ({p.role.replace("_", " ")})</option>
                ))}
              </select>
            </label>
            <label className="field inline-field"><span className="field-label">Due</span>
              <input type="date" value={due || ""} onChange={(e) => setDue(e.target.value)} />
            </label>
            <button type="button" className="secondary-btn" disabled={busy} onClick={() => run(() => assignAlert(a.id, owner ? Number(owner) : null, due || null))}>Save</button>
          </div>
          <p className="hint">If work is in progress past the due date, the alert escalates.</p>
        </section>
      )}

      {can_assign && (
        <section className="form-card">
          <h3>Add proof of the fix</h3>
          <Field label="Photo" optional><input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(e) => setEvPhoto(e.target.files?.[0] || null)} /></Field>
          <Field label="Or link a follow-up inspection" optional>
            <select value={evInspection} onChange={(e) => setEvInspection(e.target.value)}>
              <option value="">—</option>
              {(inspections.data?.items || []).map((i) => <option key={i.id} value={i.id}>#{i.id} · {formatDate(i.created_at)} · {i.inspector_name} · {i.score}%</option>)}
            </select>
          </Field>
          <Field label="Note" optional><input value={evNote} onChange={(e) => setEvNote(e.target.value)} /></Field>
          <button type="button" className="secondary-btn" disabled={busy || (!evPhoto && !evInspection && !evNote.trim())}
            onClick={() => run(async () => { await addEvidence(a.id, { note: evNote, inspectionId: evInspection, photo: evPhoto }); setEvNote(""); setEvPhoto(null); setEvInspection(""); })}>
            Add evidence
          </button>
        </section>
      )}

      {evidence.length > 0 && (
        <section>
          <h3>Evidence</h3>
          {evidence.map((e) => (
            <div key={e.id} className="report-card">
              <p className="hint">{e.kind} · {e.staff_name} · {formatDateTime(e.created_at)}{e.inspection_id ? ` · inspection #${e.inspection_id}` : ""}</p>
              {e.note && <p>{e.note}</p>}
              {e.photo_url && <StaffPhoto url={e.photo_url} />}
            </div>
          ))}
        </section>
      )}

      <section>
        <h3>History</h3>
        <ol className="timeline">
          {history.map((h) => (
            <li key={h.id}>
              <strong>{EVENT_LABEL[h.event] || h.event}</strong> · <Severity level={h.level} /> · {formatDateTime(h.timestamp)}
              {h.actor_name && <span className="hint"> · {h.actor_name}</span>}
              {h.note && <p className="hint">{h.note}</p>}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h3>Notifications</h3>
        {notifications.length === 0 ? <p className="hint">None yet.</p> : (
          <ul className="plain-list">
            {notifications.map((n) => (
              <li key={n.id}>
                <span className={n.status === "sent" ? "ok-text" : "warn-text"}>{n.status.replaceAll("_", " ")}</span> · {n.recipient_role?.replace("_", " ")} {n.recipient_email && `(${n.recipient_email})`} · {formatDateTime(n.created_at)}
              </li>
            ))}
          </ul>
        )}
      </section>
      {staff.role === "auditor" && <p className="hint">Read-only access.</p>}
    </div>
  );
}

export default function Alerts() {
  const [params, setParams] = useSearchParams();
  const open = params.get("alert");
  return open
    ? <AlertDetail id={open} onBack={() => setParams({})} />
    : <AlertList onOpen={(id) => setParams({ alert: id })} />;
}
