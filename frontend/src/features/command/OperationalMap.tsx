import {
  Layers,
  LocateFixed,
  Minus,
  Navigation,
  Plus,
  Moon,
  Map as MapIcon,
  Scan,
  RefreshCw,
  Route,
  X,
} from "lucide-react";
import maplibregl, { type Map as GLMap, type GeoJSONSource } from "maplibre-gl";
import { useQuery } from "@tanstack/react-query";
import type { StyleSpecification } from "maplibre-gl";
// Replaced at build time: the production bundle defines NODE_ENV="production".
declare const process: { env: { NODE_ENV?: string } };
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, fa } from "../../api";
import type {
  Asset,
  CommGapLayer,
  Coverage,
  Data,
  Incident,
  NearbyPatrol,
  PatrolPlan,
  RiskStatus,
  RuntimeSettings,
  Segment,
} from "../../types";
import {
  collection,
  feature,
  mapStyle,
  schematicStyle,
  operationalBounds,
  OMIDIYEH_CENTER,
  baseLayerIds,
  labelLayerIds,
  buildingLayerIds,
  type BasemapMode,
} from "./mapStyle";
import StreetMapFallback from "./StreetMapFallback";
import GisTools, { type HazardDrawing } from "../geography/GisTools";
import { circleRing } from "../geography/gis";
import MapViewport from "./MapViewport";
import { visibleTrack, playbackPosition, routeColors } from "./trackPlayback";
import { usePatrolSafety } from "./usePatrolSafety";
type Props = {
  children?: ReactNode;
  command?: boolean;
  data: Data;
  onAsset: (a: Asset) => void;
  onIncident: (i: Incident) => void;
  selected?: string;
  focus?: Incident | null;
  focusTargetId?: string;
  replay?: number;
  hazardDrawing?: HazardDrawing;
  patrolPlan?: PatrolPlan | null;
  theme?: "dark" | "light";
};
const layerNames = {
  tracks: "مسیر حرکت خودروها",
  zones: "محدوده‌های حفاظت",
  assets: "گشت‌ها و نیروها",
  incidents: "رخدادهای باز",
  coverage: "محدوده‌های پوشش ضعیف",
  patrolCoverage: "پوشش گشت خطوط",
  hazard: "محدوده خطر حوادث",
  commGaps: "شکاف ارتباطی",
  risk: "ریسک",
  heat: "نقشه حرارتی",
  cameras: "دوربین‌های نمونه",
};
const carIcon =
  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m5 6 2-3h10l2 3 2 5v6H3v-6ZM3 11h18M6 17v3m12-3v3M7 14h1m8 0h1"/></svg>';
const personIcon =
  '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="6" r="3"/><path d="M6 21v-5a6 6 0 0 1 12 0v5"/></svg>';
export default function OperationalMap(props: Props) {
  return (
    <MapViewport command={props.command}>
      <MapContent {...props} />
      {props.children}
    </MapViewport>
  );
}
function MapContent(props: Props) {
  const safety = usePatrolSafety();
  const { data, selected, focus, replay = 100 } = props;
  const ref = useRef<HTMLDivElement>(null),
    map = useRef<GLMap | null>(null),
    callbacks = useRef(props);
  const focusedReportTarget = useRef("");
  callbacks.current = props;
  const [ready, setReady] = useState(false),
    [failed, setFailed] = useState(false),
    [showLayers, setShowLayers] = useState(Boolean(props.command)),
    [layers, setLayers] = useState({
      tracks: true,
      zones: true,
      assets: true,
      incidents: true,
      coverage: false,
      patrolCoverage: false,
      hazard: true,
      commGaps: false,
      risk: false,
      heat: false,
      cameras: false,
    }),
    [flat, setFlat] = useState(true),
    [basemap, setBasemap] = useState<BasemapMode>(props.theme === "light" ? "street" : "night"),
    [labels, setLabels] = useState(true),
    [buildings, setBuildings] = useState(true),
    [tileStatus, setTileStatus] = useState<"loading" | "ready" | "error">(
      "loading",
    ),
    [view, setView] = useState({
      lon: OMIDIYEH_CENTER[0],
      lat: OMIDIYEH_CENTER[1],
      zoom: 14,
      bearing: 0,
    });
  useEffect(() => {
    if (props.theme) setBasemap(props.theme === "light" ? "street" : "night");
  }, [props.theme]);
  const activeBasemap = useRef(basemap);
  activeBasemap.current = basemap;
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<RuntimeSettings>("/settings") });
  const internalStyle = settings.data?.basemap_style_url || "";
  // Public demo tiles exist only in development builds; production uses internal or schematic maps.
  const publicBasemap = process.env.NODE_ENV !== "production" && !internalStyle;
  const commGaps = useQuery({
    queryKey: ["intel", "communication-gaps"],
    queryFn: () => api<CommGapLayer>("/intel/communication-gaps"),
    enabled: layers.commGaps,
    refetchInterval: 60000,
  });
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    const shapes = collection((commGaps.data?.cells || []).filter((c) => c.offline_samples + c.silences > 0).map((c) =>
      feature({ type: "Point", coordinates: [c.lon, c.lat] },
        { id: c.id, weight: c.offline_samples + c.silences, low: c.confidence === "low" })));
    if (!m.getSource("comm-gaps")) {
      m.addSource("comm-gaps", { type: "geojson", data: shapes });
      m.addLayer({ id: "comm-gaps", type: "circle", source: "comm-gaps", paint: {
        "circle-color": ["case", ["get", "low"], "#9aa7b3", "#e9b873"],
        "circle-opacity": 0.55,
        "circle-radius": ["min", 28, ["+", 8, ["*", 2, ["get", "weight"]]]],
        "circle-stroke-color": "#09131c", "circle-stroke-width": 1 } });
    } else (m.getSource("comm-gaps") as GeoJSONSource).setData(shapes);
    m.setLayoutProperty("comm-gaps", "visibility", layers.commGaps ? "visible" : "none");
  }, [ready, commGaps.data, layers.commGaps]);
  const coverage = useQuery({
    queryKey: ["intel", "coverage"],
    queryFn: ({ signal }) =>
      api<Coverage>("/intel/coverage", "GET", undefined, signal),
    refetchInterval: 3000,
  });
  const segments = useQuery({
    queryKey: ["intel", "segments"],
    queryFn: ({ signal }) =>
      api<Segment[]>("/intel/segments", "GET", undefined, signal),
    refetchInterval: 3000,
  });
  const risk = useQuery({
    queryKey: ["intel", "risk"],
    queryFn: ({ signal }) =>
      api<RiskStatus>("/intel/risk", "GET", undefined, signal),
    refetchInterval: 3000,
    enabled: layers.risk,
  });
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const scores = new globalThis.Map(
      risk.data?.items.map((row) => [row.id, row]),
    );
    const shapes = collection(
      (segments.data || []).map((segment) => {
        const row = scores.get(segment.id);
        return feature(
          { type: "LineString", coordinates: segment.points },
          {
            score:
              row && risk.data?.max_score ? row.score / risk.data.max_score : 0,
            label: row
              ? `${row.name} · ریسک ${fa(Number(row.score.toFixed(3)))}`
              : "ریسک ناموجود",
          },
        );
      }),
    );
    if (!m.getSource("patrol-risk")) {
      m.addSource("patrol-risk", { type: "geojson", data: shapes });
      m.addLayer({
        id: "patrol-risk-lines",
        type: "line",
        source: "patrol-risk",
        paint: {
          "line-width": 6,
          "line-color": [
            "interpolate",
            ["linear"],
            ["get", "score"],
            0,
            "#59d6c4",
            0.5,
            "#efbe69",
            1,
            "#ef737e",
          ],
        },
      });
    } else (m.getSource("patrol-risk") as GeoJSONSource).setData(shapes);
    m.setLayoutProperty(
      "patrol-risk-lines",
      "visibility",
      layers.risk && risk.data ? "visible" : "none",
    );
    if (layers.risk) m.moveLayer("patrol-risk-lines");
  }, [ready, segments.data, risk.data, layers.risk]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !layers.risk) return;
    let popup: maplibregl.Popup | undefined;
    const click = (event: maplibregl.MapLayerMouseEvent) => {
      const text = event.features?.[0]?.properties?.label;
      if (!text) return;
      const el = document.createElement("div");
      el.dir = "rtl";
      el.style.color = "#09131c";
      el.textContent = text;
      popup?.remove();
      popup = new maplibregl.Popup()
        .setLngLat(event.lngLat)
        .setDOMContent(el)
        .addTo(m);
    };
    m.on("click", "patrol-risk-lines", click);
    return () => {
      popup?.remove();
      m.off("click", "patrol-risk-lines", click);
    };
  }, [ready, layers.risk]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const shapes = collection(
      (props.patrolPlan?.patrols || [])
        .flatMap((patrol, index) => {
          const color = routeColors[index % routeColors.length];
          return [
            feature(
              {
                type: "LineString",
                coordinates: [
                  patrol.base,
                  ...patrol.stops.map((s) => [s.lon, s.lat]),
                ],
              },
              {
                color,
                label: `${data.assets.find((a) => a.id === patrol.asset_id)?.name || patrol.asset_id} · شماتیک`,
              },
            ),
            ...patrol.stops.map((stop, n) =>
              feature(
                { type: "Point", coordinates: [stop.lon, stop.lat] },
                {
                  color,
                  label: `${fa(n + 1)} · ${stop.name}`,
                },
              ),
            ),
          ];
        })
        .filter(
          (f) =>
            f.geometry.type !== "LineString" ||
            f.geometry.coordinates.length > 1,
        ),
    );
    if (!m.getSource("patrol-plan-preview")) {
      m.addSource("patrol-plan-preview", { type: "geojson", data: shapes });
      m.addLayer({
        id: "patrol-plan-line",
        type: "line",
        source: "patrol-plan-preview",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": ["get", "color"],
          "line-width": 4,
          "line-dasharray": [3, 2],
        },
      });
      m.addLayer({
        id: "patrol-plan-stops",
        type: "circle",
        source: "patrol-plan-preview",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": 7,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#09131c",
        },
      });
      // Line labels need glyphs, which only the public development style provides.
      if (m.getStyle().glyphs) m.addLayer({
        id: "patrol-plan-label",
        type: "symbol",
        source: "patrol-plan-preview",
        filter: ["==", ["geometry-type"], "LineString"],
        layout: {
          "symbol-placement": "line",
          "text-field": ["get", "label"],
          "text-size": 12,
          "text-font": ["Noto Sans Regular"],
        },
        paint: {
          "text-color": "#dbe6ee",
          "text-halo-color": "#09131c",
          "text-halo-width": 2,
        },
      });
    } else
      (m.getSource("patrol-plan-preview") as GeoJSONSource).setData(shapes);
  }, [ready, props.patrolPlan, data.assets]);
  useEffect(() => {
    if (!ready || !map.current || !props.patrolPlan) return;
    const points = props.patrolPlan.patrols.flatMap((p) => [
      p.base,
      ...p.stops.map((s) => [s.lon, s.lat]),
    ]);
    if (!points.length) return;
    const bounds = new maplibregl.LngLatBounds();
    points.forEach((p) => bounds.extend([p[0], p[1]]));
    map.current.fitBounds(bounds, { padding: 90, maxZoom: 14, duration: 600 });
  }, [ready, props.patrolPlan?.id]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const shapes = collection(
      data.incidents
        .filter((i) => i.status !== "closed" && i.hazard_area)
        .map((i) => {
          const area = i.hazard_area!;
          const ring =
            area.type === "circle"
              ? circleRing(area.center, area.radius_m)
              : [...area.points, area.points[0]];
          return feature(
            { type: "Polygon", coordinates: [ring] },
            { id: i.id, title: i.title },
          );
        }),
    );
    if (!m.getSource("incident-hazard")) {
      m.addSource("incident-hazard", { type: "geojson", data: shapes });
      m.addLayer({
        id: "incident-hazard-fill",
        type: "fill",
        source: "incident-hazard",
        paint: { "fill-color": "#ef737e", "fill-opacity": 0.2 },
      });
      m.addLayer({
        id: "incident-hazard-line",
        type: "line",
        source: "incident-hazard",
        paint: {
          "line-color": "#ef737e",
          "line-width": 2,
          "line-dasharray": [3, 2],
        },
      });
    } else (m.getSource("incident-hazard") as GeoJSONSource).setData(shapes);
    ["incident-hazard-fill", "incident-hazard-line"].forEach((id) =>
      m.setLayoutProperty(id, "visibility", layers.hazard ? "visible" : "none"),
    );
  }, [ready, data.incidents, layers.hazard]);
  useEffect(() => {
    if (!ref.current) return;
    let m: GLMap;
    try {
      if (maplibregl.getRTLTextPluginStatus() === "unavailable") {
        void maplibregl
          .setRTLTextPlugin("/maps/mapbox-gl-rtl-text.js", true)
          .catch(() => {});
      }
      m = new maplibregl.Map({
        container: ref.current,
        style: publicBasemap ? mapStyle : schematicStyle,
        center: OMIDIYEH_CENTER,
        zoom: 14,
        minZoom: 2,
        maxZoom: 19,
        attributionControl: false,
        pitch: 0,
        renderWorldCopies: false,
      });
      map.current = m;
      m.addControl(
        new maplibregl.ScaleControl({ maxWidth: 100, unit: "metric" }),
        "bottom-left",
      );
    } catch {
      setFailed(true);
      return;
    }
    m.on("style.load", () => {
      setReady(true);
      const { data } = callbacks.current;
      m.fitBounds(operationalBounds(data.zones, data.assets), {
        padding: 70,
        duration: 0,
      });
    });
    m.on("move", () => {
      const c = m.getCenter();
      setView({
        lon: c.lng,
        lat: c.lat,
        zoom: m.getZoom(),
        bearing: m.getBearing(),
      });
    });
    m.on("sourcedata", (e) => {
      const sourceId =
        activeBasemap.current === "night" ? "openmaptiles" : "osm-street";
      if (e.sourceId === sourceId && e.sourceDataType === "content")
        setTileStatus((status) => (status === "error" ? "error" : "ready"));
    });
    m.on("error", (e) => {
      const sourceId =
        activeBasemap.current === "night" ? "openmaptiles" : "osm-street";
      if ("sourceId" in e && e.sourceId === sourceId) setTileStatus("error");
    });
    m.on("webglcontextlost", () => setFailed(true));
    m.on("moveend", () => setFlat(m.getPitch() < 1));
    m.on("click", "clusters", async (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const source = m.getSource("assets") as GeoJSONSource;
      const zoom = await source.getClusterExpansionZoom(
        f.properties.cluster_id,
      );
      if (f.geometry.type === "Point")
        m.easeTo({ center: f.geometry.coordinates as [number, number], zoom });
    });
    m.on(
      "mouseenter",
      "clusters",
      () => (m.getCanvas().style.cursor = "pointer"),
    );
    m.on("mouseleave", "clusters", () => (m.getCanvas().style.cursor = ""));
    const observer = new ResizeObserver(() => m.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    // Red means an open policy breach of this exact zone (engine incidents carry zone_id).
    const breached = new Set(
      data.incidents
        .filter((i) => i.status !== "closed" && i.zone_id)
        .map((i) => i.zone_id),
    );
    (m.getSource("zones") as GeoJSONSource).setData(
      collection(
        data.zones.map((z, i) => {
          const alert = breached.has(z.id);
          return feature(
            { type: "Polygon", coordinates: [[...z.points, z.points[0]]] },
            {
              name: z.name,
              alert,
              color: alert
                ? "#f26b5b"
                : ["#b7a06d", "#6bafad", "#58aa92"][i % 3],
            },
          );
        }),
      ),
    );
    (m.getSource("coverage") as GeoJSONSource).setData(
      collection(
        data.zones
          .filter((z) => z.coverage === "weak")
          .map((z) =>
            feature(
              { type: "Polygon", coordinates: [[...z.points, z.points[0]]] },
              { name: z.name },
            ),
          ),
      ),
    );
    (m.getSource("assets") as GeoJSONSource).setData(
      collection(
        data.assets.map((a) => {
          const point = playbackPosition(a, replay);
          return feature(
            { type: "Point", coordinates: [point.lon, point.lat] },
            { id: a.id },
          );
        }),
      ),
    );
    (m.getSource("incidents") as GeoJSONSource).setData(
      collection(
        data.incidents
          .filter((i) => i.status !== "closed")
          .map((i) =>
            feature(
              { type: "Point", coordinates: [i.lon, i.lat] },
              { id: i.id },
            ),
          ),
      ),
    );
    const tracked = data.assets.filter(
      (a) => a.kind === "vehicle" || a.id === selected,
    );
    (m.getSource("tracks") as GeoJSONSource).setData(
      collection(
        tracked.flatMap((a, index) => {
          const points = visibleTrack(a.track, replay);
          return points.length < 2
            ? []
            : [
                feature(
                  {
                    type: "LineString",
                    coordinates: points.map((p) => [p.lon, p.lat]),
                  },
                  {
                    id: a.id,
                    color: routeColors[index % routeColors.length],
                    selected: a.id === selected,
                  },
                ),
              ];
        }),
      ),
    );
  }, [ready, data, selected, replay]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    if (!m.getSource("patrol-coverage")) {
      m.addSource("patrol-coverage", { type: "geojson", data: collection([]) });
      m.addLayer({
        id: "patrol-coverage-lines",
        type: "line",
        source: "patrol-coverage",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: {
          "line-color": ["get", "color"],
          "line-width": 5,
          "line-opacity": 0.9,
        },
      });
      m.addLayer({
        id: "patrol-coverage-facilities",
        type: "circle",
        source: "patrol-coverage",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": 8,
          "circle-stroke-color": "#dbe6ee",
          "circle-stroke-width": 1.5,
        },
      });
    }
    const tokens = getComputedStyle(document.documentElement);
    const colors = {
      ok: tokens.getPropertyValue("--teal").trim(),
      stale: tokens.getPropertyValue("--orange").trim(),
      never: tokens.getPropertyValue("--muted").trim(),
    };
    const statuses = {
      ok: "بازدید در مهلت",
      stale: "بازدید به تأخیر افتاده",
      never: "بازدید ثبت نشده",
    };
    const items = new Map(coverage.data?.items.map((item) => [item.id, item]));
    const geometries = [
      ...(segments.data || []).map((segment) => ({
        id: segment.id,
        name: `${data.pipelines.find((p) => p.id === segment.pipeline_id)?.name || segment.pipeline_id} · قطعه ${fa(segment.index + 1)}`,
        geometry: { type: "LineString" as const, coordinates: segment.points },
      })),
      ...data.facilities.map((facility) => ({
        id: facility.id,
        name: facility.name,
        geometry: {
          type: "Point" as const,
          coordinates: [facility.lon, facility.lat],
        },
      })),
    ];
    (m.getSource("patrol-coverage") as GeoJSONSource).setData(
      collection(
        geometries.flatMap(({ id, name, geometry }) => {
          const item = items.get(id);
          if (!item) return [];
          const patrol =
            data.assets.find((a) => a.id === item.last_asset_id)?.name ||
            item.last_asset_id ||
            "—";
          const lastVisit = item.last_visit
            ? new Date(item.last_visit).toLocaleString("fa-IR", {
                timeZone: "Asia/Tehran",
              })
            : "ثبت نشده";
          return [
            feature(geometry, {
              id,
              name,
              color: colors[item.status],
              statusLabel: statuses[item.status],
              patrol,
              lastVisit,
            }),
          ];
        }),
      ),
    );
    ["patrol-coverage-lines", "patrol-coverage-facilities"].forEach((id) =>
      m.setLayoutProperty(
        id,
        "visibility",
        layers.patrolCoverage ? "visible" : "none",
      ),
    );
  }, [
    ready,
    coverage.data,
    segments.data,
    data.assets,
    data.pipelines,
    data.facilities,
    layers.patrolCoverage,
  ]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !layers.patrolCoverage) return;
    let popup: maplibregl.Popup | undefined;
    const showPopup = (event: maplibregl.MapLayerMouseEvent) => {
      const properties = event.features?.[0]?.properties;
      if (!properties) return;
      const content = document.createElement("div");
      content.dir = "rtl";
      content.style.color = "#09131c";
      [
        properties.name,
        properties.statusLabel,
        `آخرین بازدید: ${properties.lastVisit}`,
        `گشت: ${properties.patrol}`,
      ].forEach((text) => {
        const line = document.createElement("div");
        line.textContent = text;
        content.append(line);
      });
      popup?.remove();
      popup = new maplibregl.Popup()
        .setLngLat(event.lngLat)
        .setDOMContent(content)
        .addTo(m);
    };
    const enter = () => {
      m.getCanvas().style.cursor = "pointer";
    };
    const leave = () => {
      m.getCanvas().style.cursor = "";
    };
    ["patrol-coverage-lines", "patrol-coverage-facilities"].forEach((id) => {
      m.on("click", id, showPopup);
      m.on("mouseenter", id, enter);
      m.on("mouseleave", id, leave);
    });
    return () => {
      popup?.remove();
      ["patrol-coverage-lines", "patrol-coverage-facilities"].forEach((id) => {
        m.off("click", id, showPopup);
        m.off("mouseenter", id, enter);
        m.off("mouseleave", id, leave);
      });
    };
  }, [ready, layers.patrolCoverage]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const markers: maplibregl.Marker[] = [];
    function add(el: HTMLElement, lon: number, lat: number) {
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([lon, lat])
        .addTo(m!);
      markers.push(marker);
      return marker;
    }
    const flagged = new Set(
      data.incidents
        .filter((i) => i.status !== "closed")
        .map((i) => i.asset_id),
    );
    if (layers.assets)
      data.assets.forEach((a) => {
        const t = playbackPosition(a, replay);
        const el = document.createElement("button");
        const pending =
          replay === 100 &&
          safety.data?.episodes.some(
            (e) => e.asset_id === a.id && e.state === "check_pending",
          );
        el.className = `gl-asset ${a.status} ${pending ? "check-pending" : ""} ${a.authorized === false ? (flagged.has(a.id) ? "unauthorized" : "org") : ""} ${selected === a.id ? "selected" : ""}`;
        el.setAttribute("aria-label", a.name);
        const icon = document.createElement("span");
        icon.className = "marker-symbol";
        icon.innerHTML = a.kind === "vehicle" ? carIcon : personIcon;
        const label = document.createElement("span");
        label.className = "marker-label";
        label.textContent =
          a.speed > 0 && a.kind === "vehicle"
            ? `${a.name} · ${fa(Math.round(a.speed))}`
            : a.name;
        el.append(icon, label);
        el.onclick = () => callbacks.current.onAsset(a);
        add(el, t.lon, t.lat);
      });
    if (layers.incidents)
      data.incidents
        .filter((i) => i.status !== "closed")
        .forEach((i) => {
          const el = document.createElement("button");
          el.className = `gl-incident ${i.severity} ${focus?.id === i.id ? "focused" : ""}`;
          el.setAttribute("aria-label", i.title);
          el.title = i.title;
          el.textContent = "!";
          el.onclick = () => callbacks.current.onIncident(i);
          add(el, i.lon, i.lat);
        });
    if (layers.zones)
      data.zones.forEach((z) => {
        const el = document.createElement("span");
        const alert = data.incidents.some(
          (i) => i.status !== "closed" && i.zone_id === z.id,
        );
        el.className = alert ? "gl-zone alert" : "gl-zone";
        el.textContent = alert ? `⚠ ${z.name}` : z.name;
        add(el, z.points[0][0], z.points[0][1]);
      });
    if (layers.cameras)
      [
        [49.88, 30.85],
        [49.97, 30.74],
        [49.73, 30.87],
      ].forEach(([lon, lat], i) => {
        const el = document.createElement("span");
        el.className = "gl-camera";
        el.textContent = `◉ دوربین نمونه ${i + 1}`;
        add(el, lon, lat);
      });
    const toggle = () => {
      markers.forEach((marker) => {
        const el = marker.getElement();
        if (el.classList.contains("gl-asset"))
          el.style.visibility = m.getZoom() < 9.5 ? "hidden" : "visible";
      });
    };
    m.on("zoom", toggle);
    toggle();
    return () => {
      m.off("zoom", toggle);
      markers.forEach((x) => x.remove());
    };
  }, [
    ready,
    data.assets,
    data.incidents,
    data.zones,
    layers,
    replay,
    selected,
    focus?.id,
    safety.data,
  ]);
  // Incident command mode: candidate patrols with estimated ETA, then the live dispatch line.
  const live = focus
    ? data.incidents.find((i) => i.id === focus.id) || focus
    : null;
  const [candidates, setCandidates] = useState<NearbyPatrol[]>([]);
  const candidateKey =
    live && live.status !== "closed" && !live.assigned_to ? live.id : "";
  useEffect(() => {
    if (!candidateKey) return setCandidates([]);
    const controller = new AbortController();
    api<NearbyPatrol[]>(
      `/incidents/${candidateKey}/nearby`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((rows) => setCandidates(rows.slice(0, 3)))
      .catch(() => {});
    return () => controller.abort();
  }, [candidateKey, data.assets]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const source = m.getSource("command") as GeoJSONSource;
    const markers: maplibregl.Marker[] = [];
    const patrol = live?.assigned_to
      ? data.assets.find((a) => a.id === live.assigned_to)
      : undefined;
    const active = live && live.status !== "closed";
    const lines = !active
      ? []
      : patrol
        ? [
            {
              lon: patrol.lon,
              lat: patrol.lat,
              dispatched: true,
              label: live.arrived_at ? "در محل" : `${patrol.name} · در مسیر`,
            },
          ]
        : candidates.map((c, k) => ({
            lon: c.lon,
            lat: c.lat,
            dispatched: false,
            label: `${k === 0 ? "★ " : ""}${c.name} · ~${fa(Math.round(c.eta_minutes))} دقیقه`,
          }));
    source.setData(
      collection(
        lines.map((l) =>
          feature(
            {
              type: "LineString",
              coordinates: [
                [l.lon, l.lat],
                [live!.lon, live!.lat],
              ],
            },
            { dispatched: l.dispatched },
          ),
        ),
      ),
    );
    lines.forEach((l) => {
      const el = document.createElement("span");
      el.className = l.dispatched ? "gl-eta dispatched" : "gl-eta";
      el.textContent = l.label;
      markers.push(
        new maplibregl.Marker({ element: el })
          .setLngLat([(l.lon + live!.lon) / 2, (l.lat + live!.lat) / 2])
          .addTo(m),
      );
    });
    if (active) {
      const ring = document.createElement("span");
      ring.className = "gl-focus-ring";
      markers.push(
        new maplibregl.Marker({ element: ring })
          .setLngLat([live.lon, live.lat])
          .addTo(m),
      );
    }
    return () => markers.forEach((x) => x.remove());
  }, [ready, live, candidates, data.assets]);
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;
    const groups: Record<string, string[]> = {
      tracks: ["track-casing", "track-glow", "track"],
      zones: ["zone-fill", "zone-glow", "zone-line"],
      assets: ["clusters", "cluster-core"],
      coverage: ["coverage-fill", "coverage-line"],
      heat: ["heat"],
    };
    Object.entries(groups).forEach(([k, ids]) =>
      ids.forEach((id) =>
        m.setLayoutProperty(
          id,
          "visibility",
          layers[k as keyof typeof layers] ? "visible" : "none",
        ),
      ),
    );
  }, [layers, ready]);
  useEffect(() => {
    // Approved internal style: its sources and layers go beneath the operational layers.
    const m = map.current;
    if (!m || !ready || !internalStyle) return;
    let cancelled = false;
    fetch(internalStyle)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((style: StyleSpecification) => {
        if (cancelled) return;
        const first = m.getStyle().layers.find((l) => l.id !== "background")?.id;
        Object.entries(style.sources).forEach(([id, src]) => { if (!m.getSource(`base-${id}`)) m.addSource(`base-${id}`, src); });
        style.layers.forEach((layer) => {
          if (layer.type === "symbol" || m.getLayer(`base-${layer.id}`)) return; // no remote glyphs in the merged style
          const copy = { ...layer, id: `base-${layer.id}` } as typeof layer & { source?: string };
          if ("source" in layer && layer.source) copy.source = `base-${layer.source}`;
          m.addLayer(copy as Parameters<typeof m.addLayer>[0], first);
        });
        setTileStatus("ready");
      })
      .catch(() => !cancelled && setTileStatus("error"));
    return () => { cancelled = true; };
  }, [ready, internalStyle]);
  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    if (!publicBasemap) return;
    baseLayerIds.forEach((id) => {
      const visible =
        basemap === "night" &&
        (!labelLayerIds.includes(id) || labels) &&
        (!buildingLayerIds.includes(id) || buildings);
      m.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    });
    m.setLayoutProperty(
      "osm-street",
      "visibility",
      basemap === "street" ? "visible" : "none",
    );
    setTileStatus(
      m.isSourceLoaded(basemap === "night" ? "openmaptiles" : "osm-street")
        ? "ready"
        : "loading",
    );
  }, [ready, basemap, labels, buildings]);
  useEffect(() => {
    if (ready && focus)
      map.current?.flyTo({
        center: [focus.lon, focus.lat],
        zoom: 12.4,
        offset: [0, -90],
        duration: 1100,
      });
  }, [focus?.id, ready]);

  useEffect(() => {
    const id = props.focusTargetId;
    const m = map.current;
    if (!id) { focusedReportTarget.current = ""; return; }
    if (!ready || !m || !id) return;
    const segment = segments.data?.find(s => s.id === id);
    const facility = data.facilities.find(f => f.id === id);
    const points = segment?.points || (facility ? [[facility.lon, facility.lat]] : []);
    if (!points.length) return;
    const key = `${id}:${JSON.stringify(points)}`;
    if (focusedReportTarget.current === key) return;
    focusedReportTarget.current = key;
    setLayers(l => ({ ...l, patrolCoverage: true }));
    const bounds = new maplibregl.LngLatBounds();
    points.forEach(p => bounds.extend([p[0], p[1]]));
    m.fitBounds(bounds, { padding: 100, maxZoom: 16, duration: 600 });
  }, [props.focusTargetId, ready, segments.data, data.facilities]);
  useEffect(() => {
    const a = data.assets.find((a) => a.id === selected);
    if (!ready || !a) return;
    if (a.track.length > 1) {
      const bounds = new maplibregl.LngLatBounds();
      a.track.forEach((p) => bounds.extend([p.lon, p.lat]));
      map.current?.fitBounds(bounds, {
        padding: 90,
        maxZoom: 15,
        duration: 600,
      });
    } else map.current?.easeTo({ center: [a.lon, a.lat], duration: 600 });
  }, [selected, ready]);
  function fitRoutes() {
    const points = data.assets
      .filter((a) => a.kind === "vehicle" || a.id === selected)
      .flatMap((a) => a.track);
    if (!points.length) return;
    const bounds = new maplibregl.LngLatBounds();
    points.forEach((p) => bounds.extend([p.lon, p.lat]));
    setLayers((current) => ({ ...current, tracks: true }));
    map.current?.fitBounds(bounds, { padding: 90, maxZoom: 15, duration: 700 });
  }
  if (failed) return <StreetMapFallback {...props} />;
  return (
    <div
      className={`map-shell maplibre-shell omidiyeh-map ${basemap}`}
      data-map-engine="maplibre"
    >
      <div
        ref={ref}
        className="gl-container"
        aria-label="نقشه واقعی امیدیه، خوزستان؛ OpenStreetMap"
      />
      <div className="map-top">
        <div className="map-location-card">
          <span className="map-kicker">AGHAJARI / KHUZESTAN</span>
          <div>
            <span className="map-location-dot" />
            <strong>آغاجاری</strong>
            <span>امیدیه · خوزستان</span>
          </div>
          <small>میدان‌ها، محدوده‌ها و گشت‌های زنده</small>
        </div>
        <button
          className="map-compass"
          aria-label="تنظیم جهت شمال"
          title="تنظیم جهت شمال"
          onClick={() =>
            map.current?.easeTo({ bearing: 0, pitch: 0, duration: 500 })
          }
        >
          <span>N</span>
          <Navigation
            size={21}
            style={{ transform: `rotate(${-view.bearing - 45}deg)` }}
          />
        </button>
      </div>
      <div className="basemap-switch" role="group" aria-label="سبک نقشه">
        <button
          aria-pressed={basemap === "night"}
          onClick={() => setBasemap("night")}
        >
          <Moon size={14} />
          عملیاتی شب
        </button>
        <button
          aria-pressed={basemap === "street"}
          onClick={() => setBasemap("street")}
        >
          <MapIcon size={14} />
          خیابانی OSM
        </button>
      </div>
      <div className={`map-source-status ${tileStatus}`} role="status">
        <i />
        {tileStatus === "loading"
          ? "در حال دریافت نقشه…"
          : tileStatus === "error"
            ? "دریافت بخشی از نقشه ناموفق بود"
            : basemap === "night"
              ? "OpenStreetMap · نقشه برداری"
              : "OpenStreetMap · نقشه خیابانی"}
        {tileStatus === "error" && (
          <button
            aria-label="تلاش دوباره برای دریافت نقشه"
            onClick={() => {
              setTileStatus("loading");
              const m = map.current;
              if (basemap === "night")
                (
                  m?.getSource("openmaptiles") as
                    | maplibregl.VectorTileSource
                    | undefined
                )?.setUrl("https://tiles.openfreemap.org/planet");
              else
                (
                  m?.getSource("osm-street") as
                    | maplibregl.RasterTileSource
                    | undefined
                )?.setTiles(["https://tile.openstreetmap.org/{z}/{x}/{y}.png"]);
            }}
          >
            <RefreshCw size={13} />
          </button>
        )}
      </div>
      <button
        className="map-route-overview"
        onClick={fitRoutes}
        disabled={!ready}
        aria-label="نمایش مسیر خودروها"
      >
        <Route size={15} /> مسیر خودروها{" "}
        <span>
          {data.assets
            .filter((a) => a.kind === "vehicle" && a.track.length > 1)
            .length.toLocaleString("fa-IR")}
        </span>
      </button>
      <div className="map-tools">
        <button aria-label="بزرگ‌نمایی" onClick={() => map.current?.zoomIn()}>
          <Plus size={18} />
        </button>
        <button aria-label="کوچک‌نمایی" onClick={() => map.current?.zoomOut()}>
          <Minus size={18} />
        </button>
        <button
          aria-label="بازگشت به امیدیه"
          title="بازگشت به امیدیه"
          onClick={() =>
            map.current?.easeTo({
              center: OMIDIYEH_CENTER,
              zoom: 14,
              duration: 700,
              bearing: 0,
              pitch: 0,
            })
          }
        >
          <LocateFixed size={18} />
        </button>
        <button
          aria-label="نمایش همه گشت‌ها"
          title="نمایش همه گشت‌ها"
          onClick={() => {
            map.current?.fitBounds(operationalBounds(data.zones, data.assets), {
              padding: 70,
              maxZoom: 15,
              duration: 700,
            });
          }}
        >
          <Scan size={18} />
        </button>
        <button
          aria-label="تغییر زاویه نقشه"
          title="نمای مایل / نمای عمودی"
          className={!flat ? "active" : ""}
          onClick={() => {
            map.current?.easeTo({
              pitch: flat ? 45 : 0,
              bearing: flat ? -12 : 0,
              duration: 700,
            });
            setFlat(!flat);
          }}
        >
          <span className="map-3d">{flat ? "45°" : "2D"}</span>
        </button>
        <button
          aria-label="لایه‌ها"
          aria-expanded={showLayers}
          className={showLayers ? "active" : ""}
          onClick={() => setShowLayers(!showLayers)}
        >
          <Layers size={18} />
        </button>
      </div>
      {showLayers && (
        <div className="layer-panel">
          <div className="layer-panel-header">
            <span className="layer-panel-icon"><Layers size={17}/></span>
            <div><b>لایه‌های نقشه</b><small>{fa(Object.values(layers).filter(Boolean).length + Number(labels) + Number(buildings))} لایه فعال</small></div>
            <button aria-label="بستن پنل لایه‌ها" onClick={() => setShowLayers(false)}><X size={15}/></button>
          </div>
          <div className="layer-panel-scroll">
          <span className="layer-section-title">عوارض OpenStreetMap</span>
          <label>
            <input
              type="checkbox"
              checked={labels}
              disabled={basemap === "street"}
              onChange={() => setLabels(!labels)}
            />
            نام خیابان‌ها و مکان‌ها
          </label>
          <label>
            <input
              type="checkbox"
              checked={buildings}
              disabled={basemap === "street"}
              onChange={() => setBuildings(!buildings)}
            />
            ساختمان‌ها
          </label>
          {basemap === "street" && (
            <small className="layer-help">
              تفکیک عوارض در نمای عملیاتی شب در دسترس است.
            </small>
          )}
          <span className="layer-section-title">لایه‌های عملیاتی نمونه</span>
          {Object.entries(layerNames).map(([k, v]) => (
            <label key={k}>
              <input
                type="checkbox"
                checked={layers[k as keyof typeof layers]}
                onChange={() =>
                  setLayers({
                    ...layers,
                    [k]: !layers[k as keyof typeof layers],
                  })
                }
              />
              {v}
            </label>
          ))}
          {layers.patrolCoverage && (
            <small className="layer-help">
              {coverage.isError || segments.isError
                ? "دریافت پوشش گشت ناموفق بود"
                : coverage.isPending || segments.isPending
                  ? "در حال دریافت پوشش گشت…"
                  : "سبز: در مهلت · نارنجی: دیرکرد · خاکستری: بدون بازدید؛ برای جزئیات روی خط یا تأسیسات بزنید."}
            </small>
          )}
          {layers.risk && (
            <small className="layer-help">
              {risk.isError
                ? "دریافت ریسک ناموفق بود"
                : risk.isPending
                  ? "در حال دریافت ریسک…"
                  : "سبز: ریسک کمتر · نارنجی: میانه · قرمز: ریسک بیشتر؛ رنگ نسبت به مجموع وزن‌هاست."}
            </small>
          )}
          </div>
        </div>
      )}
      <div className="map-status-dock">
      <div className="map-bottom">
        <span>
          {props.patrolPlan
            ? "پیش‌نمایش برنامه گشت · خطوط مستقیم شماتیک · ETA تخمینی"
            : "گشت‌ها و رخدادها: دادهٔ نمونه · عدد کنار نام: سرعت (کیلومتر بر ساعت)"}
        </span>
        <div className="legend">
          <span>
            <i style={{ background: "#59d6c4" }} />
            برخط
          </span>
          <span>
            <i style={{ background: "#efbe69" }} />
            هشدار
          </span>
          <span>
            <i style={{ background: "#788e9a" }} />
            قطع
          </span>
        </div>
      </div>
      <div className="map-coordinate-bar">
        <span>WGS 84</span>
        <span dir="ltr">
          {view.lat.toFixed(5)}° N · {view.lon.toFixed(5)}° E
        </span>
        <span dir="ltr">Z {view.zoom.toFixed(1)}</span>
      </div>
      </div>
      <GisTools
        map={ready ? map.current : null}
        hazardDrawing={props.hazardDrawing}
      />
      <div className="map-attribution" dir="ltr">
        ©{" "}
        <a
          href="https://www.openstreetmap.org/copyright"
          target="_blank"
          rel="noopener noreferrer"
        >
          OpenStreetMap
        </a>{" "}
        contributors
        {basemap === "night" && (
          <>
            {" "}
            ·{" "}
            <a
              href="https://openfreemap.org/"
              target="_blank"
              rel="noopener noreferrer"
            >
              OpenFreeMap
            </a>{" "}
            · ©{" "}
            <a
              href="https://openmaptiles.org/"
              target="_blank"
              rel="noopener noreferrer"
            >
              OpenMapTiles
            </a>
          </>
        )}
      </div>
    </div>
  );
}
