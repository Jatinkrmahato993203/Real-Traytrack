import { createHmac } from "node:crypto";
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

// What an authenticator app does (RFC 6238): 6-digit code from a base32 secret.
export function totpCode(secret, time = Date.now(), offsetSteps = 0) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.replace(/[\s=]/g, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g).map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(time / 30000) + offsetSteps));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = digest[digest.length - 1] & 0xf;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

// Secrets of accounts that turned on two-factor during the tests.
export const twoFactorSecrets = {};
let lastCodeStep = 0;

export async function staffSignInUi(page, email, password = "e2e-staff-pass") {
  await page.goto("/admin");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  const codeStep = page.getByRole("heading", { name: "Enter your code" });
  const signedIn = page.getByText("Sign out of staff account");
  const forcedSetup = page.getByRole("heading", { name: "Set up two-factor sign-in" });
  await expect(codeStep.or(signedIn).or(forcedSetup).first()).toBeVisible();
  if (await codeStep.isVisible()) {
    // Codes are single-use per 30 s step: wait for a fresh step if needed.
    let step = Math.floor(Date.now() / 30000);
    if (step <= lastCodeStep) {
      await page.waitForTimeout((lastCodeStep + 1) * 30000 - Date.now() + 500);
      step = lastCodeStep + 1;
    }
    lastCodeStep = step;
    await page.getByLabel("Code").fill(totpCode(twoFactorSecrets[email]));
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(signedIn).toBeVisible();
  }
}

// The forced first-sign-in setup: read the key like a user would, confirm
// with a code, save the recovery codes.
export async function completeTwoFactorSetup(page, email) {
  await expect(page.getByRole("heading", { name: "Set up two-factor sign-in" })).toBeVisible();
  await page.getByRole("button", { name: "Set up two-factor sign-in" }).click();
  await expect(page.getByAltText(/QR code to add TrayTrack/)).toBeVisible();
  await page.getByText("Can't scan? Enter this key instead").click();
  const secret = (await page.locator(".secret-key").innerText()).replace(/\s/g, "");
  twoFactorSecrets[email] = secret;
  lastCodeStep = Math.floor(Date.now() / 30000);
  await page.getByLabel("Enter the 6-digit code").fill(totpCode(secret));
  await page.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByText("Save these recovery codes now")).toBeVisible();
  const codes = await page.locator(".recovery-codes code").allInnerTexts();
  expect(codes).toHaveLength(10);
  await page.getByRole("button", { name: "I've saved them" }).click();
  await expect(page.getByText("Sign out of staff account")).toBeVisible();
  return codes;
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
