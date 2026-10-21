import { useState } from "react";
import { addCompliance, complianceTypes, deleteCompliance, listCompliance } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { formatDate } from "../../lib/time";
import { ErrorBanner, Field, Loading, StaffPhoto, useAsync } from "../../components/ui";
import { ScopeFilters, useScope } from "./common";

function expiryLabel(d) {
  if (d.days_left == null) return <span className="hint">No expiry</span>;
  if (d.days_left < 0) return <span className="pill pill-dismissed">Expired {formatDate(d.expires_on)}</span>;
  if (d.days_left <= 30) return <span className="pill pill-fixed">Expires in {d.days_left} day(s)</span>;
  return <span className="hint">Valid until {formatDate(d.expires_on)}</span>;
}

function AddRecord({ scope, onAdded }) {
  const types = useAsync(complianceTypes, []);
  const { staff } = useStaff();
  const empty = { doc_type: "fssai_license", title: "", person_name: "", reference_no: "", issued_on: "", expires_on: "", notes: "", mess_id: staff.mess_id || "" };
  const [form, setForm] = useState(empty);
  const [scan, setScan] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const collegeId = scope.collegeId || scope.colleges.data?.[0]?.id;
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const personal = form.doc_type === "medical_certificate" || form.doc_type === "fostac_training";
  return (
    <form className="form-card" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        await addCompliance({ ...form, college_id: collegeId }, scan);
        setForm(empty);
        setScan(null);
        e.target.reset();
        onAdded();
      } catch (err) { setError(err); } finally { setBusy(false); }
    }}>
      <h3>Add a record</h3>
      <div className="filters-row">
        <label className="field inline-field"><span className="field-label">Type</span>
          <select value={form.doc_type} onChange={set("doc_type")}>
            {(types.data || []).map((t) => <option key={t.type} value={t.type}>{t.label}</option>)}
          </select>
        </label>
        {!staff.mess_id && (
          <label className="field inline-field"><span className="field-label">Mess hall</span>
            <select value={form.mess_id} onChange={set("mess_id")}>
              <option value="">Whole college</option>
              {(scope.halls.data || []).filter((h) => !collegeId || String(h.college_id) === String(collegeId)).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          </label>
        )}
      </div>
      <Field label="Title"><input required maxLength={255} value={form.title} onChange={set("title")} placeholder={personal ? "e.g. Medical fitness — cook" : "e.g. FSSAI licence 2026"} /></Field>
      {personal && <Field label="Person" optional><input value={form.person_name} onChange={set("person_name")} /></Field>}
      <div className="filters-row">
        <label className="field inline-field"><span className="field-label">Reference / certificate no.</span><input value={form.reference_no} onChange={set("reference_no")} /></label>
        <label className="field inline-field"><span className="field-label">Issued</span><input type="date" value={form.issued_on} onChange={set("issued_on")} /></label>
        <label className="field inline-field"><span className="field-label">Expires</span><input type="date" value={form.expires_on} onChange={set("expires_on")} /></label>
      </div>
      <Field label="Photo of the document" optional hint="Images only. Reminders go to the mess head and principal 30 days, 7 days and on the day it expires.">
        <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => setScan(e.target.files?.[0] || null)} />
      </Field>
      <ErrorBanner error={error} />
      <button type="submit" className="primary-btn" disabled={busy || !collegeId}>Save record</button>
    </form>
  );
}

export default function Compliance() {
  const scope = useScope();
  const { can } = useStaff();
  const [expiring, setExpiring] = useState(false);
  const list = useAsync(() => listCompliance({ college_id: scope.collegeId, mess_id: scope.messId, expiring_within_days: expiring ? 30 : undefined }),
    [scope.collegeId, scope.messId, expiring]);
  const [error, setError] = useState(null);
  const docs = list.data || [];
  const expired = docs.filter((d) => d.days_left != null && d.days_left < 0).length;
  const soon = docs.filter((d) => d.days_left != null && d.days_left >= 0 && d.days_left <= 30).length;

  return (
    <>
      <p className="hint">The records FSSAI checks: licence, food-handler medical certificates, FoSTaC training, water tests, pest control.</p>
      <ScopeFilters scope={scope}>
        <label className="checkbox-row"><input type="checkbox" checked={expiring} onChange={(e) => setExpiring(e.target.checked)} /> Only expired / expiring within 30 days</label>
      </ScopeFilters>
      {(expired > 0 || soon > 0) && <div className="banner warn">{expired} expired · {soon} expiring within 30 days</div>}
      {can("compliance_edit") && <AddRecord scope={scope} onAdded={list.reload} />}
      <ErrorBanner error={list.error || error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {docs.length === 0 && list.data && <div className="banner info">No records yet.</div>}
      {docs.map((d) => (
        <article key={d.id} className="report-card">
          <div className="report-card-head">
            <strong>{d.title}</strong>
            {expiryLabel(d)}
          </div>
          <p className="hint">
            {d.doc_type_label}{d.person_name ? ` · ${d.person_name}` : ""} · {d.mess_name || "Whole college"}{!scope.staff.college_id ? ` · ${d.college_name}` : ""}
            {d.reference_no ? ` · Ref ${d.reference_no}` : ""}{d.issued_on ? ` · issued ${formatDate(d.issued_on)}` : ""}
          </p>
          {d.file_url && <StaffPhoto url={d.file_url} alt={d.title} />}
          {can("compliance_edit") && (
            <button type="button" className="link-btn" onClick={async () => {
              if (!confirm(`Remove "${d.title}"?`)) return;
              try { await deleteCompliance(d.id); list.reload(); } catch (e) { setError(e); }
            }}>Remove</button>
          )}
        </article>
      ))}
    </>
  );
}
