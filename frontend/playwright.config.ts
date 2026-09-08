import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * Real-browser acceptance suite for Phase 18. Deliberately runs against the
 * REAL backend (Django + the project's Postgres/Redis containers) for the
 * genuine auth/workspace flows — synthetic data created in
 * `e2e/global-setup.ts`, cleaned up in `e2e/global-teardown.ts` — and uses
 * Playwright's own request interception only for the narrow set of failure
 * cases that are impractical to induce against a real, healthy backend
 * (a hung/failed request). See frontend/README.md, "End-to-end tests".
 *
 * Both frontend and backend are started by this config's `webServer` array
 * so the suite is self-contained and deterministic: `docker compose up -d
 * db redis` (from the repo root) must already be running, but nothing else.
 * The frontend is built and started in PRODUCTION mode (`next build` +
 * `next start`), not `next dev`, per Phase 18's build-integrity requirement.
 */
const FRONTEND_URL = "http://localhost:3000";
const BACKEND_URL = "http://localhost:8000";
const BACKEND_ROOT = path.resolve(__dirname, "..", "backend");
const PYTHON = path.join(BACKEND_ROOT, "venv", "Scripts", "python.exe");

export default defineConfig({
  testDir: "./e2e",
  globalSetup: require.resolve("./e2e/global-setup"),
  globalTeardown: require.resolve("./e2e/global-teardown"),
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false, // shared synthetic backend data — avoid cross-test interference
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: FRONTEND_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `"${PYTHON}" manage.py runserver 127.0.0.1:8000 --noreload`,
      cwd: BACKEND_ROOT,
      url: `${BACKEND_URL}/api/v1/auth/csrf/`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: "pipe",
      // No backend file/setting is changed: AUTH_LOGIN_THROTTLE_RATE and
      // AUTH_REFRESH_THROTTLE_RATE are already environment-driven knobs
      // (config/settings.py, defaults "10/min"/"30/min", same mechanism as
      // DATABASE_URL/ALLOWED_HOSTS/etc.) — overridden for this E2E process
      // only, because a real end-to-end suite performs many more real
      // logins/refreshes in a few minutes than the production
      // abuse-prevention thresholds allow for a normal user (every page
      // load bootstraps via a real refresh call too). Everything else about
      // login/refresh (CSRF, credential checks, cookie issuance/rotation)
      // is exercised completely unmodified.
      env: { AUTH_LOGIN_THROTTLE_RATE: "1000/min", AUTH_REFRESH_THROTTLE_RATE: "1000/min" },
    },
    {
      command: "npm run build && npm run start",
      cwd: __dirname,
      url: FRONTEND_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: { NEXT_PUBLIC_API_BASE_URL: BACKEND_URL },
      stdout: "pipe",
    },
  ],
});
