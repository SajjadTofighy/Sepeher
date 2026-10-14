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
import { useEffect,useState } from "react";
import { api,fa,labels,timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { download } from "../../shared/lib/download";
import { Badge,Modal } from "../../shared/ui/primitives";
import type { Data,Incident,NearbyPatrol } from "../../types";
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
    [chosen, setChosen] = useState(""),
    [note, setNote] = useState("");
  useEffect(() => {
    api<NearbyPatrol[]>(`/incidents/${i.id}/nearby`)
      .then((r) => {
        setNearby(r);
        setChosen(r[0]?.asset_id || "");
      })
      .catch(() => setNearby([]));
    setNote("");
  }, [i.id]);
  const next = flow[flow.indexOf(i.status) + 1];
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
            <p>
              زمان رسیدن تخمینی است: فاصله مستقیم × ضریب ۱٫۳ با سرعت ۴۵ کیلومتر
              بر ساعت؛ شبکه راه قابل مسیریابی هنوز در دسترس نیست.
            </p>
            <div className="nearby-list">
              {nearby.slice(0, 3).map((a) => (
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
                    {fa(a.distance_km)} کیلومتر مستقیم
                  </span>
                </label>
              ))}
            </div>
          </div>
          {i.assigned_to && (
            <p className="assigned-banner">
              <CheckCircle2 size={18} />
              ارجاع به {data.assets.find((a) => a.id === i.assigned_to)?.name}
              {i.arrived_at
                ? " · گشت در محل است"
                : i.eta_minutes
                  ? ` · رسیدن حدود ${fa(Math.round(i.eta_minutes))} دقیقه`
                  : ""}
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
