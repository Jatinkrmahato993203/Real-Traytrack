const API_BASE = "http://localhost:8000";

function authHeaders() {
  const token = localStorage.getItem("user_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// The student session token expires after 24h — when the backend rejects
// it, drop the stale session so the app shows the sign-in screen again.
function handleUserAuthFailure(res) {
  if (res.status === 401) {
    localStorage.removeItem("user_email");
    localStorage.removeItem("user_name");
    localStorage.removeItem("user_token");
    window.dispatchEvent(new Event("user-session-expired"));
  }
}

// Staff (admin / inspector) session — one per browser tab.
function adminHeaders() {
  const token = sessionStorage.getItem("staff_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function hasStaffSession() {
  return !!sessionStorage.getItem("staff_token");
}

export function clearStaffSession() {
  sessionStorage.removeItem("staff_token");
}

async function staffRequest(method, path, data) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { ...(data ? { "Content-Type": "application/json" } : {}), ...adminHeaders() },
    body: data ? JSON.stringify(data) : undefined,
  });
  const body = await res.json();
  if (!res.ok) {
    const err = new Error(body.detail || "Request failed");
    err.status = res.status;
    throw err;
  }
  return body;
}

export async function loginWithGoogle(credential) {
  const res = await fetch(`${API_BASE}/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credential }),
  });
  if (!res.ok) throw new Error("Google sign-in failed");
  return res.json();
}

export async function staffLogin(email, password) {
  const res = await fetch(`${API_BASE}/staff/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Incorrect email or password");
  sessionStorage.setItem("staff_token", body.token);
  return body.staff;
}

export const getStaffMe = () => staffRequest("GET", "/staff/me");
export const adminListStaff = () => staffRequest("GET", "/admin/staff");
export const adminCreateStaff = (data) => staffRequest("POST", "/admin/staff", data);
export const adminUpdateStaff = (id, data) => staffRequest("PATCH", `/admin/staff/${id}`, data);

export async function getColleges() {
  const res = await fetch(`${API_BASE}/colleges`);
  return res.json();
}

export async function getMessHalls(collegeId) {
  const res = await fetch(`${API_BASE}/mess-halls?college_id=${collegeId}`);
  return res.json();
}

export async function getCategories() {
  const res = await fetch(`${API_BASE}/categories`);
  return res.json();
}

export async function getChecklist() {
  const res = await fetch(`${API_BASE}/checklist`);
  return res.json();
}

export async function submitComplaint(fields, photoFile) {
  const formData = new FormData();
  Object.entries(fields).forEach(([k, v]) => formData.append(k, v));
  if (photoFile) formData.append("photo", photoFile);

  const res = await fetch(`${API_BASE}/complaints`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });
  handleUserAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed to submit complaint");
  return body;
}

export async function getMyComplaints() {
  const res = await fetch(`${API_BASE}/my-complaints`, { headers: authHeaders() });
  handleUserAuthFailure(res);
  if (!res.ok) throw new Error("Couldn't load your reports.");
  return res.json();
}

export async function resolveMyAlert(alertId) {
  const res = await fetch(`${API_BASE}/my-complaints/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ alert_id: alertId }),
  });
  handleUserAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed to resolve");
  return body;
}

export async function getDashboardStatus(collegeId) {
  const res = await fetch(`${API_BASE}/dashboard-status?college_id=${collegeId}`);
  return res.json();
}

export async function getAnalytics(collegeId) {
  const res = await fetch(`${API_BASE}/analytics?college_id=${collegeId}`);
  return res.json();
}

export async function getOpenAlerts(collegeId, messId) {
  const params = new URLSearchParams();
  if (collegeId) params.set("college_id", collegeId);
  if (messId) params.set("mess_id", messId);
  const res = await fetch(`${API_BASE}/alerts?${params}`);
  return res.json();
}

export async function getTrends(collegeId, startDate, endDate) {
  const params = new URLSearchParams();
  if (collegeId) params.set("college_id", collegeId);
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);
  const res = await fetch(`${API_BASE}/trends?${params}`);
  return res.json();
}

export async function submitInspection(data) {
  const res = await fetch(`${API_BASE}/inspections`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...adminHeaders() },
    body: JSON.stringify(data),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed to submit inspection");
  return body;
}

export async function adminAddCollege(data) {
  const res = await fetch(`${API_BASE}/admin/colleges`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...adminHeaders() },
    body: JSON.stringify(data),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed");
  return body;
}

export async function adminUpdateCollegeContacts(collegeId, data) {
  const res = await fetch(`${API_BASE}/admin/colleges/${collegeId}/contacts`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...adminHeaders() },
    body: JSON.stringify(data),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed");
  return body;
}

export async function adminAddMessHall(data) {
  const res = await fetch(`${API_BASE}/admin/mess-halls`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...adminHeaders() },
    body: JSON.stringify(data),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed");
  return body;
}

export async function adminDeleteMessHall(messId) {
  const res = await fetch(`${API_BASE}/admin/mess-halls/${messId}`, {
    method: "DELETE",
    headers: adminHeaders(),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed to delete");
  return body;
}

export async function adminDeleteCollege(collegeId) {
  const res = await fetch(`${API_BASE}/admin/colleges/${collegeId}`, {
    method: "DELETE",
    headers: adminHeaders(),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed to delete");
  return body;
}

export async function adminGetAlerts(resolved = false) {
  const res = await fetch(`${API_BASE}/admin/alerts?resolved=${resolved}`, { headers: adminHeaders() });
  return res.json();
}

export async function adminGetComplaints({ collegeId, messId, days } = {}) {
  const params = new URLSearchParams();
  if (collegeId) params.set("college_id", collegeId);
  if (messId) params.set("mess_id", messId);
  params.set("days", days ?? 30);
  const res = await fetch(`${API_BASE}/admin/complaints?${params}`, { headers: adminHeaders() });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed to load complaints");
  return body;
}

export async function adminGetActivity({ collegeId, eventType, beforeId, limit = 100 } = {}) {
  const params = new URLSearchParams({ limit });
  if (collegeId) params.set("college_id", collegeId);
  if (eventType) params.set("event_type", eventType);
  if (beforeId) params.set("before_id", beforeId);
  const res = await fetch(`${API_BASE}/admin/activity?${params}`, { headers: adminHeaders() });
  const body = await res.json();
  if (!res.ok) {
    const err = new Error(body.detail || "Failed to load activity");
    err.status = res.status;
    throw err;
  }
  return body;
}

// Live activity over Server-Sent Events. Uses fetch (not EventSource) so
// the admin token travels in the Authorization header, never in the URL.
// Reconnects automatically, resuming from the last event it received.
// Returns a function that stops the stream.
export function streamAdminActivity({ afterId = 0, collegeId, onEvent, onStatus }) {
  let lastId = afterId;
  let stopped = false;
  let controller = null;

  async function connect() {
    while (!stopped) {
      controller = new AbortController();
      try {
        const params = new URLSearchParams({ after_id: lastId });
        if (collegeId) params.set("college_id", collegeId);
        const res = await fetch(`${API_BASE}/admin/activity/stream?${params}`, {
          headers: adminHeaders(),
          signal: controller.signal,
        });
        if (res.status === 401) { onStatus("expired"); return; }
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
            if (event === "expired") { onStatus("expired"); return; }
            if (event === "activity" && data) {
              const row = JSON.parse(data);
              lastId = Math.max(lastId, row.id);
              onEvent(row);
            }
          }
        }
      } catch (err) {
        if (stopped) return;
      }
      if (stopped) return;
      onStatus("reconnecting");
      await new Promise((r) => setTimeout(r, 3000));
    }
  }

  connect();
  return () => {
    stopped = true;
    if (controller) controller.abort();
  };
}

// Live updates from "now on" only — for views that just need to know
// something changed (e.g. to refetch), not the history.
export function subscribeToNewActivity({ collegeId, onEvent, onStatus = () => {} }) {
  let stop = () => {};
  let cancelled = false;
  adminGetActivity({ collegeId, limit: 1 })
    .then((rows) => {
      if (cancelled) return;
      stop = streamAdminActivity({ afterId: rows.length ? rows[0].id : 0, collegeId, onEvent, onStatus });
    })
    .catch((err) => { if (err.status === 401) onStatus("expired"); });
  return () => {
    cancelled = true;
    stop();
  };
}

export async function adminResolveAlert(alertId, notes) {
  const res = await fetch(`${API_BASE}/admin/alerts/${alertId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...adminHeaders() },
    body: JSON.stringify({ notes }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || "Failed");
  return body;
}

// Complaint photos are staff-only, so they're fetched with the Bearer
// header (an <img src> can't send one) and shown via a blob: URL.
// Takes the photo_url the API returns; older activity rows still say
// /uploads/complaints/<name>, so only the file name is used.
export async function fetchComplaintPhoto(photoUrl) {
  const name = photoUrl.split("/").pop();
  const res = await fetch(`${API_BASE}/admin/complaint-photos/${encodeURIComponent(name)}`, {
    headers: adminHeaders(),
  });
  if (!res.ok) throw new Error("Photo unavailable");
  return URL.createObjectURL(await res.blob());
}

