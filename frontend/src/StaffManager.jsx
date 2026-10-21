import { useEffect, useState } from "react";
import { adminListStaff, adminCreateStaff, adminUpdateStaff } from "./api";

const EMPTY_FORM = { name: "", email: "", role: "inspector", college_id: "", password: "" };

// Admin-only: create admin/inspector accounts, deactivate them, change
// roles and reset passwords. A college-scoped admin only sees and manages
// their own college's staff (the backend enforces this too).
export default function StaffManager({ me, colleges, onSessionExpired }) {
  const [staffList, setStaffList] = useState(null);
  const [form, setForm] = useState({ ...EMPTY_FORM, college_id: me.college_id || "" });
  const [formError, setFormError] = useState("");
  const [formOk, setFormOk] = useState("");
  const [passwordDrafts, setPasswordDrafts] = useState({});
  const [rowMessage, setRowMessage] = useState({});

  function handleError(err, setter) {
    if (err.status === 401) onSessionExpired();
    else setter(err.message);
  }

  function load() {
    adminListStaff().then(setStaffList).catch((err) => handleError(err, alert));
  }

  useEffect(load, []);

  async function handleCreate(e) {
    e.preventDefault();
    setFormError(""); setFormOk("");
    try {
      const created = await adminCreateStaff({
        ...form,
        college_id: form.college_id ? Number(form.college_id) : null,
      });
      setFormOk(`Created ${created.role} account for ${created.name}. Share the password with them privately.`);
      setForm({ ...EMPTY_FORM, college_id: me.college_id || "" });
      load();
    } catch (err) { handleError(err, setFormError); }
  }

  async function update(person, changes, okText) {
    setRowMessage((m) => ({ ...m, [person.id]: "" }));
    try {
      await adminUpdateStaff(person.id, changes);
      setRowMessage((m) => ({ ...m, [person.id]: okText }));
      load();
    } catch (err) {
      handleError(err, (msg) => setRowMessage((m) => ({ ...m, [person.id]: msg })));
    }
  }

  async function handleResetPassword(person) {
    const password = passwordDrafts[person.id] || "";
    await update(person, { password }, "Password changed.");
    setPasswordDrafts((d) => ({ ...d, [person.id]: "" }));
  }

  return (
    <>
      <h2>Add a staff account</h2>
      <form onSubmit={handleCreate} className="form-card">
        <label>Full name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Email (used to log in)
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </label>
        <div className="contact-grid">
          <label>Role
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="inspector">Inspector — submits inspections, sees complaints</option>
              <option value="admin">Admin — full Admin Panel</option>
            </select>
          </label>
          <label>College
            <select
              value={form.college_id}
              onChange={(e) => setForm({ ...form, college_id: e.target.value })}
              disabled={!!me.college_id}
            >
              {!me.college_id && <option value="">All colleges</option>}
              {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        </div>
        <label>Initial password (min 8 characters)
          <input
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </label>
        {formError && <div className="banner error">{formError}</div>}
        {formOk && <div className="banner success">{formOk}</div>}
        <button className="primary-btn" type="submit">Create account</button>
      </form>

      <h2 style={{ marginTop: 28 }}>Staff accounts</h2>
      {!staffList && <p className="hint">Loading…</p>}
      {staffList && staffList.length === 0 && <div className="banner info">No staff accounts yet.</div>}
      {(staffList || []).map((person) => {
        const isMe = person.id === me.id;
        return (
          <div key={person.id} className={`report-card ${person.active ? "" : "staff-inactive"}`}>
            <div className="report-card-head">
              <strong>
                {person.name}{isMe ? " (you)" : ""} · {person.role === "admin" ? "Admin" : "Inspector"}
                {!person.active && " · Deactivated"}
              </strong>
              <span className="hint">{person.college_name || "All colleges"}</span>
            </div>
            <p className="hint">{person.email}</p>

            <div className="staff-actions">
              {!isMe && (
                <button
                  className="link-btn"
                  onClick={() => update(person, { active: !person.active }, person.active ? "Deactivated." : "Reactivated.")}
                >
                  {person.active ? "Deactivate" : "Reactivate"}
                </button>
              )}
              {!isMe && (
                <button
                  className="link-btn"
                  onClick={() => update(
                    person,
                    { role: person.role === "admin" ? "inspector" : "admin" },
                    "Role changed.",
                  )}
                >
                  Make {person.role === "admin" ? "inspector" : "admin"}
                </button>
              )}
              <input
                type="password"
                autoComplete="new-password"
                placeholder={isMe ? "New password for you" : "New password"}
                value={passwordDrafts[person.id] || ""}
                onChange={(e) => setPasswordDrafts((d) => ({ ...d, [person.id]: e.target.value }))}
              />
              <button
                className="link-btn"
                disabled={!passwordDrafts[person.id]}
                onClick={() => handleResetPassword(person)}
              >
                Set password
              </button>
            </div>
            {rowMessage[person.id] && <p className="hint">{rowMessage[person.id]}</p>}
          </div>
        );
      })}
    </>
  );
}
