import { useEffect, useState } from "react";
import { downloadStaffFile, getCategories, getMeals, hideComplaint, onNewActivity, respondToComplaint, searchComplaints } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { formatDateTime } from "../../lib/time";
import { ErrorBanner, Loading, Pager, StaffPhoto, useAsync, When } from "../../components/ui";
import { COMPLAINT_STATUS_LABEL, ScopeFilters, useScope } from "./common";

const PAGE = 25;

function Reply({ c, onDone }) {
  const [status, setStatus] = useState(c.status === "received" ? "acknowledged" : c.status);
  const [text, setText] = useState(c.staff_response || "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const needsText = status === "action_taken" || status === "dismissed";
  return (
    <div className="reply-box">
      <div className="filters-row">
        <label className="field inline-field"><span className="field-label">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["acknowledged", "action_taken", "closed", "dismissed"].map((s) => <option key={s} value={s}>{COMPLAINT_STATUS_LABEL[s]}</option>)}
          </select>
        </label>
      </div>
      <label className="field">
        <span className="field-label">Reply to the student {needsText ? "" : <span className="hint">(optional)</span>}</span>
        <textarea rows={2} value={text} maxLength={2000} onChange={(e) => setText(e.target.value)}
          placeholder={status === "dismissed" ? "Why it was dismissed" : "What was done about it"} />
      </label>
      <ErrorBanner error={error} />
      <button type="button" className="secondary-btn" disabled={busy || (needsText && !text.trim())} onClick={async () => {
        setBusy(true);
        setError(null);
        try { await respondToComplaint(c.id, status, text); onDone(); } catch (e) { setError(e); } finally { setBusy(false); }
      }}>Save reply</button>
    </div>
  );
}

export default function Complaints() {
  const scope = useScope();
  const { can } = useStaff();
  const categories = useAsync(getCategories, []);
  const meals = useAsync(getMeals, []);
  const [filters, setFilters] = useState({ q: "", category: "", status: "", meal: "", days: "30" });
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [openReply, setOpenReply] = useState(null);
  const list = useAsync(
    () => searchComplaints({ college_id: scope.collegeId, mess_id: scope.messId, ...filters, q: query, offset, limit: PAGE }),
    [scope.collegeId, scope.messId, filters.category, filters.status, filters.meal, filters.days, query, offset],
  );
  const set = (k) => (e) => { setFilters({ ...filters, [k]: e.target.value }); setOffset(0); };

  useEffect(() => onNewActivity({
    collegeId: scope.collegeId, messId: scope.messId,
    onEvent: (row) => row.event_type === "complaint_submitted" && offset === 0 && list.reload(),
  }), [scope.collegeId, scope.messId, offset]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <p className="hint">Every complaint students have filed — including ones that haven't (yet) formed an alert.</p>
      <ScopeFilters scope={scope}>
        <form className="search-form" onSubmit={(e) => { e.preventDefault(); setQuery(filters.q.trim()); setOffset(0); }} role="search">
          <label className="field inline-field"><span className="field-label">Search text / dish</span>
            <input type="search" value={filters.q} onChange={set("q")} placeholder="e.g. rajma, cockroach" />
          </label>
        </form>
        <label className="field inline-field"><span className="field-label">Category</span>
          <select value={filters.category} onChange={set("category")}>
            <option value="">All</option>
            {(categories.data || []).map((c) => <option key={c.name}>{c.name}</option>)}
          </select>
        </label>
        <label className="field inline-field"><span className="field-label">Meal</span>
          <select value={filters.meal} onChange={set("meal")}>
            <option value="">All</option>
            {(meals.data || []).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <label className="field inline-field"><span className="field-label">Status</span>
          <select value={filters.status} onChange={set("status")}>
            <option value="">All</option>
            {Object.entries(COMPLAINT_STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="field inline-field"><span className="field-label">Period</span>
          <select value={filters.days} onChange={set("days")}>
            <option value="7">Last 7 days</option><option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option><option value="0">All time</option>
          </select>
        </label>
        {can("export") && (
          <button type="button" className="secondary-btn" onClick={() => downloadStaffFile(
            `/staff/export/complaints.csv?days=${filters.days || 0}${scope.collegeId ? `&college_id=${scope.collegeId}` : ""}${scope.messId ? `&mess_id=${scope.messId}` : ""}`,
            "complaints.csv")}>⬇ Export CSV</button>
        )}
      </ScopeFilters>

      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data && <p className="hint">{list.data.total} complaint(s). Reporter emails are masked; anonymous reports show no identity.</p>}
      {list.data?.items.map((c) => (
        <article key={c.id} className="report-card">
          <div className="report-card-head">
            <strong>#{c.id} · {c.mess_name} · {c.category}</strong>
            <When value={c.created_at} />
          </div>
          <p className="hint">
            {c.meal}{c.dish ? ` · ${c.dish}` : ""} · {c.reporter}{!scope.staff.college_id ? ` · ${c.college_name}` : ""} ·{" "}
            <span className={`pill pill-${c.status}`}>{COMPLAINT_STATUS_LABEL[c.status]}</span>
          </p>
          {c.description && <p>{c.description}</p>}
          {c.hidden_reason && <p className="hint">Text hidden by staff: {c.hidden_reason}</p>}
          {c.photo_url && <StaffPhoto url={c.photo_url} />}
          {c.staff_response && <p className="response"><strong>Reply:</strong> {c.staff_response} <span className="hint">({formatDateTime(c.responded_at)})</span></p>}
          {can("alert_verify") && c.description && (
            <button type="button" className="link-btn danger" style={{ marginRight: 14 }} onClick={async () => {
              const reason = prompt("Hide this complaint's text? Use for abuse or text that names/identifies someone. Reason:");
              if (!reason?.trim()) return;
              try { await hideComplaint(c.id, reason.trim()); list.reload(); } catch (e) { alert(e.message); }
            }}>Hide text</button>
          )}
          {can("respond") && (openReply === c.id
            ? <Reply c={c} onDone={() => { setOpenReply(null); list.reload(); }} />
            : <button type="button" className="link-btn" onClick={() => setOpenReply(c.id)}>{c.staff_response ? "Update reply" : "Reply / update status"}</button>)}
        </article>
      ))}
      {list.data && <Pager offset={offset} limit={PAGE} total={list.data.total} onChange={setOffset} />}
    </>
  );
}
