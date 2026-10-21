import { useEffect, useState } from "react";
import { staffLogin, getStaffMe, hasStaffSession, clearStaffSession } from "./api";

// The signed-in admin/inspector for this tab, or null. On load it asks the
// backend who the stored token belongs to, so a deactivated account or an
// expired token drops straight back to the login form.
export function useStaffSession() {
  const [staff, setStaff] = useState(null);
  const [checking, setChecking] = useState(hasStaffSession());

  useEffect(() => {
    if (!hasStaffSession()) return;
    getStaffMe()
      .then(setStaff)
      .catch(() => clearStaffSession())
      .finally(() => setChecking(false));
  }, []);

  function logout() {
    clearStaffSession();
    setStaff(null);
  }

  return { staff, setStaff, checking, logout };
}

export function StaffBar({ staff, onLogout }) {
  return (
    <div className="staff-bar">
      <span>
        Signed in as <strong>{staff.name}</strong> · {staff.role === "admin" ? "Admin" : "Inspector"} ·{" "}
        {staff.college_name || "All colleges"}
      </span>
      <button className="link-btn" onClick={onLogout}>Log out of staff account</button>
    </div>
  );
}

export default function StaffLogin({ title, onLoggedIn, notice }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      onLoggedIn(await staffLogin(email, password));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content">
      <h1>{title}</h1>
      <form onSubmit={handleSubmit} className="form-card">
        {notice && <div className="banner info" style={{ marginTop: 0 }}>{notice}</div>}
        <label>
          Staff email
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <div className="banner error">{error}</div>}
        <button className="primary-btn" type="submit" disabled={busy}>{busy ? "Logging in…" : "Log in"}</button>
        <p className="hint">Each admin and inspector has their own account — ask an admin if you need one.</p>
      </form>
    </div>
  );
}
