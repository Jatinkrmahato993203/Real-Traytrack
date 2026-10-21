import { useEffect, useState } from "react";
import QRCode from "qrcode";
import {
  addChecklistItem, addCollege, addMessHall, deleteCollege, deleteMessHall, getChecklist, getCollegeSettings,
  newKitchenCode, setupHealth, staffColleges, staffMessHalls, updateChecklistItem, updateCollegeSettings,
  updateContacts, updateMessHall,
} from "../../lib/api";
import { useStaff } from "../../lib/session";
import { ErrorBanner, Loading, useAsync } from "../../components/ui";

function Qr({ value, label, size = 160 }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    QRCode.toDataURL(value, { width: size, margin: 1, errorCorrectionLevel: "M" }).then(setSrc).catch(() => setSrc(null));
  }, [value, size]);
  return src ? <img src={src} width={size} height={size} alt={`QR code: ${label}`} /> : null;
}

// A printable sheet: student QR for the dining tables, kitchen code for the
// kitchen wall. Uses the browser's print dialog (save as PDF works too).
function PrintSheet({ hall, onClose }) {
  return (
    <div className="print-sheet" role="dialog" aria-label={`Print QR codes for ${hall.name}`}>
      <div className="no-print button-row">
        <button type="button" className="primary-btn" onClick={() => window.print()}>Print</button>
        <button type="button" className="secondary-btn" onClick={onClose}>Close</button>
      </div>
      <section className="print-card">
        <h2>{hall.name}</h2>
        <p className="print-big">Food problem? Scan to report it.</p>
        <Qr value={hall.report_url} label="report a problem" size={260} />
        <p>Takes under a minute · your identity is never shown publicly</p>
        <p className="print-url">{hall.report_url}</p>
        <hr />
        <p className="print-big">Rate today's meal</p>
        <Qr value={hall.rate_url} label="rate a meal" size={180} />
      </section>
      {hall.kitchen_code && (
        <section className="print-card page-break">
          <h2>{hall.name} — Kitchen</h2>
          <p>For TrayTrack inspectors only. Scan or enter this code during an inspection.</p>
          <Qr value={`TRAYTRACK-KITCHEN:${hall.kitchen_code}`} label="kitchen code" size={220} />
          <p className="kitchen-code">{hall.kitchen_code}</p>
          <p className="hint">Display inside the kitchen only. If it's shared outside, issue a new code in Setup.</p>
        </section>
      )}
    </div>
  );
}

function Halls({ college, onChanged }) {
  const halls = useAsync(() => staffMessHalls(college.id), [college.id]);
  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("");
  const [error, setError] = useState(null);
  const [printing, setPrinting] = useState(null);
  const run = async (fn) => { setError(null); try { await fn(); halls.reload(); onChanged?.(); } catch (e) { setError(e); } };

  if (printing) return <PrintSheet hall={printing} onClose={() => setPrinting(null)} />;
  return (
    <>
      {(halls.data || []).map((h) => (
        <div key={h.id} className="hall-row">
          <div>
            <strong>{h.name}</strong>
            <span className="hint block">Capacity: {h.capacity || "not set (uses default alert thresholds)"} · Kitchen code: <code>{h.kitchen_code}</code></span>
          </div>
          <div className="button-row">
            <button type="button" className="secondary-btn" onClick={() => setPrinting(h)}>QR codes</button>
            <button type="button" className="link-btn" onClick={() => {
              const v = prompt(`Diners at ${h.name} (used to scale alert thresholds). Leave empty to clear.`, h.capacity || "");
              if (v === null) return;
              run(() => updateMessHall(h.id, v.trim() ? { capacity: Number(v) } : { clear_capacity: true }));
            }}>Capacity</button>
            <button type="button" className="link-btn" onClick={() => confirm("Issue a new kitchen code? The printed one stops working.") && run(() => newKitchenCode(h.id))}>New kitchen code</button>
            <button type="button" className="link-btn danger" onClick={() => confirm(`Delete ${h.name}?`) && run(() => deleteMessHall(h.id))}>Delete</button>
          </div>
        </div>
      ))}
      <form className="inline-form" onSubmit={(e) => {
        e.preventDefault();
        run(async () => { await addMessHall({ college_id: college.id, name, capacity: capacity ? Number(capacity) : null }); setName(""); setCapacity(""); });
      }}>
        <label className="field inline-field"><span className="field-label">New mess hall</span><input required value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label className="field inline-field"><span className="field-label">Diners (optional)</span><input type="number" min="1" value={capacity} onChange={(e) => setCapacity(e.target.value)} /></label>
        <button type="submit" className="secondary-btn">Add hall</button>
      </form>
      <ErrorBanner error={error} />
    </>
  );
}

function Contacts({ college, health, onSaved }) {
  const [form, setForm] = useState({
    mess_head_email: college.mess_head_email || "", principal_email: college.principal_email || "",
    fssai_contact_email: college.fssai_contact_email || "",
    grievance_contact: college.grievance_contact || "",
  });
  const [msg, setMsg] = useState(null);
  const missing = health?.missing_contacts || [];
  return (
    <form className="contact-form" onSubmit={async (e) => {
      e.preventDefault();
      try { await updateContacts(college.id, form); setMsg("Saved."); onSaved(); } catch (err) { setMsg(err); }
    }}>
      <p className="hint">Who gets alert emails: 🟢 Low → Mess Head · 🟡 Medium → Principal · 🔴 High → FSSAI (Principal copied).</p>
      {missing.length > 0 && <div className="banner warn">Missing: {missing.map((m) => m.replace("_", " ")).join(", ")} — alerts at that level won't reach anyone.</div>}
      <div className="contact-grid">
        {[["mess_head_email", "Mess Head email"], ["principal_email", "Principal email"], ["fssai_contact_email", "FSSAI contact email"]].map(([k, l]) => (
          <label key={k} className="field"><span className="field-label">{l}</span>
            <input type="email" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      <label className="field"><span className="field-label">Privacy / grievance contact (shown to students)</span>
        <input value={form.grievance_contact} placeholder="e.g. Grievance Officer, grievance@college.ac.in"
          onChange={(e) => setForm({ ...form, grievance_contact: e.target.value })} />
        <span className="hint">Who students contact about their personal data. India's DPDP Act expects one to be named.</span>
      </label>
      <button type="submit" className="secondary-btn">Save contacts</button>
      {typeof msg === "string" ? <span className="ok-text"> {msg}</span> : <ErrorBanner error={msg} />}
    </form>
  );
}

function Checklist({ college }) {
  const items = useAsync(() => getChecklist({ college_id: college.id, include_inactive: true }), [college.id]);
  const [text, setText] = useState("");
  const [critical, setCritical] = useState(false);
  const [error, setError] = useState(null);
  const run = async (fn) => { setError(null); try { await fn(); items.reload(); } catch (e) { setError(e); } };
  if (!items.data) return <Loading />;
  return (
    <>
      <p className="hint">
        {items.data[0]?.is_default ? "Using the default FSSAI-aligned checklist. Any change creates this college's own copy." : "This college's own checklist."}
        {" "}Failing a critical item always raises a High alert.
      </p>
      <ul className="checklist-editor">
        {items.data.map((i) => (
          <li key={i.id} className={i.active ? "" : "inactive"}>
            <span>{i.text} {i.critical && <span className="crit-badge">Critical</span>} {!i.active && <span className="hint">(hidden)</span>}</span>
            <span className="button-row">
              <button type="button" className="link-btn" onClick={() => run(() => updateChecklistItem(i.id, { college_id: college.id, critical: !i.critical }))}>{i.critical ? "Make normal" : "Make critical"}</button>
              <button type="button" className="link-btn" onClick={() => run(() => updateChecklistItem(i.id, { college_id: college.id, active: !i.active }))}>{i.active ? "Hide" : "Show"}</button>
              <button type="button" className="link-btn" onClick={() => {
                const v = prompt("Edit item", i.text);
                if (v && v.trim()) run(() => updateChecklistItem(i.id, { college_id: college.id, text: v }));
              }}>Edit</button>
            </span>
          </li>
        ))}
      </ul>
      <form className="inline-form" onSubmit={(e) => { e.preventDefault(); run(async () => { await addChecklistItem({ college_id: college.id, text, critical }); setText(""); setCritical(false); }); }}>
        <label className="field inline-field grow"><span className="field-label">New item</span><input required maxLength={255} value={text} onChange={(e) => setText(e.target.value)} /></label>
        <label className="checkbox-row"><input type="checkbox" checked={critical} onChange={(e) => setCritical(e.target.checked)} /> Critical</label>
        <button type="submit" className="secondary-btn">Add</button>
      </form>
      <ErrorBanner error={error} />
    </>
  );
}

const RULES = [
  ["fast_lane_reporters", "Safety fast lane: students", "Food poisoning, insects or foreign objects reported by this many different students…"],
  ["fast_lane_hours", "…within this many hours", "…raise a High alert immediately."],
  ["window_days", "Pattern window (days)", "How far back other patterns look."],
  ["category_pct", "Same problem: % of diners", "Different students reporting the same category, as a share of the hall's diners."],
  ["category_min", "Same problem: minimum", "Never fewer students than this…"],
  ["category_max", "Same problem: maximum", "…never more than this. Also used for halls without a capacity."],
  ["mess_pct", "Anything at a hall: % of diners", "Different students reporting any problem at one hall → High alert."],
  ["mess_min", "Anything at a hall: minimum", ""],
  ["mess_max", "Anything at a hall: maximum", ""],
  ["votes_needed", "Students to confirm a fix", "Reporting students who can close a pattern alert by saying it's fixed."],
  ["inspection_interval_days", "Inspect every (days)", "A hall becomes overdue this long after its last inspection."],
];

function AlertRules({ college }) {
  const data = useAsync(() => getCollegeSettings(college.id), [college.id]);
  const [draft, setDraft] = useState({});
  const [msg, setMsg] = useState(null);
  if (!data.data) return <Loading />;
  const { settings, defaults, bounds } = data.data;
  const changed = Object.keys(draft).filter((k) => String(draft[k]) !== String(settings[k]));
  return (
    <form className="contact-form" onSubmit={async (e) => {
      e.preventDefault();
      setMsg(null);
      try {
        await updateCollegeSettings(college.id, Object.fromEntries(changed.map((k) => [k, draft[k] === "" ? null : Number(draft[k])])));
        setDraft({});
        data.reload();
        setMsg("Saved — applies to new complaints from now on.");
      } catch (err) { setMsg(err); }
    }}>
      <p className="hint">Starting values are educated guesses. Check <a href="/admin/insights">Insights</a> to see what each value would have produced on your own data before changing them. Every change is logged.</p>
      <div className="rules-grid">
        {RULES.map(([key, label, help]) => (
          <label key={key} className="field">
            <span className="field-label">{label}</span>
            <input type="number" step={key.endsWith("_pct") ? "0.5" : "1"} min={bounds[key][0]} max={bounds[key][1]}
              value={draft[key] ?? settings[key]} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
            <span className="hint small">{help} Default {defaults[key]}; allowed {bounds[key][0]}–{bounds[key][1]}.</span>
          </label>
        ))}
      </div>
      <div className="button-row">
        <button type="submit" className="primary-btn" disabled={!changed.length}>Save {changed.length || ""} change(s)</button>
        <button type="button" className="link-btn" onClick={async () => {
          if (!confirm("Reset every rule for this college to the defaults?")) return;
          await updateCollegeSettings(college.id, Object.fromEntries(Object.keys(defaults).map((k) => [k, null])));
          setDraft({}); data.reload(); setMsg("Reset to defaults.");
        }}>Reset to defaults</button>
      </div>
      {typeof msg === "string" ? <p className="ok-text">{msg}</p> : <ErrorBanner error={msg} />}
    </form>
  );
}

function NewCollege({ onAdded }) {
  const [form, setForm] = useState({ name: "", email_domain: "" });
  const [error, setError] = useState(null);
  return (
    <form className="form-card" onSubmit={async (e) => {
      e.preventDefault();
      setError(null);
      try { await addCollege(form); setForm({ name: "", email_domain: "" }); onAdded(); } catch (err) { setError(err); }
    }}>
      <h3>Add a college</h3>
      <div className="filters-row">
        <label className="field inline-field grow"><span className="field-label">College name</span><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="field inline-field"><span className="field-label">Student email domain</span><input required placeholder="nitrkl.ac.in" value={form.email_domain} onChange={(e) => setForm({ ...form, email_domain: e.target.value })} /></label>
      </div>
      <p className="hint">Any student whose Google account ends with this domain can report problems for this college.</p>
      <ErrorBanner error={error} />
      <button type="submit" className="primary-btn">Add college</button>
    </form>
  );
}

export default function Setup() {
  const { staff } = useStaff();
  const colleges = useAsync(staffColleges, []);
  const health = useAsync(setupHealth, []);
  const [open, setOpen] = useState({});
  const [error, setError] = useState(null);
  const globalAdmin = !staff.college_id;

  return (
    <>
      {health.data && !health.data.smtp_configured && (
        <div className="banner warn">Email isn't set up (SMTP_EMAIL / SMTP_APP_PASSWORD), so no alert, reminder or reply emails are being sent. Everything is still recorded in Notifications.</div>
      )}
      {globalAdmin && <NewCollege onAdded={colleges.reload} />}
      <ErrorBanner error={colleges.error || error} onRetry={colleges.reload} />
      {!colleges.data && <Loading />}
      {(colleges.data || []).map((c) => {
        const h = health.data?.colleges.find((x) => x.college_id === c.id);
        const section = open[c.id] || "halls";
        return (
          <section key={c.id} className="form-card">
            <div className="report-card-head">
              <h2 className="h3">{c.name} <span className="hint">@{c.email_domain}</span></h2>
              {globalAdmin && <button type="button" className="link-btn danger" onClick={async () => {
                if (!confirm(`Delete ${c.name}? Only possible once it has no mess halls or staff.`)) return;
                try { await deleteCollege(c.id); colleges.reload(); } catch (e) { setError(e); }
              }}>Delete college</button>}
            </div>
            {h?.missing_contacts.length > 0 && section !== "contacts" && <p className="warn-text small">⚠ Missing alert contacts: {h.missing_contacts.join(", ").replaceAll("_", " ")}</p>}
            <div className="sub-tabs" role="tablist">
              {[["halls", "Mess halls & QR codes"], ["contacts", "Contacts"], ["rules", "Alert rules"], ["checklist", "Inspection checklist"]].map(([k, l]) => (
                <button key={k} type="button" role="tab" aria-selected={section === k} className={section === k ? "active" : ""} onClick={() => setOpen({ ...open, [c.id]: k })}>{l}</button>
              ))}
            </div>
            {section === "halls" && <Halls college={c} />}
            {section === "contacts" && <Contacts college={c} health={h} onSaved={() => { colleges.reload(); health.reload(); }} />}
            {section === "rules" && <AlertRules college={c} />}
            {section === "checklist" && <Checklist college={c} />}
          </section>
        );
      })}
    </>
  );
}
