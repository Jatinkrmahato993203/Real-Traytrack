import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { addInspectionPhoto, ApiError, getChecklist, searchComplaints, staffMessHalls, submitInspection } from "../../../lib/api";
import { ErrorBanner, Field, Severity, useAsync, When } from "../../../components/ui";
import QrScanner, { qrScanSupported } from "../../../components/QrScanner";
import { DRAFT_KEY, newRef, OUTBOX_KEY, readJson, writeJson } from "./storage";

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

export default function NewInspection() {
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
