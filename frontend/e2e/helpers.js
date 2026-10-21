import { expect } from "@playwright/test";

export const API = "http://localhost:8002";
export const ADMIN = { email: "admin@e2e.test", password: "e2e-admin-pass" };
// Seeded on a fresh database: "Sample Institute of Technology" (@sample-college.edu)
// with "Mess A - North Block" (id 1) and "Mess B - South Block" (id 2).
export const HALL_A = 1;
export const HALL_B = 2;
const CSRF = { "X-TrayTrack": "1" };

// A 2x2 PNG — a real image the server will accept and re-encode.
export const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==",
  "base64",
);

// Students can't use real Google accounts in tests; the test-only endpoint
// creates the same server session (cookie) Google sign-in would.
export async function signInStudent(context, email, name = "E2E Student") {
  const r = await context.request.post(`${API}/auth/test-login`, { data: { email, name }, headers: CSRF });
  expect(r.ok()).toBeTruthy();
}

export async function staffApi(context, creds = ADMIN) {
  const r = await context.request.post(`${API}/staff/login`, { data: creds, headers: CSRF });
  expect(r.ok(), await r.text()).toBeTruthy();
  return {
    get: (path) => context.request.get(`${API}${path}`, { headers: CSRF }).then((x) => x.json()),
    post: (path, data) => context.request.post(`${API}${path}`, { data, headers: CSRF }).then(async (x) => {
      expect(x.ok(), await x.text()).toBeTruthy();
      return x.json();
    }),
  };
}

export async function createStaff(context, account) {
  const api = await staffApi(context);
  return api.post("/staff/accounts", { password: "e2e-staff-pass", college_id: 1, ...account });
}

export async function staffSignInUi(page, email, password = "e2e-staff-pass") {
  await page.goto("/admin");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Sign out of staff account")).toBeVisible();
}

// Fails the test on any Content-Security-Policy violation or page error.
export function watchForProblems(page) {
  const problems = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && /Content Security Policy|Refused to/i.test(msg.text())) problems.push(msg.text());
  });
  page.on("pageerror", (err) => problems.push(`pageerror: ${err.message}`));
  return problems;
}

// First-time students see the privacy notice; wait for it or the page itself.
export async function acceptPrivacyIfAsked(page) {
  const accept = page.getByRole("button", { name: "I understand — continue" });
  const content = page.locator("main h1");
  await expect(content.or(accept).first()).toBeVisible();
  if (await accept.isVisible()) await accept.click();
}
