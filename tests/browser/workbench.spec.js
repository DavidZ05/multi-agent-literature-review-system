const { test, expect } = require("@playwright/test");

test("creates a local run, streams completion, and preserves selection", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Literature Review Workbench" })).toBeVisible();
  await expect(page.locator("#stream-state")).toHaveText("Connected");
  await page.locator("#new-run-button").click();
  await page.locator("#new-run-topic").fill("Browser recovery test");
  await page.locator("#new-run-discover").uncheck();
  await page.locator("#start-run-button").click();

  await expect(page.getByRole("dialog", { name: "New discovery run" })).not.toBeVisible();
  await expect(page.locator("#run-topic")).toHaveText("Browser recovery test");
  await expect(page.locator("#run-status")).toHaveText("Completed", { timeout: 15_000 });
  const selectedHref = await page.locator(".run-button.selected").getAttribute("href");
  expect(selectedHref).toContain("?run=run_");

  await page.reload();
  await expect(page.locator("#run-topic")).toHaveText("Browser recovery test");
  await expect(page.locator("#run-status")).toHaveText("Completed");
  await expect(page.locator("#stream-state")).toHaveText("Connected");
});

test("persists the bilingual interface preference", async ({ page }) => {
  await page.goto("/");
  await page.locator("#language-toggle").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.locator("#runs-heading")).toHaveText("研究任务");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
  await expect(page.locator("#stream-state")).toHaveText("已连接");
});
