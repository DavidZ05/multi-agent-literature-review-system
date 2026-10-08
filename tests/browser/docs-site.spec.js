const { test, expect } = require("@playwright/test");

test("renders the public documentation without responsive overflow", async ({ page }) => {
  const widths = [320, 375, 414, 768, 1440];

  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");

    await expect(page.getByRole("heading", {
      name: "Multi-Agent Literature Review System",
      level: 1
    })).toBeVisible();
    await expect(page.getByRole("link", { name: "Start locally" })).toBeVisible();

    const image = page.locator(".lr-workbench-shot img");
    await expect(image).toBeVisible();
    expect(await image.evaluate((element) => element.naturalWidth)).toBeGreaterThan(1000);

    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});

test("keeps the Chinese quick start reachable from navigation", async ({ page }) => {
  await page.goto("/zh/quick-start/");

  await expect(page.getByRole("heading", { name: "中文快速开始", level: 1 })).toBeVisible();
  await expect(page.getByText("该项目是本地优先的文献综述工作流。", { exact: false })).toBeVisible();
});
