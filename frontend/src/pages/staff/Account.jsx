import { useState } from "react";
import { changeOwnPassword, signOutEverywhere } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { ErrorBanner, Field } from "../../components/ui";

const CAP_TEXT = {
  view: "See complaints, alerts, inspections, compliance and activity",
  view_complaints: "See student complaints",
  respond: "Reply to student complaints",
  alert_work: "Work on alerts (acknowledge, start, add proof, mark fixed, assign)",
  alert_verify: "Verify fixes, close and reopen alerts",
  inspect: "Submit inspections",
  schedule: "Schedule inspections",
  compliance_edit: "Add and remove compliance records",
  export: "Download CSV exports",
  setup: "Set up mess halls, contacts, QR codes and the checklist",
  manage_staff: "Create and manage staff accounts",
};

export default function Account() {
  const { staff, signOut } = useStaff();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  return (
    <>
      <section className="form-card">
        <h3>What your account can do</h3>
        <ul className="plain-list">{staff.capabilities.map((c) => <li key={c}>✓ {CAP_TEXT[c] || c}</li>)}</ul>
        <p className="hint">Scope: {staff.mess_name ? `${staff.mess_name} only` : staff.college_name || "All colleges"}</p>
      </section>
      <form className="form-card" onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        setDone(false);
        if (form.next !== form.confirm) return setError("The new passwords don't match.");
        try {
          await changeOwnPassword(form.current, form.next);
          setDone(true);
          setForm({ current: "", next: "", confirm: "" });
        } catch (err) { setError(err); }
      }}>
        <h3>Change your password</h3>
        <Field label="Current password"><input type="password" autoComplete="current-password" required value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} /></Field>
        <Field label="New password" hint="At least 8 characters."><input type="password" autoComplete="new-password" required minLength={8} value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} /></Field>
        <Field label="Repeat new password"><input type="password" autoComplete="new-password" required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} /></Field>
        <ErrorBanner error={error} />
        {done && <div className="banner success">Password changed.</div>}
        <button type="submit" className="primary-btn">Change password</button>
        <p className="hint">Changing your password signs you out on every other device.</p>
      </form>
      <section className="form-card">
        <h3>Sessions</h3>
        <p className="hint">Lost a phone or used a shared computer? Sign out of TrayTrack everywhere, including here.</p>
        <button type="button" className="danger-btn" onClick={async () => {
          if (!confirm("Sign out on every device?")) return;
          try { await signOutEverywhere(); } finally { signOut("You've been signed out everywhere."); }
        }}>Sign out everywhere</button>
      </section>
    </>
  );
}
