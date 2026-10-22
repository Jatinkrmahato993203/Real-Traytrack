// Browser end-to-end tests: the real backend (fresh database, test sign-in)
// and the production build served by `vite preview` with the production
// Content-Security-Policy — so a CSP mistake fails the tests.
//
//   npx playwright test            # needs MySQL/MariaDB reachable via backend/.env
//
// Locally this uses the installed Microsoft Edge; set PW_CHANNEL=chromium
// (after `npx playwright install chromium`) to use Playwright's own browser.
import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8002;
const WEB_PORT = 5175;
const channel = process.env.PW_CHANNEL || "msedge";
const python = process.env.PYTHON || "python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,               // one shared database, tests build on each other in order
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "e2e-report", open: "never" }]],
  outputDir: "e2e-results",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: channel === "chromium" ? undefined : channel }, testIgnore: /mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: channel === "chromium" ? undefined : channel }, testMatch: /mobile/ },
    // Safari's engine at iPhone size — the closest to an iPhone without one.
    { name: "iphone", use: { ...devices["iPhone 14"] }, testMatch: /mobile/ },
  ],
  webServer: [
    {
      command: `${python} scripts/e2e_server.py --port ${API_PORT} --frontend http://localhost:${WEB_PORT}`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run build && npx vite preview --port ${WEB_PORT} --strictPort`,
      env: { VITE_API_BASE: `http://localhost:${API_PORT}`, VITE_GOOGLE_CLIENT_ID: "e2e-not-used.apps.googleusercontent.com" },
      url: `http://localhost:${WEB_PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
