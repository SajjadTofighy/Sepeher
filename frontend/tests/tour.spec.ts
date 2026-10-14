import { test, expect } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("/api/v1/demo/reset");
});

test("five-minute demo runs detection, dispatch, closure and replay end to end", async ({
  page,
}) => {
  test.setTimeout(150000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "نمایش ۵ دقیقه‌ای" }).click();
  const tour = page.getByRole("region", { name: "تور نمایش پنج‌دقیقه‌ای" });
  const primary = tour.locator("footer .primary");
  await expect(tour).toContainText("وضعیت عادی");

  await primary.click();
  await expect(tour).toContainText("موتور سیاست ورود را تشخیص داد", {
    timeout: 30000,
  });
  await expect(page.locator(".gl-zone.alert")).toHaveCount(1);

  await primary.click();
  await primary.click();
  await expect(tour).toContainText("پیشنهاد سامانه");
  await expect(page.locator(".gl-eta").first()).toBeVisible();

  await primary.click();
  await primary.click();
  await expect(page.locator(".gl-eta.dispatched")).toBeVisible();
  await expect(tour).toContainText("به محل رسید", { timeout: 70000 });

  await primary.click();
  await primary.click();
  await expect(tour.locator(".tour-insight")).toContainText("POL-01");
  await expect(tour).toContainText("نقشه راه");

  await primary.click();
  await primary.click();
  await expect(tour.locator(".tour-metrics b")).toHaveCount(4);
  await expect(page.locator(".gl-zone.alert")).toHaveCount(0);

  await primary.click();
  await primary.click();
  await expect(page).toHaveURL(/#replay/);
  await primary.click();
  await expect(tour).toHaveCount(0);

  const audit = await (await page.request.get("/api/v1/audit/verify")).json();
  expect(audit.valid).toBeTruthy();
  expect(errors).toEqual([]);
});
