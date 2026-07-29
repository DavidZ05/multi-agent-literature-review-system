const { defineConfig } = require("@playwright/test");

const port = Number(process.env.WORKBENCH_E2E_PORT || 8876);
const browserUse = process.env.PLAYWRIGHT_CHANNEL
  ? { channel: process.env.PLAYWRIGHT_CHANNEL }
  : {};

module.exports = defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: "output/playwright/test-results",
  reporter: [["line"], ["html", {
    outputFolder: "output/playwright/report",
    open: "never"
  }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  webServer: {
    command: "python3 tests/browser/serve_workbench.py",
    url: `http://127.0.0.1:${port}`,
    timeout: 30_000,
    reuseExistingServer: false
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium", ...browserUse } }
  ]
});
