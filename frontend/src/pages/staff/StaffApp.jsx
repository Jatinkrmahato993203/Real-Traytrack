import { lazy, Suspense, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { getMyWork, onNewActivity } from "../../lib/api";
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
const Insights = lazy(() => import("./Insights"));
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
  ["insights", "Insights", (can) => can("view"), Insights],
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

// What needs attention, per tab — so nobody depends on email to know.
const BADGES = {
  alerts: (w) => (w.alerts_assigned_to_me || 0) + (w.fixes_to_verify || 0) + (w.alerts_untouched || 0),
  complaints: (w) => w.complaints_unanswered || 0,
  inspections: (w) => (w.inspections_due || 0),
  compliance: (w) => w.compliance_expiring || 0,
};
const BADGE_TITLE = {
  alerts: (w) => [w.alerts_assigned_to_me && `${w.alerts_assigned_to_me} assigned to you`, w.fixes_to_verify && `${w.fixes_to_verify} fixes to verify`, w.alerts_untouched && `${w.alerts_untouched} untouched`].filter(Boolean).join(", "),
  complaints: (w) => `${w.complaints_unanswered} without a reply`,
  inspections: (w) => `${w.inspections_due} halls due${w.inspections_assigned ? `, ${w.inspections_assigned} scheduled for you` : ""}`,
  compliance: (w) => `${w.compliance_expiring} expired or expiring`,
};

function useMyWork(enabled) {
  const [work, setWork] = useState({});
  useEffect(() => {
    if (!enabled) return undefined;
    let timer;
    const load = () => getMyWork().then(setWork).catch(() => {});
    load();
    timer = setInterval(load, 60000);
    let debounce;
    const stop = onNewActivity({ onEvent: () => { clearTimeout(debounce); debounce = setTimeout(load, 1500); } });
    return () => { clearInterval(timer); clearTimeout(debounce); stop(); };
  }, [enabled]);
  return work;
}

export default function StaffApp() {
  const { staff, checking, can, signOut } = useStaff();
  const work = useMyWork(!!staff);
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
        {tabs.map(([path, label]) => {
          const count = BADGES[path]?.(work) || 0;
          return (
            <NavLink key={path} to={`/admin/${path}`} className={({ isActive }) => `tab-btn ${isActive ? "active" : ""}`}>
              {label}
              {count > 0 && <span className="badge" title={BADGE_TITLE[path](work)} aria-label={`, ${BADGE_TITLE[path](work)}`}>{count}</span>}
            </NavLink>
          );
        })}
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
