import {
  Car,
  Eye,
  Layers,
  LocateFixed,
  Minus,
  Navigation,
  Plus,
  UserRound,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fa } from "../../api";
import type { Asset, Data, Incident } from "../../types";
const X = (n: number) => ((n - 49.58) / 0.6) * 1000;
const Y = (n: number) => ((31.01 - n) / 0.46) * 720;
const roads = [
  [
    [49.6, 30.8],
    [49.7, 30.82],
    [49.78, 30.76],
    [49.86, 30.8],
    [49.94, 30.77],
    [50.06, 30.82],
    [50.16, 30.86],
  ],
  [
    [49.68, 30.98],
    [49.73, 30.94],
    [49.8, 30.89],
    [49.86, 30.8],
    [49.91, 30.72],
    [49.96, 30.62],
  ],
  [
    [49.6, 30.64],
    [49.72, 30.69],
    [49.78, 30.76],
    [49.83, 30.65],
    [49.98, 30.65],
    [50.12, 30.73],
  ],
  [
    [49.67, 30.84],
    [49.73, 30.94],
    [49.87, 30.88],
    [49.95, 30.92],
    [50.1, 30.88],
  ],
  [
    [49.91, 30.72],
    [50.05, 30.73],
    [50.1, 30.88],
    [50.13, 30.99],
  ],
];
export default function Map({
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
  const [zoom, setZoom] = useState(1),
    [pan, setPan] = useState({ x: 0, y: 0 }),
    [layers, setLayers] = useState({
      zones: true,
      assets: true,
      incidents: true,
      coverage: false,
      heat: false,
      cameras: false,
    }),
    [showLayers, setShowLayers] = useState(false);
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(
    null,
  );
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => {
    if (focus) {
      setZoom(1.35);
      setPan({ x: 500 - X(focus.lon), y: 360 - Y(focus.lat) });
    }
  }, [focus?.id]);
  const changeZoom = (delta: number) =>
    setZoom((z) => Math.min(2.8, Math.max(0.8, z + delta)));
  const poly = (pts: number[][]) =>
    pts.map(([lon, lat]) => `${X(lon)},${Y(lat)}`).join(" ");
  return (
    <div className="map-shell">
      <svg
        ref={svg}
        className="map-svg"
        viewBox="0 0 1000 720"
        role="img"
        aria-label="نقشه عملیاتی نمایشی آغاجاری؛ برای انتخاب روی گشت یا رخداد کلیک کنید"
        onWheel={(e) => changeZoom(e.deltaY < 0 ? 0.1 : -0.1)}
        onPointerDown={(e) => {
          if ((e.target as Element).closest("[data-marker]")) return;
          drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          const scale = 1000 / (svg.current?.clientWidth || 1000) / zoom;
          setPan({
            x: drag.current.px + (e.clientX - drag.current.x) * scale,
            y: drag.current.py + (e.clientY - drag.current.y) * scale,
          });
        }}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
      >
        <defs>
          <pattern
            id="grid"
            width="55"
            height="55"
            patternUnits="userSpaceOnUse"
          >
            <path
              d="M55 0H0V55"
              fill="none"
              stroke="#34515a"
              strokeWidth=".5"
              opacity=".3"
            />
          </pattern>
          <radialGradient id="heat">
            <stop stopColor="#f46b51" stopOpacity=".65" />
            <stop offset="1" stopColor="#f46b51" stopOpacity="0" />
          </radialGradient>
          <filter id="glow">
            <feGaussianBlur stdDeviation="3" />
          </filter>
        </defs>
        <rect width="1000" height="720" fill="#10222b" />
        <rect width="1000" height="720" fill="url(#grid)" />
        <g
          transform={`translate(500 360) scale(${zoom}) translate(-500 -360) translate(${pan.x} ${pan.y})`}
        >
          <g fill="none" stroke="#29414a" strokeWidth=".8" opacity=".75">
            {Array.from({ length: 40 }, (_, i) => (
              <path
                key={i}
                d={`M ${-160 + i * 21} -40 C ${270 + i * 9} ${100 + i * 2}, ${-100 + i * 25} ${240 + i * 3}, ${200 + i * 22} 330 S ${320 + i * 24} 580, ${150 + i * 30} 800`}
              />
            ))}
          </g>
          <path
            d="M70 -30 C250 200 40 310 160 420S 280 580 140 770"
            fill="none"
            stroke="#173d4b"
            strokeWidth="21"
          />
          <path
            d="M70 -30 C250 200 40 310 160 420S 280 580 140 770"
            fill="none"
            stroke="#285363"
            strokeWidth="1"
          />
          {roads.map((r, i) => (
            <g key={i}>
              <polyline
                points={poly(r)}
                fill="none"
                stroke="#0b171e"
                strokeWidth="8"
                strokeLinejoin="round"
              />
              <polyline
                points={poly(r)}
                fill="none"
                stroke="#45606a"
                strokeWidth={i === 0 ? 3 : 2}
                strokeLinejoin="round"
              />
              <polyline
                points={poly(r)}
                fill="none"
                stroke="#a7babf"
                strokeOpacity=".25"
                strokeDasharray="4 8"
              />
            </g>
          ))}
          {layers.zones &&
            data.zones.map((z, i) => (
              <g key={z.id}>
                <polygon
                  points={poly(z.points)}
                  fill={["#e4b659", "#51b8b8", "#5ac6a2"][i % 3]}
                  fillOpacity=".06"
                  stroke={["#a99155", "#438c94", "#3a7a73"][i % 3]}
                  strokeWidth="1.5"
                  strokeDasharray="5 5"
                />
                <text
                  x={X(z.points[0][0])}
                  y={Y(z.points[0][1]) - 15}
                  className="zone-label"
                >
                  {z.name}
                </text>
              </g>
            ))}
          {layers.coverage &&
            data.zones
              .filter((z) => z.coverage === "weak")
              .map((z) => (
                <polygon
                  key={`coverage-${z.id}`}
                  points={z.points
                    .map(([lon, lat]) => `${X(lon)},${Y(lat)}`)
                    .join(" ")}
                  fill="#b98fe3"
                  fillOpacity=".13"
                  stroke="#b98fe3"
                  strokeDasharray="4 7"
                />
              ))}
          {layers.heat &&
            data.incidents.map((i) => (
              <circle
                key={i.id}
                cx={X(i.lon)}
                cy={Y(i.lat)}
                r="85"
                fill="url(#heat)"
              />
            ))}
          {[
            ["آغاجاری", 49.76, 30.81],
            ["کرنج", 49.92, 30.96],
            ["پارسی", 50.08, 30.68],
            ["امیدیه", 49.64, 30.67],
          ].map(([n, lo, la]) => (
            <g key={String(n)}>
              <circle
                cx={X(Number(lo))}
                cy={Y(Number(la))}
                r="3"
                fill="#89a4b0"
              />
              <text
                className="town-label"
                x={X(Number(lo))}
                y={Y(Number(la)) - 14}
              >
                {n}
              </text>
            </g>
          ))}
          {focus && (
            <circle
              cx={X(focus.lon)}
              cy={Y(focus.lat)}
              r="85"
              fill="#fa7457"
              fillOpacity=".05"
              stroke="#fa7457"
              strokeDasharray="6 8"
            />
          )}
          {layers.assets &&
            data.assets.map((a) => {
              const t =
                replay < 100
                  ? a.track[Math.min(5, Math.floor(replay / 20))]
                  : a;
              const x = X(t.lon),
                y = Y(t.lat),
                color =
                  a.status === "offline"
                    ? "#788e9a"
                    : a.status === "warning"
                      ? "#efbe69"
                      : "#59d6c4";
              return (
                <g
                  key={a.id}
                  data-marker="true"
                  tabIndex={0}
                  role="button"
                  aria-label={a.name}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onAsset(a);
                  }}
                  onClick={() => onAsset(a)}
                  className="map-marker"
                >
                  {(selected === a.id || (replay < 100 && !selected)) && (
                    <polyline
                      points={a.track
                        .map((t) => `${X(t.lon)},${Y(t.lat)}`)
                        .join(" ")}
                      fill="none"
                      stroke={color}
                      strokeWidth="3"
                      strokeDasharray="6 5"
                    />
                  )}
                  {selected === a.id && (
                    <circle
                      cx={x}
                      cy={y}
                      r="32"
                      fill={color}
                      fillOpacity=".1"
                      stroke={color}
                      strokeOpacity=".3"
                    />
                  )}
                  <rect
                    x={x - 16}
                    y={y - 16}
                    width="32"
                    height="32"
                    rx="10"
                    fill="#102a31"
                    stroke={color}
                    strokeWidth="1.3"
                  />
                  <foreignObject x={x - 9} y={y - 10} width="20" height="22">
                    <div style={{ color }}>
                      {a.kind === "vehicle" ? (
                        <Car size={18} />
                      ) : (
                        <UserRound size={18} />
                      )}
                    </div>
                  </foreignObject>
                  <rect
                    x={x - 38}
                    y={y + 21}
                    width="76"
                    height="24"
                    rx="5"
                    fill="#0d1c25"
                    fillOpacity=".93"
                  />
                  <text x={x} y={y + 37} className="asset-label">
                    {a.name}
                  </text>
                </g>
              );
            })}
          {layers.incidents &&
            data.incidents
              .filter((i) => i.status !== "closed")
              .map((i) => (
                <g
                  key={i.id}
                  data-marker="true"
                  role="button"
                  tabIndex={0}
                  aria-label={i.title}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onIncident(i);
                  }}
                  onClick={() => onIncident(i)}
                  className="map-marker"
                >
                  <circle
                    cx={X(i.lon) + 22}
                    cy={Y(i.lat) - 23}
                    r="22"
                    fill="#ef725d"
                    fillOpacity=".12"
                    className={i.severity === "critical" ? "pulse-ring" : ""}
                  />
                  <circle
                    cx={X(i.lon) + 22}
                    cy={Y(i.lat) - 23}
                    r="12"
                    fill={i.severity === "critical" ? "#ef725d" : "#d4a75c"}
                  />
                  <text
                    x={X(i.lon) + 22}
                    y={Y(i.lat) - 18}
                    textAnchor="middle"
                    fill="#15202a"
                    fontWeight="700"
                  >
                    !
                  </text>
                </g>
              ))}
          {layers.cameras &&
            [
              [640, 260],
              [590, 410],
              [345, 240],
            ].map(([x, y], i) => (
              <g key={i}>
                <circle cx={x} cy={y} r="14" fill="#32475b" />
                <foreignObject x={x - 8} y={y - 8} width="18" height="18">
                  <Eye size={16} color="#c0cfea" />
                </foreignObject>
                <text x={x} y={y + 29} className="asset-label">
                  دوربین نمونه {fa(i + 1)}
                </text>
              </g>
            ))}
        </g>
      </svg>
      <div className="map-top">
        <div className="map-tag">
          <span className="live-dot" /> لایه عملیاتی آغاجاری{" "}
          <span className="muted">/</span> <small>نقشه شماتیک</small>
        </div>
        <div className="north">
          <Navigation size={18} />
          <span>N</span>
        </div>
      </div>
      <div className="map-tools">
        <button
          title="بزرگ‌نمایی"
          aria-label="بزرگ‌نمایی"
          onClick={() => changeZoom(0.2)}
        >
          <Plus size={18} />
        </button>
        <button
          title="کوچک‌نمایی"
          aria-label="کوچک‌نمایی"
          onClick={() => changeZoom(-0.2)}
        >
          <Minus size={18} />
        </button>
        <button
          title="نمایش کل منطقه"
          aria-label="نمایش کل منطقه"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          <LocateFixed size={18} />
        </button>
        <button
          title="لایه‌ها"
          aria-label="لایه‌ها"
          className={showLayers ? "active" : ""}
          onClick={() => setShowLayers(!showLayers)}
        >
          <Layers size={18} />
        </button>
      </div>
      {showLayers && (
        <div className="layer-panel">
          <b>لایه‌های نقشه</b>
          {Object.entries({
            zones: "محدوده‌ها",
            assets: "گشت‌ها و نیروها",
            incidents: "رخدادها",
            coverage: "پوشش ارتباطی",
            heat: "تراکم رخداد",
            cameras: "دوربین‌های نمونه · فاز ۳",
          }).map(([k, v]) => (
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
        </div>
      )}
      <div className="map-bottom">
        <span>مختصات و عوارض نمایشی · فاقد اعتبار عملیاتی</span>
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
    </div>
  );
}
