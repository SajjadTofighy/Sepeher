import {
Car,
Check,
CheckCircle2,
Download,
History,
MapPin,
Printer,
ShieldAlert,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect,useState } from "react";
import { api,fa,labels,timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { download } from "../../shared/lib/download";
import { Badge,Modal } from "../../shared/ui/primitives";
import type { Data,Incident,NearbyPatrol, DispatchOptions, RoadRoute, RoutePlan } from "../../types";
import { printIncidentReport } from "./printReport";
import HazardDetails from "./HazardDetails";
const flow = [
  "detected",
  "confirmed",
  "assigned",
  "en_route",
  "on_scene",
  "closed",
];
export default function IncidentPanel({
  incident: i,
  data,
  busy,
  close,
  act,
  onMap,
  onDrawHazard,
}: {
  incident: Incident;
  data: Data;
  busy: boolean;
  close: () => void;
  act: Act;
  onMap: () => void;
  onDrawHazard: () => void;
}) {
  const [nearby, setNearby] = useState<NearbyPatrol[]>([]),
    [options, setOptions] = useState<DispatchOptions | null>(null),
    [chosen, setChosen] = useState(""),
    [note, setNote] = useState(""),
    [routeId, setRouteId] = useState("R1");
  useEffect(() => {
    api<DispatchOptions>(`/incidents/${i.id}/dispatch-options`)
      .then((r) => {
        setOptions(r);
        const rows = [...r.suggestions, ...r.needs_confirmation];
        setNearby(rows);
        setChosen(r.suggestions[0]?.asset_id || "");
      })
      .catch(() => setNearby([]));
    setNote("");
  }, [i.id]);
  const next = flow[flow.indexOf(i.status) + 1];
  const routes = useQuery({
    queryKey: ["incident-routes", i.id, chosen],
    queryFn: () => api<RoutePlan>(`/incidents/${i.id}/routes?asset_id=${encodeURIComponent(chosen)}`),
    enabled: next === "assigned" && !!chosen,
  });
  useEffect(() => setRouteId("R1"), [chosen]);
  const policy = data.policies.find((p) => p.id === i.policy_id);
  return (
    <Modal title="فرماندهی حادثه" onClose={close} wide>
      <div className="incident-detail">
        <section>
          <div className="detail-tags">
            <Badge value={i.severity} />
            <span className="mono">{i.id}</span>
            <Badge value={i.status} />
          </div>
          <h2 className="incident-title">{i.title}</h2>
          <p className="muted">
            <MapPin size={15} />
            {i.zone}
          </p>
          <p className="incident-description">{i.description}</p>
          <HazardDetails incident={i} act={act} busy={busy} onDraw={() => { onDrawHazard(); close(); }} />
          {!!i.emergency_contacts?.length && (
            <div className="detail-section">
              <h3>تماس‌های اضطراری</h3>
              {i.emergency_contacts.map((contact, index) => (
                <p key={index}>{contact.name} · {contact.role} · <span dir="ltr">{contact.phone}</span></p>
              ))}
            </div>
          )}
          {policy && (
            <p className="policy-source">
              <ShieldAlert size={15} />
              کشف خودکار · سیاست <b dir="ltr">{policy.id}</b> «{policy.name}» ·
              نسخه {fa(policy.version)}
            </p>
          )}
          <div className="incident-steps">
            {flow.map((s, j) => (
              <div
                key={s}
                className={flow.indexOf(i.status) >= j ? "done" : ""}
              >
                <span>
                  {flow.indexOf(i.status) > j ? <Check size={13} /> : fa(j + 1)}
                </span>
                <small>{labels[s]}</small>
              </div>
            ))}
          </div>
          <div className="detail-section">
            <h3>پیشنهاد گشت نزدیک</h3>
            <p>{options?.eta_basis}</p>
            <div className="nearby-list">
              {nearby.map((a) => (
                <label
                  key={a.asset_id}
                  className={chosen === a.asset_id ? "chosen" : ""}
                >
                  <input
                    type="radio"
                    name="patrol"
                    value={a.asset_id}
                    checked={chosen === a.asset_id}
                    onChange={() => setChosen(a.asset_id)}
                  />
                  <Car size={20} />
                  <strong>{a.name}</strong>
                  <span>
                    ~{fa(Math.round(a.eta_minutes))} دقیقه ·{" "}
                    {fa(a.distance_km)} کیلومتر {a.distance_type === "road" ? "روی شبکه راه" : "مستقیم"}
                    {a.needs_confirmation && " · موقعیت تازه نیست؛ پیش از اعزام تأیید کنید"}
                  </span>
                </label>
              ))}
            </div>
            {!!options?.excluded.length && (
              <details>
                <summary>گشت‌های کنارگذاشته ({fa(options.excluded.length)})</summary>
                <ul>{options.excluded.map((x) => <li key={x.asset_id}>{x.name}: {x.reason}</li>)}</ul>
              </details>
            )}
          </div>
          {next === "assigned" && !!chosen && (
            <div className="detail-section">
              <h3>انتخاب مسیر اعزام</h3>
              {routes.isLoading && <p className="muted">در حال محاسبه مسیرها…</p>}
              {routes.data && !routes.data.routes.length && (
                <p className="muted">مسیر روی شبکه راه یافت نشد؛ زمان رسیدن با فاصله مستقیم تخمین زده می‌شود.</p>
              )}
              {!!routes.data?.routes.length && (
                <>
                  <RoutePreview routes={routes.data.routes} active={routeId} />
                  {!!routes.data.avoided_areas && (
                    <p className="muted">{fa(routes.data.avoided_areas)} محدوده خطر باز از مسیرها کنار گذاشته شد.</p>
                  )}
                  <div className="nearby-list">
                    {routes.data.routes.map((r) => (
                      <label key={r.id} className={routeId === r.id ? "chosen" : ""}>
                        <input type="radio" name="route" checked={routeId === r.id} onChange={() => setRouteId(r.id)} />
                        <strong>{r.label}</strong>
                        <span>
                          ~{fa(Math.round(r.eta_minutes))} دقیقه · {fa(r.distance_km)} کیلومتر
                          {r.access_km > 0.05 && ` · ${fa(r.access_km)} کیلومتر بیرون از راه`}
                        </span>
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          {i.assigned_to && (
            <p className="assigned-banner">
              <CheckCircle2 size={18} />
              ارجاع به {data.assets.find((a) => a.id === i.assigned_to)?.name}
              {i.arrived_at
                ? " · گشت در محل است"
                : i.eta_minutes
                  ? ` · رسیدن حدود ${fa(Math.round(i.eta_minutes))} دقیقه`
                  : ""}
              {i.route && ` · ${i.route.label}، ${fa(i.route.distance_km)} کیلومتر روی شبکه راه (روی نقشه)`}
            </p>
          )}
          {next && (
            <>
              <label className="field">
                {next === "closed" ? "گزارش خاتمه (الزامی)" : "یادداشت اقدام"}
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="شرح بررسی و اقدام انجام‌شده…"
                />
              </label>
              <button
                className="primary full"
                disabled={
                  busy ||
                  (next === "closed" && !note.trim()) ||
                  (next === "assigned" && !chosen)
                }
                onClick={() =>
                  act(
                    () =>
                      api(`/incidents/${i.id}/transition`, "POST", {
                        status: next,
                        asset_id: chosen,
                        route_id: next === "assigned" && routes.data?.routes.length ? routeId : undefined,
                        note,
                      }),
                    `وضعیت پرونده: ${labels[next]}`,
                  )
                }
              >
                <Check size={17} />
                {next === "confirmed"
                  ? "تأیید حادثه"
                  : next === "assigned"
                    ? "تأیید و اعزام گشت"
                    : next === "en_route"
                      ? "ثبت حرکت گشت"
                      : next === "on_scene"
                        ? "ثبت حضور در محل"
                        : "ثبت گزارش و خاتمه"}
              </button>
            </>
          )}
        </section>
        <aside className="incident-timeline">
          <h3>
            <History size={18} />
            خط زمانی پرونده
          </h3>
          {i.timeline.map((e, j) => (
            <div className="timeline-item" key={j}>
              <i />
              <small>
                {timeFa(e.time)} · {e.actor}
              </small>
              <p>{e.action}</p>
            </div>
          ))}
          <div className="timeline-spacer" />
          <button
            className="secondary full"
            onClick={() => {
              onMap();
              close();
            }}
          >
            <MapPin size={16} />
            نمایش روی نقشه
          </button>
          <button
            className="primary full"
            onClick={() => act(() => printIncidentReport(i, data), "گزارش آماده چاپ شد")}
          >
            <Printer size={16} />
            چاپ گزارش حادثه
          </button>
          <button
            className="secondary full"
            onClick={async () => {
              const r = await act(
                () => api(`/incidents/${i.id}/report`),
                "گزارش دریافت شد",
              );
              if (r) download(`${i.id}.json`, r);
            }}
          >
            <Download size={16} />
            دریافت گزارش JSON
          </button>
        </aside>
      </div>
    </Modal>
  );
}

/** Schematic preview of route choices before dispatch; the map shows the dispatched route. */
function RoutePreview({ routes, active }: { routes: RoadRoute[]; active: string }) {
  const points = routes.flatMap((r) => r.path);
  const [x0, x1] = [Math.min(...points.map((p) => p[0])), Math.max(...points.map((p) => p[0]))];
  const [y0, y1] = [Math.min(...points.map((p) => p[1])), Math.max(...points.map((p) => p[1]))];
  const scale = 280 / Math.max(x1 - x0, y1 - y0, 1e-6);
  const xy = (p: number[]) => `${8 + (p[0] - x0) * scale},${8 + (y1 - p[1]) * scale}`;
  const ordered = [...routes.filter((r) => r.id !== active), ...routes.filter((r) => r.id === active)];
  return (
    <svg className="route-preview" viewBox={`0 0 ${16 + (x1 - x0) * scale} ${16 + (y1 - y0) * scale}`}
      role="img" aria-label="پیش‌نمایش مسیرهای پیشنهادی" style={{ width: "100%", maxHeight: 180 }}>
      {ordered.map((r) => (
        <polyline key={r.id} points={r.path.map(xy).join(" ")} fill="none" strokeLinecap="round" strokeLinejoin="round"
          stroke={r.id === active ? "#4fb3ff" : "#9aa7b3"} strokeWidth={r.id === active ? 4 : 2}
          strokeDasharray={r.id === active ? undefined : "4 4"} />
      ))}
      <circle cx={xy(routes[0].path[0]).split(",")[0]} cy={xy(routes[0].path[0]).split(",")[1]} r={5} fill="#7bd88f" />
      <circle cx={xy(routes[0].path.at(-1)!).split(",")[0]} cy={xy(routes[0].path.at(-1)!).split(",")[1]} r={5} fill="#ef737e" />
    </svg>
  );
}
