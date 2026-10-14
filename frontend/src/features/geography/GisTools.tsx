import { useQuery } from "@tanstack/react-query";
import {
  Download,
  Layers,
  Ruler,
  Trash2,
  Upload,
  X,
  Undo2,
  LocateFixed,
  Check,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import maplibregl, {
  type Map as GLMap,
  type GeoJSONSource,
  type MapMouseEvent,
} from "maplibre-gl";
import type { FeatureCollection, Position } from "geojson";
import { api, fa } from "../../api";
import type { HazardArea, RuntimeSettings } from "../../types";
import { download } from "../../shared/lib/download";
import { collection, empty, feature } from "../command/mapStyle";
import {
  allPositions,
  circleRing,
  areaSquareMetres,
  distanceMetres,
  fetchWFS,
  MAX_GEOJSON_BYTES,
  parseGeoJSON,
  wmsTileURL,
} from "./gis";

function addVector(
  map: GLMap,
  id: string,
  data: FeatureCollection,
  color: string,
) {
  map.addSource(id, { type: "geojson", data });
  const before = map.getLayer("zone-fill") ? "zone-fill" : undefined;
  map.addLayer(
    {
      id: `${id}-fill`,
      type: "fill",
      source: id,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: { "fill-color": color, "fill-opacity": 0.18 },
    },
    before,
  );
  map.addLayer(
    {
      id: `${id}-line`,
      type: "line",
      source: id,
      filter: ["!=", ["geometry-type"], "Point"],
      paint: { "line-color": color, "line-width": 2.5 },
    },
    before,
  );
  map.addLayer(
    {
      id: `${id}-point`,
      type: "circle",
      source: id,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-color": color,
        "circle-radius": 6,
        "circle-stroke-color": "#10222b",
        "circle-stroke-width": 2,
      },
    },
    before,
  );
}
function removeVector(map: GLMap, id: string) {
  if (!map.getStyle()) return;
  ["fill", "line", "point"].forEach((suffix) => {
    if (map.getLayer(`${id}-${suffix}`)) map.removeLayer(`${id}-${suffix}`);
  });
  if (map.getSource(id)) map.removeSource(id);
}
export type HazardDrawing = {
  onSave: (area: HazardArea) => Promise<void>;
  onCancel: () => void;
  busy: boolean;
};
export default function GisTools({
  map,
  hazardDrawing,
}: {
  map: GLMap | null;
  hazardDrawing?: HazardDrawing;
}) {
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: ({ signal }) =>
      api<RuntimeSettings>("/settings", "GET", undefined, signal),
  });
  const [open, setOpen] = useState(false),
    [imported, setImported] = useState<FeatureCollection | null>(null),
    [filename, setFilename] = useState("");
  const [error, setError] = useState(""),
    [externalStatus, setExternalStatus] = useState(""),
    [externalData, setExternalData] = useState<FeatureCollection | null>(null);
  const [showImport, setShowImport] = useState(true),
    [showExternal, setShowExternal] = useState(true),
    [retry, setRetry] = useState(0);
  const [kind, setKind] = useState<"distance" | "area" | null>(null),
    [drawing, setDrawing] = useState(false),
    [points, setPoints] = useState<Position[]>([]);
  const [hazardKind, setHazardKind] = useState<"circle" | "polygon">("circle"),
    [radius, setRadius] = useState(200);
  const hazardRef = useRef({ active: !!hazardDrawing, kind: hazardKind });
  hazardRef.current = { active: !!hazardDrawing, kind: hazardKind };
  useEffect(() => {
    if (hazardDrawing) {
      setOpen(true);
      setKind("area");
      setPoints([]);
      setDrawing(true);
    } else {
      setDrawing(false);
      setKind(null);
      setPoints([]);
    }
  }, [!!hazardDrawing]);
  const fileInput = useRef<HTMLInputElement>(null),
    modeRef = useRef(drawing);
  modeRef.current = drawing;
  const distance = distanceMetres(
    kind === "area" && points.length > 2 ? [...points, points[0]] : points,
  );
  const area = kind === "area" ? areaSquareMetres(points) : 0;
  const measurement = collection([
    ...points.map((coordinates) => feature({ type: "Point", coordinates })),
    ...(hazardDrawing && hazardKind === "circle" && points.length && radius > 0
      ? [
          feature({
            type: "Polygon",
            coordinates: [circleRing(points[0], radius)],
          }),
        ]
      : points.length > 1
        ? [
            feature(
              kind === "area" && points.length > 2
                ? { type: "Polygon", coordinates: [[...points, points[0]]] }
                : { type: "LineString", coordinates: points },
              {
                name: "اندازه‌گیری",
                distance_m: distance,
                ...(kind === "area" ? { area_m2: area } : {}),
              },
            ),
          ]
        : []),
  ]);
  function fit(data: FeatureCollection) {
    if (!map) return;
    const positions = allPositions(data);
    if (!positions.length) return;
    const bounds = new maplibregl.LngLatBounds();
    positions.forEach((p) => bounds.extend([p[0], p[1]]));
    map.fitBounds(bounds, { padding: 75, maxZoom: 17, duration: 600 });
  }
  useEffect(() => {
    if (!map) return;
    addVector(map, "gis-import", empty, "#86bafa");
    addVector(map, "gis-measure", empty, "#f5cc74");
    const click = (e: MapMouseEvent) => {
      if (modeRef.current) {
        if (hazardRef.current.active && hazardRef.current.kind === "circle") {
          setPoints([[e.lngLat.lng, e.lngLat.lat]]);
          return;
        }
        setPoints((p) =>
          p.length < (hazardRef.current.active ? 100 : 1000)
            ? [...p, [e.lngLat.lng, e.lngLat.lat]]
            : p,
        );
        return;
      }
      const ids = [
        "gis-import-fill",
        "gis-import-line",
        "gis-import-point",
        "gis-service-fill",
        "gis-service-line",
        "gis-service-point",
      ].filter((id) => map.getLayer(id));
      const f = map.queryRenderedFeatures(e.point, { layers: ids })[0];
      if (!f) return;
      const el = document.createElement("div");
      el.className = "gis-feature-info";
      el.dir = "rtl";
      const title = document.createElement("strong");
      title.textContent = "مشخصات عارضه";
      el.append(title);
      const entries = Object.entries(f.properties || {}).slice(0, 12);
      if (!entries.length) {
        const row = document.createElement("p");
        row.textContent = "این عارضه اطلاعات توصیفی ندارد.";
        el.append(row);
      }
      entries.forEach(([k, v]) => {
        const row = document.createElement("p");
        row.textContent = `${k}: ${String(v).slice(0, 250)}`;
        el.append(row);
      });
      new maplibregl.Popup({ maxWidth: "300px" })
        .setLngLat(e.lngLat)
        .setDOMContent(el)
        .addTo(map);
    };
    map.on("click", click);
    return () => {
      map.off("click", click);
      removeVector(map, "gis-import");
      removeVector(map, "gis-measure");
    };
  }, [map]);
  useEffect(() => {
    if (map?.getSource("gis-import"))
      (map.getSource("gis-import") as GeoJSONSource).setData(imported || empty);
  }, [map, imported]);
  useEffect(() => {
    if (map?.getSource("gis-measure"))
      (map.getSource("gis-measure") as GeoJSONSource).setData(measurement);
  }, [map, points, kind, radius, hazardKind, !!hazardDrawing]);
  useEffect(() => {
    if (!map) return;
    map.getCanvas().style.cursor = drawing ? "crosshair" : "";
    if (drawing) map.doubleClickZoom.disable();
    else map.doubleClickZoom.enable();
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawing(false);
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      map.getCanvas().style.cursor = "";
      map.doubleClickZoom.enable();
    };
  }, [map, drawing]);
  const config = settings.data;
  useEffect(() => {
    if (!map || !config || config.gis_mode === "local" || !showExternal) {
      setExternalStatus("");
      setExternalData(null);
      return;
    }
    const controller = new AbortController();
    let timedOut = false;
    const timer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
      setExternalStatus("مهلت دریافت سرویس GIS تمام شد؛ دوباره تلاش کنید.");
    }, 20000);
    setExternalStatus("در حال اتصال به سرویس GIS…");
    setExternalData(null);
    const onError = (e: maplibregl.ErrorEvent) => {
      if ("sourceId" in e && e.sourceId === "gis-wms") {
        window.clearTimeout(timer);
        setExternalStatus(
          "دریافت WMS ناموفق بود؛ نشانی، نام لایه و مجوز CORS را بررسی کنید.",
        );
      }
    };
    const onData = (e: maplibregl.MapSourceDataEvent) => {
      if (e.sourceId === "gis-wms" && e.sourceDataType === "content") {
        window.clearTimeout(timer);
        setExternalStatus("WMS · لایهٔ تصویری متصل است");
      }
    };
    if (config.gis_mode === "wms") {
      try {
        map.on("error", onError);
        map.on("sourcedata", onData);
        map.addSource("gis-wms", {
          type: "raster",
          tiles: [wmsTileURL(config)],
          tileSize: 256,
        });
        map.addLayer(
          {
            id: "gis-wms",
            type: "raster",
            source: "gis-wms",
            paint: { "raster-opacity": config.gis_opacity ?? 0.7 },
          },
          "zone-fill",
        );
      } catch (e) {
        window.clearTimeout(timer);
        setExternalStatus((e as Error).message);
      }
    } else {
      fetchWFS(config, controller.signal)
        .then(({ data, limited }) => {
          if (controller.signal.aborted) return;
          window.clearTimeout(timer);
          addVector(map, "gis-service", data, "#c2a7f5");
          setExternalData(data);
          setExternalStatus(
            `WFS · ${fa(data.features.length)} عارضه دریافت شد${limited ? " · نمایش بخشی از داده (حداکثر ۵٬۰۰۰ عارضه)" : ""}`,
          );
        })
        .catch((e) => {
          if (controller.signal.aborted && !timedOut) return;
          window.clearTimeout(timer);
          setExternalStatus(
            timedOut
              ? "مهلت دریافت سرویس GIS تمام شد."
              : e instanceof TypeError
                ? "اتصال WFS ناموفق بود؛ شبکه و مجوز CORS را بررسی کنید."
                : e.message,
          );
        });
    }
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      map.off("error", onError);
      map.off("sourcedata", onData);
      if (map.getStyle()) {
        if (map.getLayer("gis-wms")) map.removeLayer("gis-wms");
        if (map.getSource("gis-wms")) map.removeSource("gis-wms");
        removeVector(map, "gis-service");
      }
    };
  }, [
    map,
    config?.gis_mode,
    config?.gis_url,
    config?.gis_layers,
    config?.gis_wms_version,
    config?.gis_wfs_version,
    config?.gis_opacity,
    retry,
    showExternal,
  ]);
  useEffect(() => {
    if (!map) return;
    ["fill", "line", "point"].forEach((suffix) => {
      if (map.getLayer(`gis-import-${suffix}`))
        map.setLayoutProperty(
          `gis-import-${suffix}`,
          "visibility",
          showImport ? "visible" : "none",
        );
    });
  }, [map, showImport]);
  async function importFile(file?: File) {
    if (!file) return;
    setError("");
    try {
      if (file.size > MAX_GEOJSON_BYTES)
        throw new Error("حداکثر اندازهٔ فایل ۵ مگابایت است.");
      let raw: unknown;
      try {
        raw = JSON.parse(await file.text());
      } catch {
        throw new Error("فایل JSON معتبر نیست.");
      }
      const data = parseGeoJSON(raw);
      setImported(data);
      setFilename(file.name);
      setShowImport(true);
      fit(data);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <>
      <button
        className="gis-toggle"
        aria-label="ابزارهای GIS"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Layers size={15} />
        GIS
      </button>
      {open && (
        <section className="gis-panel" aria-label="ابزارهای GIS">
          <header>
            <strong>ابزارهای GIS</strong>
            <button
              aria-label="بستن ابزارهای GIS"
              onClick={() => setOpen(false)}
            >
              <X size={16} />
            </button>
          </header>
          {hazardDrawing && (
            <div className="hazard-drawing">
              <strong>ترسیم محدوده خطر</strong>
              <div className="gis-actions">
                <button
                  aria-pressed={hazardKind === "circle"}
                  onClick={() => {
                    setHazardKind("circle");
                    setPoints([]);
                    setDrawing(true);
                  }}
                >
                  دایره
                </button>
                <button
                  aria-pressed={hazardKind === "polygon"}
                  onClick={() => {
                    setHazardKind("polygon");
                    setPoints([]);
                    setDrawing(true);
                  }}
                >
                  چندضلعی
                </button>
              </div>
              {hazardKind === "circle" && (
                <label className="field">
                  شعاع خطر (متر)
                  <input
                    type="number"
                    min={1}
                    max={100000}
                    value={radius}
                    onChange={(e) => setRadius(+e.target.value)}
                  />
                </label>
              )}
              <p className="gis-help">
                {hazardKind === "circle"
                  ? "مرکز دایره را روی نقشه کلیک کنید."
                  : "رأس‌ها را روی نقشه کلیک کنید؛ حداقل سه نقطه."}
              </p>
              <p className="gis-help">
                {hazardKind === "circle" && points[0]
                  ? `مرکز: ${points[0].map((n) => fa(Number(n.toFixed(5)))).join("، ")}`
                  : `${fa(points.length)} نقطه انتخاب شده`}
              </p>
              <div className="gis-actions">
                {hazardKind === "polygon" && (
                  <button
                    aria-label="حذف آخرین رأس خطر"
                    disabled={!points.length}
                    onClick={() => setPoints((p) => p.slice(0, -1))}
                  >
                    <Undo2 size={13} />
                  </button>
                )}
                <button
                  className="primary"
                  disabled={
                    hazardDrawing.busy ||
                    (hazardKind === "circle"
                      ? !points.length || radius <= 0 || radius > 100000
                      : points.length < 3)
                  }
                  onClick={() => {
                    const area: HazardArea =
                      hazardKind === "circle"
                        ? {
                            type: "circle",
                            center: points[0],
                            radius_m: radius,
                          }
                        : { type: "polygon", points };
                    void hazardDrawing.onSave(area);
                  }}
                >
                  ثبت محدوده خطر
                </button>
                <button
                  onClick={() => {
                    setDrawing(false);
                    setKind(null);
                    setPoints([]);
                    hazardDrawing.onCancel();
                  }}
                >
                  انصراف
                </button>
              </div>
            </div>
          )}
          {!hazardDrawing && (
            <>
              <span className="layer-section-title">اندازه‌گیری روی نقشه</span>
              <div className="gis-actions">
                <button
                  aria-pressed={kind === "distance"}
                  onClick={() => {
                    setKind("distance");
                    setPoints([]);
                    setDrawing(true);
                  }}
                >
                  <Ruler size={14} />
                  فاصله
                </button>
                <button
                  aria-pressed={kind === "area"}
                  onClick={() => {
                    setKind("area");
                    setPoints([]);
                    setDrawing(true);
                  }}
                >
                  مساحت
                </button>
              </div>
              {kind && (
                <>
                  <p className="gis-help">
                    {drawing
                      ? "نقاط را با کلیک روی نقشه انتخاب کنید؛ برای پایان Escape بزنید."
                      : "اندازه‌گیری تکمیل شد."}
                  </p>
                  <output className="gis-result">
                    {kind === "area"
                      ? `${fa(Math.round(area))} متر مربع`
                      : `${fa(Math.round(distance))} متر`}
                  </output>
                  <small className="gis-help">
                    برآورد جغرافیایی روی سطح زمین · {fa(points.length)} نقطه
                  </small>
                  <div className="gis-actions">
                    <button
                      aria-label="حذف آخرین نقطه"
                      onClick={() => setPoints((p) => p.slice(0, -1))}
                      disabled={!points.length}
                    >
                      <Undo2 size={13} />
                    </button>
                    <button
                      onClick={() => setDrawing(false)}
                      disabled={!drawing}
                    >
                      <Check size={13} />
                      پایان
                    </button>
                    <button
                      onClick={() => {
                        setKind(null);
                        setDrawing(false);
                        setPoints([]);
                      }}
                    >
                      <Trash2 size={13} />
                      پاک‌کردن
                    </button>
                  </div>
                </>
              )}
            </>
          )}
          <span className="layer-section-title">لایهٔ فایل · WGS 84</span>
          <input
            ref={fileInput}
            type="file"
            accept=".geojson,.json,application/geo+json,application/json"
            aria-label="فایل GeoJSON"
            hidden
            onChange={(e) => {
              void importFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <button
            className="gis-wide"
            onClick={() => fileInput.current?.click()}
          >
            <Upload size={14} />
            ورود GeoJSON
          </button>
          {imported && (
            <>
              <label className="gis-check">
                <input
                  type="checkbox"
                  checked={showImport}
                  onChange={(e) => setShowImport(e.target.checked)}
                />
                <span>
                  {filename} · {fa(imported.features.length)} عارضه
                </span>
              </label>
              <div className="gis-actions">
                <button onClick={() => fit(imported)}>
                  <LocateFixed size={13} />
                  نمایش لایه
                </button>
                <button
                  onClick={() => {
                    setImported(null);
                    setFilename("");
                  }}
                >
                  حذف لایه
                </button>
              </div>
              <small className="gis-help">
                این فایل تا زمان خروج از صفحه نگهداری می‌شود.
              </small>
            </>
          )}
          {error && (
            <p className="gis-error" role="alert">
              {error}
            </p>
          )}
          <span className="layer-section-title">سرویس سازمانی</span>
          {settings.isError ? (
            <p className="gis-error">دریافت تنظیمات ناموفق بود.</p>
          ) : config?.gis_mode !== "local" && config ? (
            <>
              <label className="gis-check">
                <input
                  type="checkbox"
                  checked={showExternal}
                  onChange={(e) => setShowExternal(e.target.checked)}
                />
                {config.gis_mode.toUpperCase()} · {config.gis_layers}
              </label>
              <p className="gis-service-status" role="status">
                {externalStatus || "لایه خاموش است"}
              </p>
              <div className="gis-actions">
                <button
                  onClick={() => setRetry((n) => n + 1)}
                  disabled={!showExternal}
                >
                  اتصال مجدد
                </button>
                {externalData && (
                  <button onClick={() => fit(externalData)}>
                    نمایش عوارض WFS
                  </button>
                )}
              </div>
            </>
          ) : (
            <p className="gis-help">
              نشانی سرویس و نام لایه را در مدیریت سامانه ← اتصال GIS تنظیم کنید.
            </p>
          )}
          <button
            className="gis-wide"
            disabled={!imported && !externalData && !points.length}
            onClick={() =>
              download(
                "sepehr-gis.geojson",
                collection([
                  ...(imported?.features || []),
                  ...(externalData?.features || []),
                  ...measurement.features,
                ]),
              )
            }
          >
            <Download size={14} />
            خروجی لایه‌ها و اندازه‌گیری
          </button>
        </section>
      )}
      {kind && drawing && !open && (
        <div className="gis-measuring">
          {hazardDrawing ? "ترسیم محدوده خطر فعال" : "اندازه‌گیری فعال"} · پایان
          با Escape
        </div>
      )}
    </>
  );
}
