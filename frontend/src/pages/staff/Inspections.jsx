import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  addInspectionPhoto, addSchedule, ApiError, deleteSchedule, downloadStaffFile, getChecklist, getInspection,
  inspectionOverview, listInspections, listStaff, searchComplaints, staffMessHalls, submitInspection,
} from "../../lib/api";
import { useStaff } from "../../lib/session";
import { daysFromToday, formatDate, formatDateTime } from "../../lib/time";
import { ErrorBanner, Field, Loading, Pager, Severity, StaffPhoto, useAsync, When } from "../../components/ui";
import QrScanner, { qrScanSupported } from "../../components/QrScanner";

const DRAFT_KEY = (messId) => `tt_inspection_draft_${messId}`;
const OUTBOX_KEY = "tt_inspection_outbox";

function readJson(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function writeJson(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch { /* storage full or blocked */ }
}
const newRef = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

// ---------------- To do ----------------

function ToDo() {
  const { can } = useStaff();
  const overview = useAsync(() => inspectionOverview(), []);
  const navigate = useNavigate();
  if (overview.error) return <ErrorBanner error={overview.error} onRetry={overview.reload} />;
  if (!overview.data) return <Loading />;
  return (
    <>
      <p className="hint">Halls are due every 30 days, or by the date an admin scheduled. Overdue first.</p>
      <table className="data-table responsive clickable">
        <thead><tr><th>Hall</th><th>Last inspected</th><th>Last score</th><th>Next due</th><th></th></tr></thead>
        <tbody>
          {overview.data.halls.map((h) => (
            <tr key={h.mess_id}>
              <td data-label="Hall">{h.mess_name}<span className="hint block">{h.college_name}</span></td>
              <td data-label="Last inspected">{h.last_inspected_at ? <When value={h.last_inspected_at} /> : <span className="warn-text">Never</span>}</td>
              <td data-label="Last score">{h.last_score != null ? `${h.last_score}%` : "—"}</td>
              <td data-label="Next due">
                <span className={h.overdue ? "warn-text" : ""}>
                  {h.never_inspected ? "Due now — never inspected" : `${formatDate(h.next_due)}${h.overdue ? " — overdue" : ""}`}
                </span>
                {h.assigned_to_me && <span className="pill pill-acknowledged block">assigned to you</span>}
              </td>
              <td>{can("inspect") && <button type="button" className="secondary-btn" onClick={() => navigate(`/admin/inspections/new?mess=${h.mess_id}`)}>Inspect</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ---------------- New inspection ----------------

function useOutbox() {
  const [outbox, setOutbox] = useState(() => readJson(OUTBOX_KEY, []));
  const save = (items) => { writeJson(OUTBOX_KEY, items.length ? items : null); setOutbox(items); };
  return [outbox, save];
}

function ItemRow({ item, answer, onChange, photo, onPhoto, missing }) {
  const result = answer?.result;
  return (
    <fieldset className={`check-item ${missing ? "missing" : ""} ${result || ""}`}>
      <legend>
        {item.text} {item.critical && <span className="crit-badge">Critical</span>}
      </legend>
      <div className="seg" role="radiogroup" aria-label={item.text}>
        {[["pass", "Pass"], ["fail", "Fail"], ["na", "N/A"]].map(([value, label]) => (
          <label key={value} className={`seg-btn ${result === value ? `on ${value}` : ""}`}>
            <input type="radio" name={item.item_key} value={value} checked={result === value}
              onChange={() => onChange({ ...answer, result: value })} />
            {label}
          </label>
        ))}
      </div>
      {result === "fail" && (
        <div className="fail-extra">
          <input aria-label={`What's wrong — ${item.text}`} placeholder="What's wrong? (shown to the mess head)" value={answer.note || ""}
            maxLength={500} onChange={(e) => onChange({ ...answer, note: e.target.value })} />
          <label className="file-inline">
            📷 {photo ? photo.name : "Add photo"}
            <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(e) => onPhoto(e.target.files?.[0] || null)} />
          </label>
        </div>
      )}
    </fieldset>
  );
}

function NewInspection() {
  const [params, setParams] = useSearchParams();
  const halls = useAsync(() => staffMessHalls(), []);
  const messId = params.get("mess") || "";
  const checklist = useAsync(() => (messId ? getChecklist({ mess_id: messId }) : null), [messId]);
  const recent = useAsync(() => (messId ? searchComplaints({ mess_id: messId, days: 30, limit: 10 }) : null), [messId]);

  const [draft, setDraft] = useState(null);
  const [photos, setPhotos] = useState({});
  const [scanning, setScanning] = useState(false);
  const [useLocation, setUseLocation] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [missing, setMissing] = useState([]);
  const [result, setResult] = useState(null);
  const [outbox, setOutbox] = useOutbox();

  // Restore (or start) the draft for this hall; it's saved as you go.
  useEffect(() => {
    if (!messId) return;
    setDraft(readJson(DRAFT_KEY(messId), null) || { answers: {}, kitchen_code: "", general_notes: "", client_ref: newRef() });
    setPhotos({});
    setResult(null);
    setMissing([]);
  }, [messId]);
  useEffect(() => { if (messId && draft) writeJson(DRAFT_KEY(messId), draft); }, [messId, draft]);

  const answered = useMemo(() => (checklist.data || []).filter((i) => draft?.answers[i.item_key]?.result).length, [checklist.data, draft]);
  const total = checklist.data?.length || 0;
  const hall = halls.data?.find((h) => String(h.id) === String(messId));

  const send = useCallback(async (payload, itemPhotos) => {
    const res = await submitInspection(payload);
    for (const [key, file] of Object.entries(itemPhotos || {})) {
      if (file) await addInspectionPhoto(res.inspection_id, key, file);
    }
    return res;
  }, []);

  // Retry anything saved while offline as soon as we're back online.
  const flushOutbox = useCallback(async () => {
    let remaining = readJson(OUTBOX_KEY, []);
    for (const item of [...remaining]) {
      try {
        await send(item.payload, {});
        remaining = remaining.filter((x) => x.payload.client_ref !== item.payload.client_ref);
      } catch (e) {
        if (!(e instanceof ApiError) || e.status === 0) break; // still offline
        remaining = remaining.filter((x) => x.payload.client_ref !== item.payload.client_ref);
      }
    }
    setOutbox(remaining);
  }, [send, setOutbox]);
  useEffect(() => {
    window.addEventListener("online", flushOutbox);
    return () => window.removeEventListener("online", flushOutbox);
  }, [flushOutbox]);

  const setAnswer = (key, value) => setDraft((d) => ({ ...d, answers: { ...d.answers, [key]: value } }));

  async function submit() {
    setError(null);
    const notAnswered = checklist.data.filter((i) => !draft.answers[i.item_key]?.result).map((i) => i.item_key);
    setMissing(notAnswered);
    if (notAnswered.length) {
      setError(`Answer every item — ${notAnswered.length} left. Use N/A for anything that doesn't apply.`);
      document.querySelector(".check-item.missing")?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setBusy(true);
    let coords = {};
    if (useLocation && navigator.geolocation) {
      coords = await new Promise((resolve) => navigator.geolocation.getCurrentPosition(
        (p) => resolve({ latitude: Number(p.coords.latitude.toFixed(6)), longitude: Number(p.coords.longitude.toFixed(6)) }),
        () => resolve({}), { timeout: 8000 },
      ));
    }
    const payload = {
      mess_id: Number(messId), responses: draft.answers, general_notes: draft.general_notes || null,
      kitchen_code: draft.kitchen_code || null, client_ref: draft.client_ref, ...coords,
    };
    try {
      const res = await send(payload, photos);
      writeJson(DRAFT_KEY(messId), null);
      setResult(res);
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) {
        // Offline: keep it and send it later. Same client_ref = no duplicate.
        setOutbox([...outbox.filter((x) => x.payload.client_ref !== payload.client_ref), { payload, hall: hall?.name, saved_at: new Date().toISOString() }]);
        writeJson(DRAFT_KEY(messId), null);
        setResult({ offline: true });
      } else {
        setError(e);
        if (e.detail?.missing) setMissing(e.detail.missing);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {outbox.length > 0 && (
        <div className="banner warn">
          {outbox.length} inspection(s) saved offline ({outbox.map((o) => o.hall).join(", ")}). They'll send automatically when you're back online.
          <button type="button" className="link-btn" onClick={flushOutbox} style={{ marginLeft: 8 }}>Send now</button>
          <p className="hint small">Photos attached to offline inspections can't be stored on the device — add them from History once sent.</p>
        </div>
      )}

      <Field label="Mess hall">
        <select value={messId} onChange={(e) => setParams({ mess: e.target.value })}>
          <option value="" disabled>Select a mess hall</option>
          {(halls.data || []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
        </select>
      </Field>

      {result && (
        result.offline ? (
          <div className="banner warn" role="status"><strong>No connection — inspection saved on this device.</strong> It will be sent automatically.</div>
        ) : (
          <div className={`banner ${result.level ? "warn" : "success"}`} role="status">
            <strong>Inspection recorded — {result.score}%.</strong>{" "}
            {result.level ? <>An alert was raised: <Severity level={result.level} />. {result.reason}</> : "No issues found, so no alert was raised."}
            <p className="hint">{result.verified_onsite ? "✓ Verified on site with the kitchen code." : "Not verified on site (no or wrong kitchen code)."}</p>
            <button type="button" className="link-btn" onClick={() => setParams({})}>Inspect another hall</button>
          </div>
        )
      )}

      {messId && !result && checklist.data && draft && (
        <div className="inspection-form">
          <section className="form-card">
            <h3>On-site check-in</h3>
            <p className="hint">Scan or type the code printed on the sign in this hall's kitchen. It proves the inspection was done on site.</p>
            <div className="filters-row">
              <label className="field inline-field"><span className="field-label">Kitchen code</span>
                <input value={draft.kitchen_code} maxLength={16} autoCapitalize="characters" onChange={(e) => setDraft({ ...draft, kitchen_code: e.target.value.toUpperCase() })} />
              </label>
              {qrScanSupported && <button type="button" className="secondary-btn" onClick={() => setScanning(true)}>📷 Scan QR</button>}
            </div>
            {scanning && <QrScanner onClose={() => setScanning(false)} onResult={(v) => { setDraft((d) => ({ ...d, kitchen_code: v.replace(/^TRAYTRACK-KITCHEN:/, "").toUpperCase() })); setScanning(false); }} />}
            <label className="checkbox-row"><input type="checkbox" checked={useLocation} onChange={(e) => setUseLocation(e.target.checked)} /> Attach my location to this inspection</label>
          </section>

          <p className="progress-text" aria-live="polite">{answered} of {total} answered</p>
          {checklist.data.map((item) => (
            <ItemRow key={item.item_key} item={item} answer={draft.answers[item.item_key]}
              missing={missing.includes(item.item_key)}
              onChange={(v) => { setAnswer(item.item_key, v); setMissing((m) => m.filter((k) => k !== item.item_key)); }}
              photo={photos[item.item_key]} onPhoto={(f) => setPhotos((p) => ({ ...p, [item.item_key]: f }))} />
          ))}

          <Field label="General notes" optional>
            <textarea rows={3} maxLength={2000} value={draft.general_notes} onChange={(e) => setDraft({ ...draft, general_notes: e.target.value })} />
          </Field>
          <ErrorBanner error={error} />
          <div className="button-row sticky-actions">
            <button type="button" className="primary-btn" disabled={busy} onClick={submit}>{busy ? "Submitting…" : `Submit inspection (${answered}/${total})`}</button>
            <button type="button" className="link-btn" onClick={() => { if (confirm("Discard this draft?")) { writeJson(DRAFT_KEY(messId), null); setDraft({ answers: {}, kitchen_code: "", general_notes: "", client_ref: newRef() }); setPhotos({}); } }}>Discard draft</button>
          </div>
          <p className="hint">Your answers are saved on this device as you go.</p>
        </div>
      )}

      {messId && recent.data?.items?.length > 0 && !result && (
        <section>
          <h3>What students reported here (last 30 days)</h3>
          {recent.data.items.map((c) => (
            <div key={c.id} className="report-card compact">
              <strong>{c.category}</strong> <span className="hint">· {c.meal}{c.dish ? ` · ${c.dish}` : ""} · <When value={c.created_at} /></span>
              {c.description && <p>{c.description}</p>}
            </div>
          ))}
        </section>
      )}
    </>
  );
}

// ---------------- History ----------------

function History() {
  const { can } = useStaff();
  const [offset, setOffset] = useState(0);
  const [mine, setMine] = useState(false);
  const list = useAsync(() => listInspections({ offset, limit: 25, mine: mine || undefined }), [offset, mine]);
  const navigate = useNavigate();
  return (
    <>
      <div className="filters-row">
        {can("inspect") && <label className="checkbox-row"><input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setOffset(0); }} /> Only mine</label>}
        {can("export") && <button type="button" className="secondary-btn" onClick={() => downloadStaffFile("/staff/export/inspections.csv", "inspections.csv")}>⬇ Export CSV</button>}
      </div>
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.loading && !list.data && <Loading />}
      {list.data?.items.length === 0 && <div className="banner info">No inspections yet.</div>}
      {list.data?.items.length > 0 && (
        <table className="data-table responsive clickable">
          <thead><tr><th>#</th><th>Hall</th><th>Inspector</th><th>Score</th><th>Failed</th><th>When</th></tr></thead>
          <tbody>
            {list.data.items.map((i) => (
              <tr key={i.id} tabIndex={0} onClick={() => navigate(`/admin/inspections/history/${i.id}`)} onKeyDown={(e) => e.key === "Enter" && navigate(`/admin/inspections/history/${i.id}`)}>
                <td data-label="#">{i.id}</td>
                <td data-label="Hall">{i.mess_name}</td>
                <td data-label="Inspector">{i.inspector_name}{i.verified_onsite ? " ✓" : ""}</td>
                <td data-label="Score">{i.score}%</td>
                <td data-label="Failed">{i.summary.failed_items.length}{i.summary.failed_items.some((f) => f.critical) && <span className="crit-badge">critical</span>}</td>
                <td data-label="When"><When value={i.created_at} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.data && <Pager offset={offset} limit={25} total={list.data.total} onChange={setOffset} />}
    </>
  );
}

function InspectionDetail() {
  const { id } = useParams();
  const { staff } = useStaff();
  const insp = useAsync(() => getInspection(id), [id]);
  const [error, setError] = useState(null);
  const navigate = useNavigate();
  if (insp.error) return <ErrorBanner error={insp.error} />;
  if (!insp.data) return <Loading />;
  const d = insp.data;
  const canAddPhotos = d.inspector_id === staff.id || staff.role === "admin";
  return (
    <div className="detail">
      <button type="button" className="link-btn" onClick={() => navigate("/admin/inspections/history")}>← History</button>
      <h2>Inspection #{d.id} · {d.mess_name}</h2>
      <p>{d.inspector_name} · {formatDateTime(d.created_at)} · {d.score}% · {d.verified_onsite ? "✓ verified on site" : "not verified on site"}
        {d.latitude != null && <> · <a href={`https://www.openstreetmap.org/?mlat=${d.latitude}&mlon=${d.longitude}#map=18/${d.latitude}/${d.longitude}`} target="_blank" rel="noreferrer">location</a></>}</p>
      {d.general_notes && <p>{d.general_notes}</p>}
      <ul className="check-results">
        {Object.entries(d.responses).map(([key, r]) => (
          <li key={key} className={r.result}>
            <span className="result-tag">{r.result === "na" ? "N/A" : r.result.toUpperCase()}</span> {r.text}
            {r.critical && <span className="crit-badge">Critical</span>}
            {r.note && <span className="hint block">{r.note}</span>}
            {d.photos.filter((p) => p.item_key === key).map((p) => <StaffPhoto key={p.id} url={p.photo_url} />)}
          </li>
        ))}
      </ul>
      {d.photos.filter((p) => !p.item_key).map((p) => <StaffPhoto key={p.id} url={p.photo_url} />)}
      {canAddPhotos && (
        <label className="file-inline">📷 Add a photo
          <input type="file" accept="image/jpeg,image/png,image/webp" onChange={async (e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            try { await addInspectionPhoto(d.id, null, f); insp.reload(); } catch (err) { setError(err); }
          }} />
        </label>
      )}
      <ErrorBanner error={error} />
    </div>
  );
}

// ---------------- Schedule ----------------

function Schedule() {
  const { can } = useStaff();
  const overview = useAsync(() => inspectionOverview(), []);
  const inspectors = useAsync(() => listStaff("inspector"), []);
  const [form, setForm] = useState({ mess_id: "", due_date: daysFromToday(7), assigned_staff_id: "", notes: "" });
  const [error, setError] = useState(null);
  if (!overview.data) return <Loading />;
  return (
    <>
      {can("schedule") && (
        <form className="form-card" onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            await addSchedule({ ...form, mess_id: Number(form.mess_id), assigned_staff_id: form.assigned_staff_id ? Number(form.assigned_staff_id) : null });
            setForm({ ...form, notes: "" });
            overview.reload();
          } catch (err) { setError(err); }
        }}>
          <h3>Schedule an inspection</h3>
          <div className="filters-row">
            <label className="field inline-field"><span className="field-label">Hall</span>
              <select required value={form.mess_id} onChange={(e) => setForm({ ...form, mess_id: e.target.value })}>
                <option value="" disabled>Choose</option>
                {overview.data.halls.map((h) => <option key={h.mess_id} value={h.mess_id}>{h.mess_name} ({h.college_name})</option>)}
              </select>
            </label>
            <label className="field inline-field"><span className="field-label">Due by</span>
              <input type="date" required value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
            </label>
            <label className="field inline-field"><span className="field-label">Inspector</span>
              <select value={form.assigned_staff_id} onChange={(e) => setForm({ ...form, assigned_staff_id: e.target.value })}>
                <option value="">Anyone</option>
                {(inspectors.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
          </div>
          <Field label="Note for the inspector" optional><input value={form.notes} maxLength={500} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
          <p className="hint">For a surprise inspection, don't share the date with the mess team — only inspectors and admins see this schedule.</p>
          <ErrorBanner error={error} />
          <button type="submit" className="primary-btn">Add to schedule</button>
        </form>
      )}
      <h3>Upcoming</h3>
      {overview.data.schedule.length === 0 ? <p className="hint">Nothing scheduled.</p> : (
        <table className="data-table responsive">
          <thead><tr><th>Hall</th><th>Due</th><th>Inspector</th><th>Note</th><th></th></tr></thead>
          <tbody>
            {overview.data.schedule.map((s) => (
              <tr key={s.id}>
                <td data-label="Hall">{s.mess_name}</td>
                <td data-label="Due">{formatDate(s.due_date)}</td>
                <td data-label="Inspector">{s.assigned_name || "Anyone"}</td>
                <td data-label="Note">{s.notes || "—"}</td>
                <td>{can("schedule") && <button type="button" className="link-btn" onClick={async () => { try { await deleteSchedule(s.id); overview.reload(); } catch (e) { setError(e); } }}>Remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

export default function Inspections() {
  const { can } = useStaff();
  const sub = [["", "To do", true], ["new", "New inspection", can("inspect")], ["history", "History", true], ["schedule", "Schedule", true]]
    .filter(([, , show]) => show);
  return (
    <>
      <nav className="sub-tabs" aria-label="Inspections">
        {sub.map(([path, label]) => (
          <NavLink key={path} end to={`/admin/inspections${path ? `/${path}` : ""}`} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<ToDo />} />
        <Route path="new" element={<NewInspection />} />
        <Route path="history" element={<History />} />
        <Route path="history/:id" element={<InspectionDetail />} />
        <Route path="schedule" element={<Schedule />} />
      </Routes>
    </>
  );
}
