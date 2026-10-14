import { test, expect } from "@playwright/test";
import {
  visibleTrack,
  playbackPosition,
} from "../src/features/command/trackPlayback";
import type { Asset } from "../src/types";

test("route playback uses timestamps and handles empty and long histories", () => {
  const track = [0, 1, 2, 20, 40, 60, 80, 99, 100].map((minute) => ({
    lon: 49 + minute / 1000,
    lat: 30,
    time: new Date(Date.UTC(2026, 0, 1, 0, minute)).toISOString(),
  }));
  expect(visibleTrack(track, 50)).toEqual(track.slice(0, 5));
  expect(visibleTrack(track, 0)).toEqual(track.slice(0, 1));
  expect(visibleTrack(track, 100)).toEqual(track);
  expect(visibleTrack([], 50)).toEqual([]);
  expect(visibleTrack(track.slice(0, 1), 50)).toEqual(track.slice(0, 1));
  const asset = { lon: 49.1, lat: 30, track } as Asset;
  expect(playbackPosition(asset, 99)).toEqual(track[7]);
  expect(playbackPosition({ ...asset, track: [] }, 50).lon).toBe(asset.lon);
});

test("command map spans the card, floats events, and supports fullscreen with route controls", async ({
  page,
}) => {
  await page.request.post("/api/v1/demo/reset");
  await page.goto("/");
  const map = page.locator(".command-map-viewport");
  await expect(map).toBeVisible();
  await expect(page.locator(".floating-events")).toBeVisible();
  const mapBox = (await map.boundingBox())!;
  const cardBox = (await page.locator(".map-card").boundingBox())!;
  expect(Math.abs(mapBox.width - cardBox.width)).toBeLessThan(4);
  const eventsBox = (await page.locator(".floating-events").boundingBox())!;
  expect(eventsBox.x).toBeGreaterThan(mapBox.x);
  expect(eventsBox.x + eventsBox.width).toBeLessThan(mapBox.x + mapBox.width);
  await page.getByRole("button", { name: "جمع‌کردن رخدادها" }).click();
  await expect(page.locator(".floating-events")).toHaveCount(0);
  await page
    .getByRole("button", { name: "نمایش مسیر خودروها", exact: true })
    .click();
  await page.getByRole("button", { name: "لایه‌ها", exact: true }).click();
  const tracks = page.getByRole("checkbox", {
    name: "مسیر حرکت خودروها",
    exact: true,
  });
  await expect(tracks).toBeChecked();
  await tracks.uncheck();
  await expect(tracks).not.toBeChecked();
  await tracks.check();
  await page.getByRole("button", { name: "لایه‌ها", exact: true }).click();
  await page
    .getByRole("button", { name: "نقشه تمام‌صفحه", exact: true })
    .click();
  await expect(map).toHaveAttribute("data-fullscreen", "true");
  expect(await page.evaluate(() => !!document.fullscreenElement)).toBeTruthy();
  const fullBox = (await map.boundingBox())!;
  expect(fullBox.width).toBe(page.viewportSize()!.width);
  expect(fullBox.height).toBe(page.viewportSize()!.height);
  await page
    .getByRole("button", { name: "نمایش رخدادها", exact: true })
    .click();
  await page
    .getByRole("button", { name: /بحرانی.*ورود به محدوده حفاظت‌شده/ })
    .click();
  await expect(page.locator("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "خروج از تمام‌صفحه", exact: true })
    .click();
  await expect(map).toHaveAttribute("data-fullscreen", "false");
});

test("fullscreen fallback exits with Escape and mobile cards remain collapsible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    Element.prototype.requestFullscreen = () =>
      Promise.reject(new Error("Unavailable"));
  });
  await page.goto("/");
  await expect(page.locator(".floating-events")).toHaveCount(0);
  await page
    .getByRole("button", { name: "نمایش رخدادها", exact: true })
    .click();
  await expect(page.locator(".floating-events")).toBeVisible();
  await page.getByRole("button", { name: "جمع‌کردن رخدادها" }).click();
  await page
    .getByRole("button", { name: "نقشه تمام‌صفحه", exact: true })
    .click();
  await expect(page.locator(".map-viewport")).toHaveClass(
    /fullscreen-fallback/,
  );
  await page.keyboard.press("Escape");
  await expect(page.locator(".map-viewport")).toHaveAttribute(
    "data-fullscreen",
    "false",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
