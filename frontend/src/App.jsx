import { Component, lazy, Suspense, useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useI18n } from "./lib/i18n";
import { useStaff, useStudent } from "./lib/session";
import { Loading } from "./components/ui";

// Pages load on demand: a student opening the report form doesn't download
// the charts library or the staff screens.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Trends = lazy(() => import("./pages/Trends"));
const Privacy = lazy(() => import("./pages/Privacy"));
const Report = lazy(() => import("./pages/student/Report"));
const Rate = lazy(() => import("./pages/student/Rate"));
const MyReports = lazy(() => import("./pages/student/MyReports"));
const StaffApp = lazy(() => import("./pages/staff/StaffApp"));

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="content">
          <div className="banner error" role="alert">
            This page hit an error. <button className="link-btn" onClick={() => location.reload()}>Reload</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function Header() {
  const { t, lang, setLang } = useI18n();
  const { me, signOut } = useStudent();
  const { staff } = useStaff();
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setOpen(false), [location.pathname]);

  const links = [
    ["/", t("nav.dashboard"), true],
    ["/report", t("nav.report")],
    ["/rate", t("nav.rate")],
    ["/my-reports", t("nav.myReports")],
    ["/trends", t("nav.trends")],
    ["/admin", staff ? `${t("nav.staff")} · ${staff.name.split(" ")[0]}` : t("nav.staff")],
  ];

  return (
    <header className="topbar">
      <a href="#main" className="skip-link">{t("nav.skip")}</a>
      <Link to="/" className="brand-mark small" aria-label="TrayTrack home">
        <span aria-hidden="true">🍽️</span> TrayTrack
      </Link>
      <button
        type="button"
        className="menu-btn"
        aria-expanded={open}
        aria-controls="main-nav"
        onClick={() => setOpen((o) => !o)}
      >
        ☰ {t("nav.menu")}
      </button>
      <nav id="main-nav" className={`nav-row ${open ? "open" : ""}`} aria-label="Main">
        {links.map(([to, label, end]) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-btn ${isActive ? "active" : ""}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="user-chip">
        <button type="button" className="link-btn" onClick={() => setLang(lang === "en" ? "hi" : "en")} lang={lang === "en" ? "hi" : "en"}>
          {t("lang.switch")}
        </button>
        {me && (
          <>
            <span className="hide-sm">{me.email}</span>
            <button type="button" className="link-btn" onClick={signOut}>{t("nav.signOut")}</button>
          </>
        )}
      </div>
    </header>
  );
}

function NotFound() {
  const { t } = useI18n();
  return (
    <div className="content">
      <h1>404</h1>
      <p>{t("error.notFound")} <Link to="/">{t("nav.dashboard")}</Link></p>
    </div>
  );
}

function Footer() {
  const { t } = useI18n();
  return (
    <footer className="footer">
      <Link to="/privacy">{t("nav.privacy")}</Link>
      <span className="hint">TrayTrack — FSSAI-aligned mess food safety monitoring</span>
    </footer>
  );
}

export default function App() {
  return (
    <div className="page">
        <Header />
        <main id="main" tabIndex={-1}>
          <ErrorBoundary>
            <Suspense fallback={<div className="content"><Loading /></div>}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/report" element={<Report />} />
                <Route path="/rate" element={<Rate />} />
                <Route path="/my-reports" element={<MyReports />} />
                <Route path="/trends" element={<Trends />} />
                <Route path="/privacy" element={<Privacy />} />
                <Route path="/admin/*" element={<StaffApp />} />
                <Route path="/inspector" element={<Navigate to="/admin/inspections" replace />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </main>
        <Footer />
    </div>
  );
}
