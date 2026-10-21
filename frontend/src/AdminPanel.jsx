import { useEffect, useState } from "react";
import {
  getColleges, getMessHalls, adminAddCollege, adminAddMessHall,
  adminDeleteMessHall, adminDeleteCollege, adminUpdateCollegeContacts,
  adminGetAlerts, adminResolveAlert, subscribeToNewActivity,
} from "./api";
import ComplaintList from "./ComplaintList";
import ActivityLog from "./ActivityLog";
import StaffPhoto from "./StaffPhoto";
import StaffManager from "./StaffManager";
import StaffLogin, { StaffBar, useStaffSession } from "./StaffLogin";

export default function AdminPanel() {
  const { staff, setStaff, checking, logout } = useStaffSession();
  const [loginNotice, setLoginNotice] = useState("");
  const [tab, setTab] = useState("activity");
  const authed = staff?.role === "admin";
  // A college-scoped admin manages only their own college; adding or
  // deleting colleges needs an all-colleges admin.
  const isGlobalAdmin = authed && !staff.college_id;

  const [colleges, setColleges] = useState([]);
  const [collegeName, setCollegeName] = useState("");
  const [collegeDomain, setCollegeDomain] = useState("");
  const [messHeadEmail, setMessHeadEmail] = useState("");
  const [principalEmail, setPrincipalEmail] = useState("");
  const [fssaiEmail, setFssaiEmail] = useState("");
  const [messCollegeId, setMessCollegeId] = useState("");
  const [messName, setMessName] = useState("");
  const [manageError, setManageError] = useState("");
  const [contactDrafts, setContactDrafts] = useState({});

  const [alerts, setAlerts] = useState([]);
  const [notesById, setNotesById] = useState({});
  const [messHallsByCollege, setMessHallsByCollege] = useState({});
  const [complaintCollegeId, setComplaintCollegeId] = useState("");
  const [complaintMessId, setComplaintMessId] = useState("");

  function loadColleges() {
    getColleges().then((all) => {
      const cs = staff.college_id ? all.filter((c) => c.id === staff.college_id) : all;
      setColleges(cs);
      if (cs.length && !messCollegeId) setMessCollegeId(cs[0].id);
      const drafts = {};
      cs.forEach((c) => {
        drafts[c.id] = {
          mess_head_email: c.mess_head_email || "",
          principal_email: c.principal_email || "",
          fssai_contact_email: c.fssai_contact_email || "",
        };
        getMessHalls(c.id).then((halls) =>
          setMessHallsByCollege((prev) => ({ ...prev, [c.id]: halls }))
        );
      });
      setContactDrafts(drafts);
    });
  }
  function loadAlerts() {
    adminGetAlerts(false).then(setAlerts);
  }

  useEffect(() => { if (authed) { loadColleges(); loadAlerts(); } }, [authed]);

  // Keep the open-alerts list current: refetch on opening the tab and
  // whenever an alert is raised, escalated or resolved anywhere.
  useEffect(() => {
    if (!authed || tab !== "alerts") return;
    loadAlerts();
    return subscribeToNewActivity({
      onEvent: (row) => { if (row.event_type.startsWith("alert_")) loadAlerts(); },
      onStatus: (s) => { if (s === "expired") handleSessionExpired(); },
    });
  }, [authed, tab]);

  function handleSessionExpired() {
    logout();
    setLoginNotice("Your session expired — please log in again.");
  }

  async function handleAddCollege(e) {
    e.preventDefault();
    setManageError("");
    try {
      await adminAddCollege({
        name: collegeName, email_domain: collegeDomain,
        mess_head_email: messHeadEmail || null,
        principal_email: principalEmail || null,
        fssai_contact_email: fssaiEmail || null,
      });
      setCollegeName(""); setCollegeDomain("");
      setMessHeadEmail(""); setPrincipalEmail(""); setFssaiEmail("");
      loadColleges();
    } catch (err) { setManageError(err.message); }
  }

  async function handleSaveContacts(collegeId) {
    try {
      await adminUpdateCollegeContacts(collegeId, contactDrafts[collegeId]);
      loadColleges();
    } catch (err) { alert(err.message); }
  }

  async function handleAddMessHall(e) {
    e.preventDefault();
    setManageError("");
    try {
      await adminAddMessHall({ college_id: Number(messCollegeId), name: messName });
      setMessName("");
      loadColleges();
    } catch (err) { setManageError(err.message); }
  }

  async function handleResolve(alertId) {
    try {
      await adminResolveAlert(alertId, notesById[alertId] || "");
      loadAlerts();
    } catch (err) { alert(err.message); }
  }

  async function handleDeleteMessHall(messId) {
    if (!confirm("Delete this mess hall? This can't be undone.")) return;
    try {
      await adminDeleteMessHall(messId);
      loadColleges();
    } catch (err) { alert(err.message); }
  }

  async function handleDeleteCollege(collegeId) {
    if (!confirm("Delete this college? This can't be undone.")) return;
    try {
      await adminDeleteCollege(collegeId);
      loadColleges();
    } catch (err) { alert(err.message); }
  }

  if (checking) return <div className="content">Loading…</div>;
  if (!staff) {
    return (
      <StaffLogin
        title="🔐 Admin panel"
        notice={loginNotice}
        onLoggedIn={(s) => { setLoginNotice(""); setStaff(s); }}
      />
    );
  }
  if (!authed) {
    return (
      <div className="content">
        <h1>🔐 Admin panel</h1>
        <StaffBar staff={staff} onLogout={logout} />
        <div className="banner info">
          The Admin Panel needs an admin account. As an inspector you can use the 🔍 Inspector Entry tab.
        </div>
      </div>
    );
  }

  return (
    <div className="content wide">
      <h1>🔐 Admin panel</h1>
      <StaffBar staff={staff} onLogout={logout} />

      <div className="tab-row">
        <button className={`tab-btn ${tab === "activity" ? "active" : ""}`} onClick={() => setTab("activity")}>
          🟢 Live activity
        </button>
        <button className={`tab-btn ${tab === "colleges" ? "active" : ""}`} onClick={() => setTab("colleges")}>
          🏫 Manage colleges &amp; mess halls
        </button>
        <button className={`tab-btn ${tab === "alerts" ? "active" : ""}`} onClick={() => setTab("alerts")}>
          🚨 Open alerts
        </button>
        <button className={`tab-btn ${tab === "complaints" ? "active" : ""}`} onClick={() => setTab("complaints")}>
          📋 All complaints
        </button>
        <button className={`tab-btn ${tab === "staff" ? "active" : ""}`} onClick={() => setTab("staff")}>
          👥 Staff
        </button>
      </div>

      {tab === "staff" && (
        <StaffManager me={staff} colleges={colleges} onSessionExpired={handleSessionExpired} />
      )}

      {tab === "colleges" && (
        <>
          {isGlobalAdmin && (<>
          <h2>Add a college</h2>
          <form onSubmit={handleAddCollege} className="form-card">
            <label>College name<input value={collegeName} onChange={(e) => setCollegeName(e.target.value)} /></label>
            <label>Authorized email domain
              <input value={collegeDomain} onChange={(e) => setCollegeDomain(e.target.value)} placeholder="e.g. nitrkl.ac.in" />
            </label>
            <p className="hint">
              These three contacts receive real alert emails — 🟢 Low → Mess Head, 🟡 Medium → Principal, 🔴 High → FSSAI.
            </p>
            <label>Mess Head email
              <input type="email" value={messHeadEmail} onChange={(e) => setMessHeadEmail(e.target.value)} />
            </label>
            <label>Principal email
              <input type="email" value={principalEmail} onChange={(e) => setPrincipalEmail(e.target.value)} />
            </label>
            <label>FSSAI contact email
              <input type="email" value={fssaiEmail} onChange={(e) => setFssaiEmail(e.target.value)} />
            </label>
            <button className="primary-btn" type="submit">Add college</button>
          </form>
          </>)}

          <h2 style={{ marginTop: isGlobalAdmin ? 28 : 0 }}>Add a mess hall</h2>
          <form onSubmit={handleAddMessHall} className="form-card">
            <label>College
              <select value={messCollegeId} onChange={(e) => setMessCollegeId(e.target.value)}>
                {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label>Mess hall name<input value={messName} onChange={(e) => setMessName(e.target.value)} /></label>
            <button className="primary-btn" type="submit">Add mess hall</button>
          </form>

          {manageError && <div className="banner error">{manageError}</div>}

          <h2 style={{ marginTop: 28 }}>Current colleges &amp; mess halls</h2>
          {colleges.map((c) => (
            <div key={c.id} className="report-card">
              <div className="report-card-head">
                <strong>{c.name}</strong> — domain <code>@{c.email_domain}</code>
                {isGlobalAdmin && (
                  <button className="link-btn" onClick={() => handleDeleteCollege(c.id)}>Delete college</button>
                )}
              </div>

              <div className="contact-grid">
                <label>Mess Head email
                  <input
                    type="email"
                    value={contactDrafts[c.id]?.mess_head_email || ""}
                    onChange={(e) => setContactDrafts({
                      ...contactDrafts,
                      [c.id]: { ...contactDrafts[c.id], mess_head_email: e.target.value },
                    })}
                  />
                </label>
                <label>Principal email
                  <input
                    type="email"
                    value={contactDrafts[c.id]?.principal_email || ""}
                    onChange={(e) => setContactDrafts({
                      ...contactDrafts,
                      [c.id]: { ...contactDrafts[c.id], principal_email: e.target.value },
                    })}
                  />
                </label>
                <label>FSSAI contact email
                  <input
                    type="email"
                    value={contactDrafts[c.id]?.fssai_contact_email || ""}
                    onChange={(e) => setContactDrafts({
                      ...contactDrafts,
                      [c.id]: { ...contactDrafts[c.id], fssai_contact_email: e.target.value },
                    })}
                  />
                </label>
              </div>
              <button className="link-btn" onClick={() => handleSaveContacts(c.id)}>Save contacts</button>

              {(messHallsByCollege[c.id] || []).length === 0 && (
                <p className="hint">(no mess halls yet)</p>
              )}
              {(messHallsByCollege[c.id] || []).map((h) => (
                <div key={h.id} className="mess-hall-row">
                  <span>{h.name}</span>
                  <button className="link-btn" onClick={() => handleDeleteMessHall(h.id)}>Delete</button>
                </div>
              ))}
            </div>
          ))}
        </>
      )}

      {tab === "activity" && (
        <ActivityLog colleges={colleges} onSessionExpired={handleSessionExpired} />
      )}

      {tab === "complaints" && (
        <>
          <p className="hint">
            Every complaint students have filed — including ones that haven't reached an alert threshold yet.
          </p>
          <div className="contact-grid">
            <label>College
              <select
                value={complaintCollegeId}
                onChange={(e) => { setComplaintCollegeId(e.target.value); setComplaintMessId(""); }}
              >
                <option value="">All colleges</option>
                {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label>Mess hall
              <select
                value={complaintMessId}
                onChange={(e) => setComplaintMessId(e.target.value)}
                disabled={!complaintCollegeId}
              >
                <option value="">All mess halls</option>
                {(messHallsByCollege[complaintCollegeId] || []).map((h) => (
                  <option key={h.id} value={h.id}>{h.name}</option>
                ))}
              </select>
            </label>
          </div>
          <ComplaintList collegeId={complaintCollegeId} messId={complaintMessId} />
        </>
      )}

      {tab === "alerts" && (
        <>
          <p className="hint">Even here, student emails are masked — this is the only place they're visible at all.</p>
          {alerts.length === 0 && <div className="banner info">No open alerts.</div>}
          {alerts.map((a) => (
            <div key={a.id} className="report-card">
              <div className="report-card-head">
                <strong>#{a.id} · {a.mess_name} · {a.level}</strong>
                <span className="hint">{a.created_at}</span>
              </div>
              <p><strong>Reason:</strong> {a.reason}</p>
              <p><strong>FSSAI reference:</strong> {a.fssai_reference}</p>
              <p className="hint">Source: {a.source} (record #{a.source_id})</p>

              {a.complaint && (
                <div className="hint" style={{ marginBottom: 10 }}>
                  <p><strong>Reporting student (masked):</strong> {a.complaint.masked_email}</p>
                  <p><strong>Category:</strong> {a.complaint.category}</p>
                  {a.complaint.description && <p><strong>Description:</strong> {a.complaint.description}</p>}
                  {a.complaint.photo_url && (
                    <StaffPhoto photoUrl={a.complaint.photo_url} style={{ maxWidth: 240, borderRadius: 8 }} />
                  )}
                </div>
              )}

              <input
                placeholder="Resolution notes"
                value={notesById[a.id] || ""}
                onChange={(e) => setNotesById({ ...notesById, [a.id]: e.target.value })}
                style={{ marginBottom: 8, width: "100%" }}
              />
              <button className="primary-btn" onClick={() => handleResolve(a.id)}>Mark resolved</button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
