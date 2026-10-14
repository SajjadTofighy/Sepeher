import type { Feature, FeatureCollection, Geometry, Position } from "geojson";
import type { RuntimeSettings } from "../../types";

export const MAX_GEOJSON_BYTES = 5 * 1024 * 1024;
const EARTH_RADIUS = 6371008.8;
const radians = (n: number) => (n * Math.PI) / 180;

/** Presentation ring for a radius in metres; backend owns exposure decisions. */
export function circleRing(center: number[], radius: number): Position[] {
  const [lon, lat] = center.map(radians),
    angle = radius / EARTH_RADIUS;
  return Array.from({ length: 65 }, (_, i) => {
    const bearing = (i * Math.PI) / 32;
    const y = Math.asin(
      Math.sin(lat) * Math.cos(angle) +
        Math.cos(lat) * Math.sin(angle) * Math.cos(bearing),
    );
    const x =
      lon +
      Math.atan2(
        Math.sin(bearing) * Math.sin(angle) * Math.cos(lat),
        Math.cos(angle) - Math.sin(lat) * Math.sin(y),
      );
    return [(x * 180) / Math.PI, (y * 180) / Math.PI];
  });
}
const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);

/** GeoJSON coordinates are longitude, latitude in WGS 84 (RFC 7946). */
export function parseGeoJSON(value: unknown): FeatureCollection {
  let count = 0;
  function position(p: unknown): asserts p is Position {
    if (
      !Array.isArray(p) ||
      p.length < 2 ||
      p.length > 3 ||
      p.some((n) => typeof n !== "number" || !Number.isFinite(n)) ||
      Math.abs(p[0]) > 180 ||
      Math.abs(p[1]) > 85.051129
    )
      throw new Error("مختصات باید طول و عرض جغرافیایی معتبر WGS 84 باشند.");
    if (++count > 100000)
      throw new Error(
        "فایل بیش از ۱۰۰٬۰۰۰ نقطه دارد؛ آن را به لایه‌های کوچک‌تر تقسیم کنید.",
      );
  }
  function line(v: unknown, ring = false) {
    if (!Array.isArray(v) || v.length < (ring ? 4 : 2))
      throw new Error("هندسهٔ خط یا چندضلعی کامل نیست.");
    v.forEach(position);
    if (
      ring &&
      (v[0][0] !== v[v.length - 1][0] || v[0][1] !== v[v.length - 1][1])
    )
      throw new Error(
        "حلقهٔ چندضلعی باید بسته باشد؛ نقطهٔ اول و آخر یکسان باشند.",
      );
  }
  function geometry(v: unknown, depth = 0): asserts v is Geometry {
    if (!object(v) || depth > 8) throw new Error("هندسهٔ GeoJSON معتبر نیست.");
    const c = v.coordinates;
    const each = (fn: (x: unknown) => void) => {
      if (!Array.isArray(c) || !c.length)
        throw new Error("مختصات هندسه خالی است.");
      c.forEach(fn);
    };
    switch (v.type) {
      case "Point":
        position(c);
        break;
      case "MultiPoint":
        each(position);
        break;
      case "LineString":
        line(c);
        break;
      case "MultiLineString":
        each((v) => line(v));
        break;
      case "Polygon":
        each((v) => line(v, true));
        break;
      case "MultiPolygon":
        each((v) => {
          if (!Array.isArray(v) || !v.length)
            throw new Error("چندضلعی خالی است.");
          v.forEach((r) => line(r, true));
        });
        break;
      case "GeometryCollection":
        if (!Array.isArray(v.geometries) || !v.geometries.length)
          throw new Error("مجموعهٔ هندسه خالی است.");
        v.geometries.forEach((g) => geometry(g, depth + 1));
        break;
      default:
        throw new Error("نوع هندسهٔ GeoJSON پشتیبانی نمی‌شود.");
    }
  }
  if (!object(value)) throw new Error("فایل GeoJSON معتبر نیست.");
  if (value.crs && !/4326|CRS84/i.test(JSON.stringify(value.crs)))
    throw new Error("ابتدا داده را به WGS 84 / EPSG:4326 تبدیل کنید.");
  const features =
    value.type === "FeatureCollection"
      ? value.features
      : value.type === "Feature"
        ? [value]
        : [{ type: "Feature", properties: {}, geometry: value }];
  if (!Array.isArray(features) || features.length > 5000)
    throw new Error("هر لایه باید حداکثر ۵٬۰۰۰ عارضه داشته باشد.");
  for (const f of features) {
    if (
      !object(f) ||
      f.type !== "Feature" ||
      (f.properties != null && !object(f.properties))
    )
      throw new Error("ساختار عارضهٔ GeoJSON معتبر نیست.");
    geometry(f.geometry);
  }
  return { type: "FeatureCollection", features: features as Feature[] };
}
export function allPositions(data: FeatureCollection): Position[] {
  const points: Position[] = [];
  const visit = (v: unknown): void => {
    if (!Array.isArray(v)) return;
    if (typeof v[0] === "number") points.push(v as Position);
    else v.forEach(visit);
  };
  const geom = (g: Geometry | null): void => {
    if (!g) return;
    if (g.type === "GeometryCollection") g.geometries.forEach(geom);
    else visit(g.coordinates);
  };
  data.features.forEach((f) => geom(f.geometry));
  return points;
}
export function distanceMetres(points: Position[]): number {
  return points.slice(1).reduce((sum, p, i) => {
    const a = points[i],
      dlat = radians(p[1] - a[1]),
      dlon = radians(p[0] - a[0]);
    const h =
      Math.sin(dlat / 2) ** 2 +
      Math.cos(radians(a[1])) *
        Math.cos(radians(p[1])) *
        Math.sin(dlon / 2) ** 2;
    return sum + 2 * EARTH_RADIUS * Math.asin(Math.sqrt(Math.min(1, h)));
  }, 0);
}
export function areaSquareMetres(points: Position[]): number {
  if (points.length < 3) return 0;
  return Math.abs(
    (points.reduce((sum, p, i) => {
      const next = points[(i + 1) % points.length];
      const delta = radians(next[0] - p[0]);
      return (
        sum +
        Math.atan2(Math.sin(delta), Math.cos(delta)) *
          (2 + Math.sin(radians(p[1])) + Math.sin(radians(next[1])))
      );
    }, 0) *
      EARTH_RADIUS ** 2) /
      2,
  );
}
export function serviceURL(settings: RuntimeSettings): URL {
  const url = new URL(settings.gis_url);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  )
    throw new Error(
      "آدرس سرویس باید HTTP یا HTTPS و بدون نام کاربری و گذرواژه باشد.",
    );
  const replaced = [
    "service",
    "request",
    "version",
    "layers",
    "styles",
    "format",
    "transparent",
    "srs",
    "crs",
    "bbox",
    "width",
    "height",
    "typenames",
    "typename",
    "outputformat",
    "srsname",
    "count",
    "maxfeatures",
    "startindex",
  ];
  [...url.searchParams.keys()].forEach((key) => {
    if (replaced.includes(key.toLowerCase())) url.searchParams.delete(key);
  });
  url.hash = "";
  return url;
}
export function wmsTileURL(settings: RuntimeSettings): string {
  const url = serviceURL(settings);
  const version = settings.gis_wms_version || "1.3.0";
  Object.entries({
    service: "WMS",
    request: "GetMap",
    version,
    layers: settings.gis_layers,
    styles: "",
    format: "image/png",
    transparent: "true",
    [version === "1.3.0" ? "crs" : "srs"]: "EPSG:3857",
    bbox: "{bbox-epsg-3857}",
    width: "256",
    height: "256",
  }).forEach(([k, v]) => url.searchParams.set(k, v));
  return url.toString().replace(/%7Bbbox-epsg-3857%7D/gi, "{bbox-epsg-3857}");
}
export function wfsURL(settings: RuntimeSettings): string {
  const url = serviceURL(settings),
    version = settings.gis_wfs_version || "2.0.0";
  Object.entries({
    service: "WFS",
    request: "GetFeature",
    version,
    [version === "2.0.0" ? "typeNames" : "typeName"]: settings.gis_layers,
    outputFormat: "application/json",
    srsName: "EPSG:4326",
    [version === "2.0.0" ? "count" : "maxFeatures"]: "5000",
  }).forEach(([k, v]) => url.searchParams.set(k, v));
  return url.toString();
}
export async function fetchWFS(
  settings: RuntimeSettings,
  signal?: AbortSignal,
): Promise<{ data: FeatureCollection; limited: boolean }> {
  const response = await fetch(wfsURL(settings), {
    signal,
    credentials: "omit",
  });
  if (!response.ok) throw new Error(`سرویس WFS پاسخ ${response.status} داد.`);
  const reader = response.body?.getReader();
  if (!reader) throw new Error("پاسخ سرویس خالی است.");
  const decoder = new TextDecoder();
  let size = 0,
    text = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_GEOJSON_BYTES)
        throw new Error(
          "پاسخ WFS بیش از ۵ مگابایت است؛ لایهٔ کوچک‌تری انتخاب کنید.",
        );
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
  } finally {
    await reader.cancel();
  }
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new Error(
      "سرویس باید GeoJSON برگرداند؛ نام لایه و پشتیبانی application/json را بررسی کنید.",
    );
  }
  const data = parseGeoJSON(raw);
  const matched = object(raw)
    ? Number(raw.numberMatched ?? raw.totalFeatures)
    : NaN;
  return {
    data,
    limited: data.features.length >= 5000 || matched > data.features.length,
  };
}
