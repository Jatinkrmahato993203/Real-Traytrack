// Phone-sized checks (Pixel 7 viewport, touch, mobile user agent), with
// full-page screenshots saved to e2e-screenshots/ for a human to look at.
import { expect, test } from "@playwright/test";
import { acceptPrivacyIfAsked, HALL_A, signInStudent, staffSignInUi } from "./helpers";

async function noSidewaysScroll(page) {
  const { scroll, width } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth, width: window.innerWidth,
  }));
  expect(scroll, "page scrolls sideways on a phone").toBeLessThanOrEqual(width + 1);
}

test("phone: menu, dashboard and report form", async ({ page, context }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Menu/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "Report a problem" }).first()).toBeHidden();   // nav collapsed
  await noSidewaysScroll(page);
  await page.screenshot({ path: "e2e-screenshots/mobile-dashboard.png", fullPage: true });

  await page.getByRole("button", { name: /Menu/ }).click();
  await expect(page.locator("#main-nav").getByRole("link", { name: "Report a problem" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/mobile-menu.png" });

  await signInStudent(context, "phone@sample-college.edu", "Phone User");
  await page.goto(`/report?mess=${HALL_A}`);
  await acceptPrivacyIfAsked(page);
  await expect(page.getByRole("heading", { name: "Report a problem" })).toBeVisible();
  await noSidewaysScroll(page);
  await page.screenshot({ path: "e2e-screenshots/mobile-report.png", fullPage: true });

  // Hindi
  await page.getByRole("button", { name: "हिंदी" }).click();
  await expect(page.getByRole("heading", { name: "शिकायत करें" })).toBeVisible();
  await page.screenshot({ path: "e2e-screenshots/mobile-report-hindi.png", fullPage: true });
  await page.getByRole("button", { name: "English" }).click();

  await page.goto("/my-reports");
  await noSidewaysScroll(page);
  await page.screenshot({ path: "e2e-screenshots/mobile-my-reports.png", fullPage: true });
});

test("phone: staff alerts list becomes cards", async ({ page }) => {
  await staffSignInUi(page, "admin@e2e.test", "e2e-admin-pass");
  await page.goto("/admin/alerts");
  await page.getByLabel("Status").selectOption("all");
  const row = page.locator(".data-table tbody tr").first();
  await expect(row).toBeVisible();
  // On a phone each row is a card: its cells stack (display: block/flex), headers hidden.
  expect(await row.evaluate((el) => getComputedStyle(el).display)).toBe("block");
  await noSidewaysScroll(page);
  await page.screenshot({ path: "e2e-screenshots/mobile-staff-alerts.png", fullPage: true });

  await page.goto("/admin/inspections");
  await expect(page.locator(".data-table tbody tr").first()).toBeVisible();
  await noSidewaysScroll(page);
  await page.screenshot({ path: "e2e-screenshots/mobile-staff-inspections.png", fullPage: true });
});
