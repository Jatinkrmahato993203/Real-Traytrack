import { expect, test } from "@playwright/test";
import { createStaff, HALL_B, staffSignInUi, watchForProblems } from "./helpers";

test("an inspection can't be submitted until every item is answered", async ({ browser }) => {
  const admin = await browser.newContext();
  await createStaff(admin, { name: "Inspector E2E", email: "inspector@e2e.test", role: "inspector" });
  await admin.close();

  const context = await browser.newContext();
  const page = await context.newPage();
  const problems = watchForProblems(page);
  await staffSignInUi(page, "inspector@e2e.test");
  await expect(page).toHaveURL(/\/admin\/inspections/);       // inspectors land on their to-do list
  await expect(page.getByText("Due now — never inspected").first()).toBeVisible();

  await page.goto(`/admin/inspections/new?mess=${HALL_B}`);
  await page.getByRole("button", { name: /Submit inspection/ }).click();
  await expect(page.getByText(/Answer every item — 12 left/)).toBeVisible();
  await expect(page.locator(".check-item.missing")).toHaveCount(12);

  // Nothing is pre-ticked: answer each one.
  const items = page.locator(".check-item");
  for (let i = 0; i < 12; i++) await items.nth(i).getByText("Pass", { exact: true }).click();
  await items.nth(11).getByText("N/A", { exact: true }).click();   // e.g. licence not applicable here
  await expect(page.getByText("12 of 12 answered")).toBeVisible();

  // The draft survives a reload (dead spots in kitchens).
  await page.reload();
  await expect(page.getByText("12 of 12 answered")).toBeVisible();

  await page.getByRole("button", { name: /Submit inspection/ }).click();
  await expect(page.getByText("No issues found, so no alert was raised.")).toBeVisible();
  await expect(page.getByText("Not verified on site")).toBeVisible();   // no kitchen code entered
  expect(problems).toEqual([]);
  await context.close();
});
