import { visibleTrack, playbackPosition, routeColors } from "./trackPlayback";
import { useEffect, useRef, useState } from "react";
import {
  Car,
  LocateFixed,
  Map as MapIcon,
  Minus,
  Moon,
  Plus,
} from "lucide-react";
import type { Asset, Data, Incident } from "../../types";
import { OMIDIYEH_CENTER, type BasemapMode } from "./mapStyle";

// The same geographic coordinates projected to Web Mercator. No WebGL required.
const world = (lon: number, lat: number, zoom: number) => {
  const size = 256 * 2 ** zoom;
  const sin = Math.sin((Math.max(-85, Math.min(85, lat)) * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * size,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size,
  };
};
const coordinate = (x: number, y: number, zoom: number) => {
  const size = 256 * 2 ** zoom;
  return {
    lon: (x / size) * 360 - 180,
    lat: (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / size))) * 180) / Math.PI,
  };
};
export default function StreetMapFallback({
  data,
  onAsset,
  onIncident,
  selected,
  focus,
  replay = 100,
}: {
  data: Data;
  onAsset: (a: Asset) => void;
  onIncident: (i: Incident) => void;
  selected?: string;
  focus?: Incident | null;
  replay?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    x: number;
    y: number;
    center: { x: number; y: number };
  } | null>(null);
  const [size, setSize] = useState({ width: 800, height: 560 });
  const [view, setView] = useState({
    lon: OMIDIYEH_CENTER[0],
    lat: OMIDIYEH_CENTER[1],
    zoom: 13,
  });
  const [mode, setMode] = useState<BasemapMode>("night");
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([e]) =>
      setSize({ width: e.contentRect.width, height: e.contentRect.height }),
    );
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (focus) setView({ lon: focus.lon, lat: focus.lat, zoom: 15 });
  }, [focus?.id]);
  useEffect(() => {
    const asset = data.assets.find((a) => a.id === selected);
    if (asset) setView((v) => ({ ...v, lon: asset.lon, lat: asset.lat }));
  }, [selected]);
  const center = world(view.lon, view.lat, view.zoom);
  const left = center.x - size.width / 2,
    top = center.y - size.height / 2;
  const project = (lon: number, lat: number) => {
    const p = world(lon, lat, view.zoom);
    return { x: p.x - left, y: p.y - top };
  };
  const tiles = [];
  const n = 2 ** view.zoom;
  for (
    let x = Math.floor(left / 256);
    x <= Math.floor((left + size.width) / 256);
    x++
  ) {
    for (
      let y = Math.floor(top / 256);
      y <= Math.floor((top + size.height) / 256);
      y++
    ) {
      if (y < 0 || y >= n) continue;
      const tileX = ((x % n) + n) % n;
      const url = `https://tile.openstreetmap.org/${view.zoom}/${tileX}/${y}.png`;
      tiles.push(
        <img
          key={`${mode}-${view.zoom}-${x}-${y}`}
          className="street-tile"
          alt=""
          draggable={false}
          src={url}
          style={{ left: x * 256 - left, top: y * 256 - top }}
          onLoad={() => setStatus((s) => (s === "error" ? s : "ready"))}
          onError={() => setStatus("error")}
        />,
      );
    }
  }
  const zoom = (delta: number) =>
    setView((v) => ({ ...v, zoom: Math.max(7, Math.min(19, v.zoom + delta)) }));
  return (
    <div
      ref={ref}
      className={`map-shell omidiyeh-map street-fallback ${mode}`}
      data-map-engine="raster"
      role="region"
      aria-label="نقشه واقعی امیدیه بدون WebGL"
      onPointerDown={(e) => {
        if ((e.target as HTMLElement).closest("button,a,input")) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        drag.current = { x: e.clientX, y: e.clientY, center };
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        const p = coordinate(
          drag.current.center.x - e.clientX + drag.current.x,
          drag.current.center.y - e.clientY + drag.current.y,
          view.zoom,
        );
        setView((v) => ({ ...v, ...p }));
      }}
      onPointerUp={() => {
        drag.current = null;
      }}
      onPointerCancel={() => {
        drag.current = null;
      }}
    >
      <div className="street-tile-pane">{tiles}</div>
      <svg
        className="street-overlay"
        width={size.width}
        height={size.height}
        aria-hidden="true"
      >
        {data.zones.map((z, i) => (
          <polygon
            key={z.id}
            points={z.points
              .map(([lon, lat]) => {
                const p = project(lon, lat);
                return `${p.x},${p.y}`;
              })
              .join(" ")}
            fill={["#d2ad66", "#59b8af", "#76ba9a"][i % 3]}
            fillOpacity=".08"
            stroke={["#d2ad66", "#59b8af", "#76ba9a"][i % 3]}
            strokeDasharray="6 5"
          />
        ))}
        {data.assets
          .filter((a) => a.kind === "vehicle" || a.id === selected)
          .map((a, index) => (
            <polyline
              key={a.id}
              points={visibleTrack(a.track, replay)
                .map((t) => {
                  const p = project(t.lon, t.lat);
                  return `${p.x},${p.y}`;
                })
                .join(" ")}
              fill="none"
              stroke={routeColors[index % routeColors.length]}
              strokeWidth="3"
              strokeDasharray="6 5"
            />
          ))}
      </svg>
      {data.assets.map((a) => {
        const t = playbackPosition(a, replay);
        const p = project(t.lon, t.lat);
        return (
          <button
            key={a.id}
            className={`gl-asset fallback-marker ${a.status} ${a.id === selected ? "selected" : ""}`}
            style={{ left: p.x, top: p.y }}
            aria-label={a.name}
            onClick={() => onAsset(a)}
          >
            <span className="marker-symbol">
              <Car size={18} />
            </span>
            <span className="marker-label">{a.name}</span>
          </button>
        );
      })}
      {data.incidents
        .filter((i) => i.status !== "closed")
        .map((i) => {
          const p = project(i.lon, i.lat);
          return (
            <button
              key={i.id}
              className={`gl-incident fallback-marker ${i.severity}`}
              style={{ left: p.x, top: p.y }}
              aria-label={i.title}
              onClick={() => onIncident(i)}
            >
              !
            </button>
          );
        })}
      <div className="map-top">
        <div className="map-location-card">
          <span className="map-kicker">OMIDIYEH / KHUZESTAN</span>
          <div>
            <span className="map-location-dot" />
            <strong>امیدیه</strong>
            <span>خوزستان، ایران</span>
          </div>
          <small>نقشهٔ معابر و عوارض شهری</small>
        </div>
      </div>
      <div className="basemap-switch" role="group" aria-label="سبک نقشه">
        <button
          aria-pressed={mode === "night"}
          onClick={() => {
            setMode("night");
            setStatus("loading");
          }}
        >
          <Moon size={14} />
          عملیاتی شب
        </button>
        <button
          aria-pressed={mode === "street"}
          onClick={() => {
            setMode("street");
            setStatus("loading");
          }}
        >
          <MapIcon size={14} />
          خیابانی OSM
        </button>
      </div>
      <div className={`map-source-status ${status}`} role="status">
        <i />
        {status === "error"
          ? "دریافت بخشی از نقشه ناموفق بود؛ اتصال را بررسی کنید"
          : status === "loading"
            ? "در حال دریافت نقشه…"
            : "OpenStreetMap · نمای دوبعدی سازگار"}
      </div>
      <div className="map-tools">
        <button aria-label="بزرگ‌نمایی" onClick={() => zoom(1)}>
          <Plus size={18} />
        </button>
        <button aria-label="کوچک‌نمایی" onClick={() => zoom(-1)}>
          <Minus size={18} />
        </button>
        <button
          aria-label="بازگشت به امیدیه"
          onClick={() =>
            setView({
              lon: OMIDIYEH_CENTER[0],
              lat: OMIDIYEH_CENTER[1],
              zoom: 13,
            })
          }
        >
          <LocateFixed size={18} />
        </button>
      </div>
      <div className="map-bottom">
        <span>گشت‌ها و رخدادها: دادهٔ نمونه</span>
        <span>برای جابه‌جایی، نقشه را بکشید</span>
      </div>
      <div className="map-coordinate-bar">
        <span>WGS 84</span>
        <span dir="ltr">
          {view.lat.toFixed(5)}° N · {view.lon.toFixed(5)}° E
        </span>
        <span>Z {view.zoom}</span>
      </div>
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
      </div>
    </div>
  );
}
