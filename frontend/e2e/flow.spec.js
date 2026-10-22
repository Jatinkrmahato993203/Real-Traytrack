// The core loop, end to end in a real browser:
// students report → a pattern raises an alert → the mess head works it with
// proof → the principal verifies → students see it resolved.
import { expect, test } from "@playwright/test";
import {
  acceptPrivacyIfAsked, API, completeTwoFactorSetup, createStaff, HALL_A, PNG, signInStudent, staffApi, staffSignInUi,
  watchForProblems,
} from "./helpers";

test.describe.configure({ mode: "serial" });

test("three students reporting food poisoning raise a High alert", async ({ browser }) => {
  for (let i = 1; i <= 3; i++) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const problems = watchForProblems(page);
    await signInStudent(context, `student${i}@sample-college.edu`, `Student ${i}`);

    // A table QR code opens the form with the hall already chosen.
    await page.goto(`/report?mess=${HALL_A}`);
    await acceptPrivacyIfAsked(page);
    await expect(page.getByRole("heading", { name: "Report a problem" })).toBeVisible();
    await expect(page.getByLabel("Mess hall")).toHaveValue(String(HALL_A));
    await page.getByLabel("What went wrong?").selectOption("Food poisoning / illness reported");
    await expect(page.getByText("just 3 reports within 48 hours")).toBeVisible();
    await page.getByLabel("Which dish?").fill("Paneer curry");
    await page.getByLabel("Describe what happened").fill(`E2E: stomach cramps after dinner (${i})`);
    await page.getByRole("button", { name: "Submit report" }).click();
    await expect(page.getByText("Thanks — your report is recorded.")).toBeVisible();
    if (i < 3) await expect(page.getByText(`${i} of 3 reports needed`)).toBeVisible();
    else await expect(page.getByText("Your report confirmed a pattern")).toBeVisible();
    expect(problems).toEqual([]);
    await context.close();
  }
});

test("the public dashboard shows the alert without identities", async ({ page }) => {
  const problems = watchForProblems(page);
  await page.goto("/");
  const card = page.locator(".status-card", { hasText: "Mess A - North Block" });
  await expect(card).toContainText("High");
  await expect(card).toContainText("not yet notified");    // honest: no contacts configured
  const body = await page.locator("main").innerText();
  expect(body).not.toContain("@sample-college.edu");
  expect(body).not.toContain("stomach cramps");            // complaint text stays private
  expect(problems).toEqual([]);
});

test("mess head works the alert with proof; principal verifies it", async ({ browser }) => {
  const admin = await browser.newContext();
  await createStaff(admin, { name: "Head Mess A", email: "head@e2e.test", role: "mess_head", mess_id: HALL_A });
  await createStaff(admin, { name: "Principal E2E", email: "principal@e2e.test", role: "principal" });
  await admin.close();

  // Mess head
  const headCtx = await browser.newContext();
  const head = await headCtx.newPage();
  const problems = watchForProblems(head);
  await staffSignInUi(head, "head@e2e.test");
  await expect(head).toHaveURL(/\/admin\/alerts/);           // mess heads land on alerts
  await head.locator("tbody tr", { hasText: "Mess A - North Block" }).first().click();
  await expect(head.getByRole("heading", { name: /Alert #\d+ · Mess A/ })).toBeVisible();
  const alertUrl = head.url();

  await head.getByRole("button", { name: "Acknowledge" }).click();
  await expect(head.locator(".detail .pill").first()).toHaveText("Acknowledged");

  const proof = head.locator("section", { has: head.getByRole("heading", { name: "Add proof of the fix" }) });
  await proof.locator('input[type="file"]').setInputFiles({ name: "after.png", mimeType: "image/png", buffer: PNG });
  await proof.getByRole("button", { name: "Add evidence" }).click();
  await expect(head.locator("section", { has: head.getByRole("heading", { name: "Evidence" }) }).locator("img")).toBeVisible();

  const nextStep = head.locator("section", { has: head.getByRole("heading", { name: "Next step" }) });
  await expect(nextStep.getByRole("button", { name: "Mark fixed" })).toBeDisabled();       // note required
  await nextStep.locator("textarea").fill("Kitchen deep-cleaned, paneer supplier changed.");
  await nextStep.getByRole("button", { name: "Mark fixed" }).click();
  await expect(head.locator(".detail .pill").first()).toHaveText("Fix awaiting check");
  await expect(head.getByRole("button", { name: "Verify & close" })).toHaveCount(0);       // can't verify own fix
  expect(problems).toEqual([]);
  await headCtx.close();

  // Principal — must set up two-factor sign-in before doing anything.
  const prCtx = await browser.newContext();
  const pr = await prCtx.newPage();
  await staffSignInUi(pr, "principal@e2e.test");
  const blocked = await prCtx.request.get(`${API}/staff/alerts`);
  expect(blocked.status()).toBe(403);
  await completeTwoFactorSetup(pr, "principal@e2e.test");
  await expect(pr.locator(".tab-btn", { hasText: "Alerts" }).locator(".badge")).toBeVisible();   // in-app "work waiting"
  await pr.goto(alertUrl.replace(/^https?:\/\/[^/]+/, ""));
  const step = pr.locator("section", { has: pr.getByRole("heading", { name: "Next step" }) });
  await step.locator("textarea").fill("Checked the kitchen in person.");
  await step.getByRole("button", { name: "Verify & close" }).click();
  await expect(pr.locator(".detail .pill").first()).toHaveText("Resolved");
  await expect(pr.locator(".timeline")).toContainText("Marked fixed");
  await prCtx.close();

  // Next sign-in needs the authenticator code.
  const again = await browser.newContext();
  const page2 = await again.newPage();
  await staffSignInUi(page2, "principal@e2e.test");
  await expect(page2.locator(".staff-bar")).toContainText("Principal E2E");
  await again.close();
});

test("students see their report resolved", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInStudent(context, "student1@sample-college.edu", "Student 1");
  await page.goto("/my-reports");
  await expect(page.getByText(/^Resolved /)).toBeVisible();
  await context.close();
});

test("live activity updates without a reload", async ({ browser }) => {
  const adminCtx = await browser.newContext();
  const page = await adminCtx.newPage();
  await staffSignInUi(page, "admin@e2e.test", "e2e-admin-pass");
  await page.goto("/admin/activity");
  await expect(page.locator(".live-pill")).toContainText("Live");

  const student = await browser.newContext();
  await signInStudent(student, "live@sample-college.edu", "Live");
  await student.request.post(`${API}/me/consent`, { data: { version: "2026-10" }, headers: { "X-TrayTrack": "1" } });
  const r = await student.request.post(`${API}/complaints`, {
    headers: { "X-TrayTrack": "1" },
    multipart: { mess_id: "2", category: "Too oily", description: "E2E live feed check" },
  });
  expect(r.ok(), await r.text()).toBeTruthy();
  await expect(page.locator(".activity-item").first()).toContainText("Too oily");
  await student.close();
  await adminCtx.close();
});

test("sessions are HttpOnly cookies, never readable by page scripts", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInStudent(context, "student2@sample-college.edu");
  const res = await page.goto("/my-reports");
  expect(res.headers()["content-security-policy"]).toContain("script-src 'self'");
  const visible = await page.evaluate(() => ({ cookie: document.cookie, storage: JSON.stringify(localStorage) }));
  expect(visible.cookie).not.toContain("tt_student");
  expect(visible.storage).not.toMatch(/token/i);
  const cookies = await context.cookies(API);
  expect(cookies.find((c) => c.name === "tt_student")?.httpOnly).toBe(true);

  // Sign out really ends the session server-side.
  await page.getByRole("button", { name: "Sign out" }).click();
  const me = await context.request.get(`${API}/me`);
  expect(me.status()).toBe(401);
  await context.close();
});

test("a forged cross-site write without the CSRF header is refused", async ({ browser }) => {
  const context = await browser.newContext();
  await staffApi(context);   // signed in as admin (cookie set)
  const forged = await context.request.post(`${API}/staff/mess-halls`, { data: { college_id: 1, name: "Forged" } });
  expect(forged.status()).toBe(403);
  await context.close();
});

test("Google Sign-In loads under the strict CSP, and only where needed", async ({ page }) => {
  const problems = watchForProblems(page);
  const googleScripts = [];
  page.on("request", (r) => r.url().includes("accounts.google.com/gsi/client") && googleScripts.push(r.url()));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Mess food safety" })).toBeVisible();
  expect(googleScripts, "Google's script must not load on the dashboard").toEqual([]);

  const res = await page.goto("/report");
  const nonce = await page.locator('meta[name="csp-nonce"]').getAttribute("content");
  expect(nonce).toMatch(/^[0-9a-f]{32}$/);
  expect(res.headers()["content-security-policy"]).toContain(`'nonce-${nonce}'`);
  // Google renders its button in an iframe and injects one nonce'd <style>.
  await expect(page.locator('iframe[src*="accounts.google.com/gsi"]')).toBeAttached({ timeout: 20_000 });
  // Browsers hide nonce attribute values from the DOM (so injected scripts
  // can't read them); the element's .nonce property still has it.
  const styleNonce = await page.locator("style#googleidentityservice_button_styles").evaluate((el) => el.nonce);
  expect(styleNonce).toBe(nonce);
  expect(googleScripts.length).toBe(1);
  expect(problems).toEqual([]);

  // A different page load gets a different nonce.
  await page.reload();
  expect(await page.locator('meta[name="csp-nonce"]').getAttribute("content")).not.toBe(nonce);
});
