const { defineConfig } = require("@playwright/test");

const port = Number(process.env.DOCS_E2E_PORT || 8878);
const browserUse = process.env.PLAYWRIGHT_CHANNEL
  ? { channel: process.env.PLAYWRIGHT_CHANNEL }
  : {};

module.exports = defineConfig({
  testDir: "./tests/browser",
  testMatch: "docs-site.spec.js",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  outputDir: "output/playwright/docs-results",
  reporter: [["line"], ["html", {
    outputFolder: "output/playwright/docs-report",
    open: "never"
  }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure"
  },
  webServer: {
    command: `python3 -m http.server ${port} --bind 127.0.0.1 --directory output/site`,
    url: `http://127.0.0.1:${port}`,
    timeout: 30_000,
    reuseExistingServer: false
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium", ...browserUse } }
  ]
});
