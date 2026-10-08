const { chromium } = require("playwright");
const path = require("path");

const baseURL = process.env.WORKBENCH_CAPTURE_URL || "http://127.0.0.1:8877";
const outputPath = path.resolve(
  __dirname,
  "../../site/assets/images/workbench-overview.png",
);

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 760 } });
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.locator("#run-topic").waitFor({ state: "visible" });

  if ((await page.locator("html").getAttribute("lang")) !== "en") {
    await page.locator("#language-toggle").click();
    await page.locator("html[lang='en']").waitFor({ state: "attached" });
  }

  await page.locator("#candidates-body .candidate-row").first().click();
  await page.locator("#candidate-content").waitFor({ state: "visible" });

  await page.locator("#database-path").evaluate((element) => {
    element.textContent = "Local SQLite database";
  });
  await page.locator("#artifact-root").evaluate((element) => {
    element.textContent = "Run-scoped local artifacts";
  });
  await page.locator("#command-panel").evaluate((element) => {
    element.hidden = true;
  });

  await page.screenshot({ path: outputPath, fullPage: false });
  await browser.close();
})();
