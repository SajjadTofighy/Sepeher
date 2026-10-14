import { test, expect } from "@playwright/test";
import {
  areaSquareMetres,
  distanceMetres,
  parseGeoJSON,
  wmsTileURL,
  wfsURL,
  fetchWFS,
} from "../src/features/geography/gis";
import type { RuntimeSettings } from "../src/types";
const settings = {
  gis_url: "https://gis.example.org/ows?SERVICE=old&BBOX=old&tenant=demo",
  gis_layers: "demo:roads",
  gis_wms_version: "1.3.0",
  gis_wfs_version: "2.0.0",
} as RuntimeSettings;
const sample = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "محدودهٔ تست امیدیه" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [49.694, 30.75],
            [49.71, 30.75],
            [49.71, 30.764],
            [49.694, 30.764],
            [49.694, 30.75],
          ],
        ],
      },
    },
    {
      type: "Feature",
      properties: { name: "نقطهٔ GIS امیدیه", code: "OMID-01" },
      geometry: { type: "Point", coordinates: [49.702, 30.757] },
    },
  ],
};
test("distance and area use geographic metres, not screen pixels", () => {
  expect(
    distanceMetres([
      [0, 0],
      [1, 0],
    ]),
  ).toBeCloseTo(111195.08, 1);
  expect(
    areaSquareMetres([
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ]) / 1e6,
  ).toBeCloseTo(12363.718, 2);
  expect(
    areaSquareMetres([
      [0, 0],
      [0, 1],
      [1, 1],
      [1, 0],
    ]),
  ).toBeCloseTo(
    areaSquareMetres([
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ]),
    2,
  );
});
test("GeoJSON validates geometry and coordinate systems before rendering", () => {
  expect(parseGeoJSON(sample).features).toHaveLength(2);
  expect(
    parseGeoJSON({ type: "FeatureCollection", features: [] }).features,
  ).toHaveLength(0);
  expect(() =>
    parseGeoJSON({ type: "Point", coordinates: [4900000, 3000000] }),
  ).toThrow(/WGS/);
  expect(() =>
    parseGeoJSON({
      type: "Polygon",
      coordinates: [
        [
          [49, 30],
          [50, 30],
          [50, 31],
          [49, 31],
        ],
      ],
    }),
  ).toThrow(/بسته/);
  expect(() =>
    parseGeoJSON({
      ...sample,
      crs: { type: "name", properties: { name: "EPSG:3857" } },
    }),
  ).toThrow(/WGS/);
});
test("OGC requests use correct versions, axes and bounded feature counts", () => {
  const wms = new URL(wmsTileURL(settings));
  expect(wms.searchParams.get("crs")).toBe("EPSG:3857");
  expect(wms.searchParams.get("bbox")).toBe("{bbox-epsg-3857}");
  expect(wms.searchParams.has("BBOX")).toBeFalsy();
  expect(wms.searchParams.get("tenant")).toBe("demo");
  expect(
    new URL(
      wmsTileURL({ ...settings, gis_wms_version: "1.1.1" }),
    ).searchParams.get("srs"),
  ).toBe("EPSG:3857");
  const wfs = new URL(wfsURL(settings));
  expect(wfs.searchParams.get("typeNames")).toBe("demo:roads");
  expect(wfs.searchParams.get("count")).toBe("5000");
  expect(
    new URL(wfsURL({ ...settings, gis_wfs_version: "1.1.0" })).searchParams.get(
      "maxFeatures",
    ),
  ).toBe("5000");
});
test("WFS detects truncation and rejects XML service exceptions", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ ...sample, numberMatched: 12 }));
    expect((await fetchWFS(settings)).limited).toBeTruthy();
    globalThis.fetch = async () =>
      new Response("<ServiceException>Invalid layer</ServiceException>");
    await expect(fetchWFS(settings)).rejects.toThrow(/GeoJSON/);
  } finally {
    globalThis.fetch = original;
  }
});

test.describe("GIS in Chrome", () => {
  test.beforeEach(async ({ request }) => {
    await request.post("/api/v1/demo/reset");
  });
  test("imports, inspects, hides, exports and measures a real-coordinate GeoJSON layer", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await expect(page.locator("[data-map-engine]")).toHaveAttribute(
      "data-map-engine",
      "maplibre",
    );
    await page
      .getByRole("button", { name: "ابزارهای GIS", exact: true })
      .click();
    await page.getByLabel("فایل GeoJSON").setInputFiles({
      name: "omidiyeh.geojson",
      mimeType: "application/geo+json",
      buffer: Buffer.from(JSON.stringify(sample)),
    });
    await expect(page.getByText("omidiyeh.geojson · ۲ عارضه")).toBeVisible();
    await page.waitForTimeout(800);
    await page.getByRole("button", { name: "جمع‌کردن رخدادها" }).click();
    const canvas = page.locator(".maplibregl-canvas");
    const box = (await canvas.boundingBox())!;
    await canvas.click({ position: { x: box.width / 2, y: box.height / 2 } });
    await expect(page.locator(".gis-feature-info")).toContainText("OMID-01");
    await page.locator(".maplibregl-popup-close-button").click();
    await page.getByLabel("omidiyeh.geojson · ۲ عارضه").uncheck();
    await page.getByLabel("omidiyeh.geojson · ۲ عارضه").check();
    const downloadPromise = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "خروجی لایه‌ها و اندازه‌گیری" })
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("sepehr-gis.geojson");
    const stream = await download.createReadStream();
    let text = "";
    for await (const chunk of stream!) text += chunk;
    expect(JSON.parse(text).features).toHaveLength(2);
    await page.getByRole("button", { name: "فاصله", exact: true }).click();
    await canvas.click({ position: { x: 180, y: 300 } });
    await canvas.click({ position: { x: 280, y: 330 } });
    await expect(page.locator(".gis-result")).not.toHaveText("۰ متر");
    await page.keyboard.press("Escape");
    await expect(page.getByText("اندازه‌گیری تکمیل شد.")).toBeVisible();
    await page.getByLabel("فایل GeoJSON").setInputFiles({
      name: "bad.geojson",
      mimeType: "application/json",
      buffer: Buffer.from("{broken"),
    });
    await expect(page.getByRole("alert")).toContainText("JSON معتبر نیست");
    expect(errors).toEqual([]);
  });
  test("WFS settings fetch features and WMS requests geographic tiles", async ({
    page,
    request,
  }) => {
    const config = await (await request.get("/api/v1/settings")).json();
    await request.put("/api/v1/settings", {
      data: {
        ...config,
        gis_mode: "wfs",
        gis_url: "https://gis.example.test/ows",
        gis_layers: "demo:roads",
      },
    });
    let wfsRequest: URL | undefined;
    await page.route("https://gis.example.test/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("service") === "WFS") {
        wfsRequest = url;
        await route.fulfill({ json: sample });
      } else
        await route.fulfill({
          contentType: "image/png",
          body: Buffer.from(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=",
            "base64",
          ),
        });
    });
    await page.goto("/");
    await page
      .getByRole("button", { name: "ابزارهای GIS", exact: true })
      .click();
    await expect(page.locator(".gis-service-status")).toContainText(
      "۲ عارضه دریافت شد",
    );
    expect(wfsRequest?.searchParams.get("srsName")).toBe("EPSG:4326");
    await page.getByRole("button", { name: "نمایش عوارض WFS" }).click();
    await page.getByLabel("WFS · demo:roads").uncheck();
    await expect(page.locator(".gis-service-status")).toHaveText(
      "لایه خاموش است",
    );
    await request.put("/api/v1/settings", {
      data: {
        ...config,
        gis_mode: "wms",
        gis_url: "https://gis.example.test/ows",
        gis_layers: "demo:roads",
        gis_wms_version: "1.3.0",
      },
    });
    const tile = page.waitForRequest(
      (r) => r.url().includes("gis.example.test") && r.url().includes("GetMap"),
    );
    await page.reload();
    const url = new URL((await tile).url());
    expect(url.searchParams.get("crs")).toBe("EPSG:3857");
    expect(url.searchParams.get("bbox")).toMatch(/^-?\d/);
    expect(url.searchParams.get("bbox")).not.toContain("{");
    await page
      .getByRole("button", { name: "ابزارهای GIS", exact: true })
      .click();
    await expect(page.locator(".gis-service-status")).toContainText("WMS");
  });
  test("real-map fallback works when WebGL is unavailable", async ({
    page,
  }) => {
    await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...args) {
        if (type === "webgl" || type === "webgl2") return null;
        return original.call(this, type, ...args);
      } as typeof original;
    });
    await page.goto("/");
    await expect(page.locator("[data-map-engine]")).toHaveAttribute(
      "data-map-engine",
      "raster",
    );
    await expect(page.locator(".street-tile").first()).toHaveAttribute(
      "src",
      /tile.openstreetmap.org/,
    );
    await page.getByRole("button", { name: "بزرگ‌نمایی", exact: true }).click();
    await expect(page.locator(".map-coordinate-bar")).toContainText("Z 14");
  });
});

test("map controls preserve layers and show street-level detail on mobile", async ({
  page,
  request,
}) => {
  await request.post("/api/v1/demo/reset");
  await page.goto("/");
  // The command map opens on the whole operational area; street level is one click away.
  await expect(page.locator(".map-coordinate-bar")).toContainText(/Z (9|10|11)\./);
  await page.getByRole("button", { name: "بازگشت به امیدیه" }).click();
  await expect(page.locator(".map-coordinate-bar")).toContainText("Z 14.0");
  await page.getByRole("button", { name: "بزرگ‌نمایی", exact: true }).click();
  await expect(page.locator(".map-coordinate-bar")).toContainText("Z 15.0");
  await page.getByRole("button", { name: "لایه‌ها", exact: true }).click();
  await page.getByLabel("نام خیابان‌ها و مکان‌ها").uncheck();
  await page.getByLabel("ساختمان‌ها").uncheck();
  await page.getByRole("button", { name: "خیابانی OSM" }).click();
  await expect(
    page.getByRole("button", { name: "خیابانی OSM" }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("ساختمان‌ها")).toBeDisabled();
  await page.getByRole("button", { name: "عملیاتی شب" }).click();
  await expect(page.getByLabel("ساختمان‌ها")).not.toBeChecked();
  await page.getByRole("button", { name: "لایه‌ها", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "ابزارهای GIS", exact: true }).click();
  const bounds = (await page.locator(".gis-panel").boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
test("operator configures a WFS connection through settings form", async ({
  page,
  request,
}) => {
  await request.post("/api/v1/demo/reset");
  await page.route("https://gis.example.test/**", (route) =>
    route.fulfill({ json: { type: "FeatureCollection", features: [] } }),
  );
  await page.goto("/#settings");
  await page.getByRole("button", { name: "اتصال GIS", exact: true }).click();
  await page.getByLabel("لایهٔ GIS سازمانی روی نقشه").selectOption("wfs");
  await page.getByLabel("آدرس سرویس").fill("https://gis.example.test/ows");
  await page.getByLabel("نام نوع عارضه WFS").fill("demo:roads");
  const saved = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/v1/settings") && r.request().method() === "PUT",
  );
  await page
    .getByRole("button", { name: "ذخیره تنظیمات", exact: true })
    .click();
  expect((await saved).status()).toBe(200);
  await page.goto("/");
  await page.getByRole("button", { name: "ابزارهای GIS", exact: true }).click();
  await expect(page.locator(".gis-service-status")).toContainText(
    "۰ عارضه دریافت شد",
  );
  await request.post("/api/v1/demo/reset");
});
