import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live-network.spec.ts",
  outputDir: "/tmp/marzban-dashboard-live-playwright",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.E2E_DASHBOARD_URL || "https://127.0.0.1:18444/dashboard/",
    ignoreHTTPSErrors: true,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "live-desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 960 } },
    },
  ],
});
