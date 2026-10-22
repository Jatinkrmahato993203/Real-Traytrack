import { useState } from "react";
import { createStaff, getRoles, listStaff, staffColleges, staffMessHalls, updateStaff } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { ErrorBanner, Field, Loading, useAsync } from "../../components/ui";

const ROLE_LABEL = { admin: "Admin", principal: "Principal", mess_head: "Mess Head", inspector: "Inspector", auditor: "Auditor" };

export default function StaffAccounts() {
  const { staff: me } = useStaff();
  const roles = useAsync(getRoles, []);
  const colleges = useAsync(staffColleges, []);
  const list = useAsync(() => listStaff(), []);
  const empty = { name: "", email: "", role: "inspector", college_id: me.college_id || "", mess_id: "", password: "" };
  const [form, setForm] = useState(empty);
  const halls = useAsync(() => (form.college_id ? staffMessHalls(form.college_id) : []), [form.college_id]);
  const [error, setError] = useState(null);
  const [ok, setOk] = useState("");
  const [rowMsg, setRowMsg] = useState({});
  const [pw, setPw] = useState({});

  async function update(person, changes, msg) {
    try {
      await updateStaff(person.id, changes);
      setRowMsg((m) => ({ ...m, [person.id]: msg }));
      list.reload();
    } catch (e) {
      setRowMsg((m) => ({ ...m, [person.id]: e.message }));
    }
  }

  return (
    <>
      <form className="form-card" onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        setOk("");
        try {
          const created = await createStaff({ ...form, college_id: form.college_id ? Number(form.college_id) : null, mess_id: form.mess_id ? Number(form.mess_id) : null });
          setOk(`Created ${ROLE_LABEL[created.role]} account for ${created.name}. Share the password privately; they can change it under "My account".`);
          setForm(empty);
          list.reload();
        } catch (err) { setError(err); }
      }}>
        <h3>Add a staff account</h3>
        <div className="filters-row">
          <label className="field inline-field grow"><span className="field-label">Full name</span><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label className="field inline-field grow"><span className="field-label">Email (login)</span><input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        </div>
        <Field label="Role">
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {(roles.data || []).map((r) => <option key={r.role} value={r.role}>{r.description}</option>)}
          </select>
        </Field>
        <div className="filters-row">
          <label className="field inline-field"><span className="field-label">College</span>
            <select value={form.college_id} disabled={!!me.college_id} onChange={(e) => setForm({ ...form, college_id: e.target.value, mess_id: "" })}>
              {!me.college_id && <option value="">All colleges</option>}
              {(colleges.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          {form.college_id && (
            <label className="field inline-field"><span className="field-label">Limit to one mess hall</span>
              <select value={form.mess_id} onChange={(e) => setForm({ ...form, mess_id: e.target.value })}>
                <option value="">No — whole college</option>
                {(halls.data || []).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
              </select>
            </label>
          )}
        </div>
        <Field label="Initial password" hint="At least 10 characters; common passwords are refused."><input type="password" autoComplete="new-password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
        <ErrorBanner error={error} />
        {ok && <div className="banner success">{ok}</div>}
        <button type="submit" className="primary-btn">Create account</button>
      </form>

      <h3>Accounts</h3>
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {!list.data && <Loading />}
      {(list.data || []).map((p) => {
        const isMe = p.id === me.id;
        return (
          <article key={p.id} className={`report-card ${p.active ? "" : "staff-inactive"}`}>
            <div className="report-card-head">
              <strong>{p.name}{isMe && " (you)"} · {ROLE_LABEL[p.role] || p.role}{!p.active && " · Deactivated"}</strong>
              <span className="hint">{p.mess_name ? `${p.mess_name}, ` : ""}{p.college_name || "All colleges"}</span>
            </div>
            <p className="hint">{p.email} · {p.two_factor_enabled ? "✓ two-factor on" : "two-factor off"}</p>
            <div className="button-row">
              {!isMe && <button type="button" className="link-btn" onClick={() => update(p, { active: !p.active }, p.active ? "Deactivated — their sessions stop immediately." : "Reactivated.")}>{p.active ? "Deactivate" : "Reactivate"}</button>}
              {!isMe && (
                <select aria-label={`Change role for ${p.name}`} value={p.role} onChange={(e) => update(p, { role: e.target.value }, "Role changed.")}>
                  {Object.entries(ROLE_LABEL).map(([r, l]) => <option key={r} value={r}>{l}</option>)}
                </select>
              )}
              <input type="password" autoComplete="new-password" placeholder="New password" value={pw[p.id] || ""} onChange={(e) => setPw({ ...pw, [p.id]: e.target.value })} />
              <button type="button" className="link-btn" disabled={!pw[p.id]} onClick={async () => { await update(p, { password: pw[p.id] }, "Password changed."); setPw({ ...pw, [p.id]: "" }); }}>Set password</button>
              {!isMe && p.two_factor_enabled && (
                <button type="button" className="link-btn danger" onClick={() => confirm(`Reset ${p.name}'s two-factor sign-in? Use this if they lost their phone — they'll set it up again.`) && update(p, { reset_two_factor: true }, "Two-factor reset; they've been signed out.")}>Reset two-factor</button>
              )}
            </div>
            {rowMsg[p.id] && <p className="hint">{rowMsg[p.id]}</p>}
          </article>
        );
      })}
    </>
  );
}
