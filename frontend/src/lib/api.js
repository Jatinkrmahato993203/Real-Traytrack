// Every call to the backend goes through request(), so errors look the same
// everywhere: an ApiError with a readable message, the HTTP status, and the
// server's request id (quoted in "Something went wrong" messages).
//
// Sign-in sessions live in HttpOnly cookies set by the server — this code
// never sees or stores a token, so a script injected into the page can't
// steal one. Every request sends X-TrayTrack, which the server requires on
// cookie-authenticated writes (CSRF protection).

export const API_BASE = (import.meta.env.VITE_API_BASE || "http://localhost:8000").replace(/\/$/, "");

// Tokens from older versions of the app lived in localStorage; drop them.
try {
  ["tt_student_token", "tt_staff_token", "user_token", "staff_token", "admin_token"].forEach((k) => localStorage.removeItem(k));
} catch { /* storage blocked */ }

export class ApiError extends Error {
  constructor(message, status, requestId, detail) {
    super(message);
    this.status = status;
    this.requestId = requestId;
    this.detail = detail;
  }
}

function messageFrom(body, status) {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (d?.message) return d.message;
  if (Array.isArray(d)) return d.map((e) => e.msg).join("; ");
  if (status === 0) return "Can't reach the server. Check your connection and try again.";
  return `Request failed (${status}).`;
}

async function request(path, { method = "GET", body, form, auth, signal, raw } = {}) {
  const headers = { "X-TrayTrack": "1" };
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body: payload, signal, credentials: "include" });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(messageFrom(null, 0), 0);
  }
  const requestId = res.headers.get("X-Request-ID");
  if (res.status === 401 && auth) {
    // Session expired or revoked — let the app drop it and show sign-in.
    window.dispatchEvent(new CustomEvent("tt-session-expired", { detail: auth }));
  }
  if (raw && res.ok) return res;
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) throw new ApiError(messageFrom(data, res.status), res.status, requestId, data?.detail);
  return data;
}

function qs(params) {
  const p = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

function formData(fields) {
  const f = new FormData();
  Object.entries(fields).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") f.append(k, v);
  });
  return f;
}

// ---------- Public ----------
export const getColleges = () => request("/colleges");
export const getMessHalls = (collegeId) => request(`/mess-halls${qs({ college_id: collegeId })}`);
export const getMessHall = (id) => request(`/mess-halls/${id}`);
export const getCategories = () => request("/categories");
export const getMeals = () => request("/meals");
export const getPrivacyInfo = () => request("/privacy");
export const getDashboardStatus = (collegeId) => request(`/dashboard-status${qs({ college_id: collegeId })}`);
export const getOpenAlerts = (collegeId, messId) => request(`/alerts${qs({ college_id: collegeId, mess_id: messId })}`);
export const getAnalytics = (collegeId) => request(`/analytics${qs({ college_id: collegeId })}`);
export const getTrends = (collegeId, start, end) =>
  request(`/trends${qs({ college_id: collegeId, start_date: start, end_date: end })}`);

// ---------- Student ----------
export const loginWithGoogle = (credential) => request("/auth/google", { method: "POST", body: { credential } });
export const studentLogout = () => request("/auth/logout", { method: "POST" });
export const getMe = () => request("/me", { auth: "student" });
export const acceptPrivacy = (version) => request("/me/consent", { method: "POST", body: { version }, auth: "student" });
export const submitComplaint = (fields, photo) =>
  request("/complaints", { method: "POST", form: formData({ ...fields, photo }), auth: "student" });
export const getMyComplaints = () => request("/my-complaints", { auth: "student" });
export const voteFixed = (alertId) =>
  request("/my-complaints/resolve", { method: "POST", body: { alert_id: alertId }, auth: "student" });
export const rateMeal = (body) => request("/ratings", { method: "POST", body, auth: "student" });
export const getMyRatings = () => request("/my-ratings", { auth: "student" });

export const eraseMyData = () => request("/me/data", { method: "DELETE", auth: "student" });

// ---------- Staff ----------
const s = (path, opts = {}) => request(`/staff${path}`, { ...opts, auth: "staff" });

export const staffLogin = (email, password) => request("/staff/login", { method: "POST", body: { email, password } });
export const staffLogout = () => request("/staff/logout", { method: "POST" });
export const verifyStaffCode = (code) => request("/staff/login/verify", { method: "POST", body: { code } });
export const twoFactorSetup = () => s("/me/2fa/setup", { method: "POST" });
export const twoFactorEnable = (code) => s("/me/2fa/enable", { method: "POST", body: { code } });
export const twoFactorDisable = (password, code) => s("/me/2fa/disable", { method: "POST", body: { password, code } });
export const newRecoveryCodes = (code) => s("/me/2fa/recovery-codes", { method: "POST", body: { code } });
export const signOutEverywhere = () => s("/me/sign-out-everywhere", { method: "POST" });
export const getCollegeSettings = (id) => s(`/colleges/${id}/settings`);
export const updateCollegeSettings = (id, changes) => s(`/colleges/${id}/settings`, { method: "PATCH", body: changes });
export const getInsights = (collegeId, days) => s(`/insights${qs({ college_id: collegeId, days })}`);
export const getMyWork = () => s("/my-work");
export const hideComplaint = (id, reason) => s(`/complaints/${id}/hide`, { method: "POST", body: { reason } });
export const getStaffMe = () => s("/me");
export const changeOwnPassword = (current_password, new_password) =>
  s("/me/password", { method: "POST", body: { current_password, new_password } });
export const getRoles = () => s("/roles");
export const listStaff = (role) => s(`/accounts${qs({ role })}`);
export const createStaff = (body) => s("/accounts", { method: "POST", body });
export const updateStaff = (id, body) => s(`/accounts/${id}`, { method: "PATCH", body });

export const staffColleges = () => s("/colleges");
export const addCollege = (body) => s("/colleges", { method: "POST", body });
export const updateContacts = (id, body) => s(`/colleges/${id}/contacts`, { method: "PATCH", body });
export const deleteCollege = (id) => s(`/colleges/${id}`, { method: "DELETE" });
export const setupHealth = () => s("/setup-health");
export const staffMessHalls = (collegeId) => s(`/mess-halls${qs({ college_id: collegeId })}`);
export const addMessHall = (body) => s("/mess-halls", { method: "POST", body });
export const updateMessHall = (id, body) => s(`/mess-halls/${id}`, { method: "PATCH", body });
export const newKitchenCode = (id) => s(`/mess-halls/${id}/kitchen-code`, { method: "POST" });
export const deleteMessHall = (id) => s(`/mess-halls/${id}`, { method: "DELETE" });
export const getChecklist = (params) => s(`/checklist${qs(params)}`);
export const addChecklistItem = (body) => s("/checklist-items", { method: "POST", body });
export const updateChecklistItem = (id, body) => s(`/checklist-items/${id}`, { method: "PATCH", body });

export const searchComplaints = (params) => s(`/complaints${qs(params)}`);
export const respondToComplaint = (id, status, response) =>
  s(`/complaints/${id}/respond`, { method: "POST", body: { status, response } });
export const searchAlerts = (params) => s(`/alerts${qs(params)}`);
export const getAlertDetail = (id) => s(`/alerts/${id}`);
export const alertAction = (id, action, note) => s(`/alerts/${id}/action`, { method: "POST", body: { action, note } });
export const reopenAlert = (id, note) => s(`/alerts/${id}/reopen`, { method: "POST", body: { note } });
export const assignAlert = (id, owner_staff_id, due_date) =>
  s(`/alerts/${id}/assign`, { method: "POST", body: { owner_staff_id, due_date } });
export const addEvidence = (id, { note, inspectionId, photo }) =>
  s(`/alerts/${id}/evidence`, { method: "POST", form: formData({ note, inspection_id: inspectionId, photo }) });

export const submitInspection = (body) => s("/inspections", { method: "POST", body });
export const addInspectionPhoto = (id, itemKey, photo) =>
  s(`/inspections/${id}/photos`, { method: "POST", form: formData({ item_key: itemKey, photo }) });
export const listInspections = (params) => s(`/inspections${qs(params)}`);
export const getInspection = (id) => s(`/inspections/${id}`);
export const inspectionOverview = (collegeId) => s(`/inspection-overview${qs({ college_id: collegeId })}`);
export const addSchedule = (body) => s("/schedule", { method: "POST", body });
export const deleteSchedule = (id) => s(`/schedule/${id}`, { method: "DELETE" });

export const complianceTypes = () => s("/compliance/types");
export const listCompliance = (params) => s(`/compliance${qs(params)}`);
export const addCompliance = (fields, scan) => s("/compliance", { method: "POST", form: formData({ ...fields, scan }) });
export const deleteCompliance = (id) => s(`/compliance/${id}`, { method: "DELETE" });

export const listNotifications = (params) => s(`/notifications${qs(params)}`);
export const getActivity = (params) => s(`/activity${qs(params)}`);

// Protected files (photos, CSV exports, the student's data export) are
// authorised by the session cookie, so plain links and <img> work.
export const fileUrl = (path) => `${API_BASE}${path.replace(/^\/admin\/complaint-photos\//, "/staff/photos/")}`;

export function download(path) {
  const a = document.createElement("a");
  a.href = fileUrl(path);
  a.rel = "noopener";
  a.click();
}

export const downloadStaffFile = (path) => download(path);
export const downloadStudentData = () => download("/me/data");

// Live activity over Server-Sent Events (the session cookie authenticates
// it). Reconnects from the last event it saw.
export function streamActivity({ afterId = 0, collegeId, messId, onEvent, onStatus }) {
  let lastId = afterId;
  let stopped = false;
  let controller = null;

  (async () => {
    while (!stopped) {
      controller = new AbortController();
      try {
        const res = await fetch(`${API_BASE}/staff/activity/stream${qs({ after_id: lastId, college_id: collegeId, mess_id: messId })}`, {
          credentials: "include",
          signal: controller.signal,
        });
        if (res.status === 401) {
          onStatus("expired");
          window.dispatchEvent(new CustomEvent("tt-session-expired", { detail: "staff" }));
          return;
        }
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        onStatus("live");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let sep;
          while ((sep = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            let event = "message";
            let data = "";
            for (const line of frame.split("\n")) {
              if (line.startsWith("event:")) event = line.slice(6).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (event === "expired") {
              onStatus("expired");
              return;
            }
            if (event === "activity" && data) {
              const row = JSON.parse(data);
              lastId = Math.max(lastId, row.id);
              onEvent(row);
            }
          }
        }
      } catch {
        if (stopped) return;
      }
      if (stopped) return;
      onStatus("reconnecting");
      await new Promise((r) => setTimeout(r, 3000));
    }
  })();

  return () => {
    stopped = true;
    controller?.abort();
  };
}

// Subscribe from "now on" — for views that just refetch when something changes.
export function onNewActivity({ collegeId, messId, onEvent, onStatus = () => {} }) {
  let stop = () => {};
  let cancelled = false;
  getActivity({ college_id: collegeId, mess_id: messId, limit: 1 })
    .then((rows) => {
      if (!cancelled) stop = streamActivity({ afterId: rows[0]?.id || 0, collegeId, messId, onEvent, onStatus });
    })
    .catch(() => {});
  return () => {
    cancelled = true;
    stop();
  };
}
