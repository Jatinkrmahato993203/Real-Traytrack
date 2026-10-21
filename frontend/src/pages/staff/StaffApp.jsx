import { lazy, Suspense, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useStaff } from "../../lib/session";
import { ErrorBanner, Field, Loading } from "../../components/ui";

const Activity = lazy(() => import("./Activity"));
const Alerts = lazy(() => import("./Alerts"));
const Complaints = lazy(() => import("./Complaints"));
const Inspections = lazy(() => import("./Inspections"));
const Compliance = lazy(() => import("./Compliance"));
const Setup = lazy(() => import("./Setup"));
const StaffAccounts = lazy(() => import("./StaffAccounts"));
const Notifications = lazy(() => import("./Notifications"));
const Account = lazy(() => import("./Account"));

const ROLE_LABEL = {
  admin: "Admin", principal: "Principal", mess_head: "Mess Head", inspector: "Inspector", auditor: "Auditor",
};

// [path, label, visible-if, component]
const TABS = [
  ["activity", "Live activity", (can) => can("view") || can("view_complaints"), Activity],
  ["alerts", "Alerts", (can) => can("view"), Alerts],
  ["complaints", "Complaints", (can) => can("view_complaints"), Complaints],
  ["inspections", "Inspections", (can) => can("inspect") || can("view"), Inspections],
  ["compliance", "Compliance", (can) => can("view"), Compliance],
  ["setup", "Setup", (can) => can("setup"), Setup],
  ["staff", "Staff", (can) => can("manage_staff"), StaffAccounts],
  ["notifications", "Notifications", (can) => can("view"), Notifications],
  ["account", "My account", () => true, Account],
];

function StaffLogin() {
  const { signIn, notice } = useStaff();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="content">
      <h1>Staff sign-in</h1>
      <p className="subtitle">For mess heads, principals, inspectors and admins. Students: use “Report a problem”.</p>
      <form
        className="form-card"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await signIn(email, password);
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        {notice && <div className="banner info">{notice}</div>}
        <Field label="Email">
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorBanner error={error} />
        <button className="primary-btn" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="hint">Each person has their own account — ask your admin if you need one.</p>
      </form>
    </div>
  );
}

export default function StaffApp() {
  const { staff, checking, can, signOut } = useStaff();
  if (checking) return <div className="content"><Loading /></div>;
  if (!staff) return <StaffLogin />;

  const tabs = TABS.filter(([, , visible]) => visible(can));
  const home = staff.role === "inspector" ? "inspections" : staff.role === "mess_head" ? "alerts" : tabs[0][0];

  return (
    <div className="content wide staff-app">
      <div className="staff-bar">
        <span>
          <strong>{staff.name}</strong> · {ROLE_LABEL[staff.role] || staff.role} ·{" "}
          {staff.mess_name ? `${staff.mess_name}, ${staff.college_name}` : staff.college_name || "All colleges"}
        </span>
        <button type="button" className="link-btn" onClick={() => signOut()}>Sign out of staff account</button>
      </div>
      <nav className="tab-row scroll-x" aria-label="Staff sections">
        {tabs.map(([path, label]) => (
          <NavLink key={path} to={`/admin/${path}`} className={({ isActive }) => `tab-btn ${isActive ? "active" : ""}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <Suspense fallback={<Loading />}>
        <Routes>
          <Route index element={<Navigate to={home} replace />} />
          {tabs.map(([path, , , Component]) => (
            <Route key={path} path={`${path}/*`} element={<Component />} />
          ))}
          <Route path="*" element={<Navigate to={home} replace />} />
        </Routes>
      </Suspense>
    </div>
  );
}
