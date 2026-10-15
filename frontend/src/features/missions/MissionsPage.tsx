import { Activity, Car, Check, CheckCircle2, Clock3, MapPin, RadioTower, Route } from "lucide-react";
import { api,fa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge } from "../../shared/ui/primitives";
import type { Data } from "../../types";
import PatrolPlanner from "./PatrolPlanner";
import MissionCommandsPanel from "../mission-commands/MissionCommandsPanel";
import { useEffect } from "react";

export default function MissionsPage({
  data,
  busy,
  act,
  focusId,
  theme,
}: {
  data: Data;
  busy: boolean;
  act: Act;
  focusId?: string;
  theme: "dark" | "light";
}) {
  useEffect(() => {
    if (focusId) document.getElementById(`mission-${focusId}`)?.scrollIntoView({ block: "center" });
  }, [focusId]);
  const active = data.missions.filter((m) => m.status !== "completed");
  const completed = data.missions.filter((m) => m.status === "completed").length;
  const average = data.missions.length
    ? Math.round(data.missions.reduce((sum, m) => sum + m.progress, 0) / data.missions.length)
    : 0;
  return (
    <section className="missions-workspace">
    <header className="missions-hero">
      <div><span className="missions-kicker"><RadioTower size={12}/> PATROL OPERATIONS</span><h1>عملیات گشت <i/></h1><p>برنامه‌ریزی، پایش و کنترل مأموریت‌های میدانی در یک نمای عملیاتی</p></div>
      <div className="missions-shift"><span className="live-dot"/><div><b>شیفت عملیاتی فعال</b><small>{fa(active.length)} مأموریت در جریان</small></div></div>
    </header>
    <div className="mission-kpis">
      <article className="mission-kpi total"><span><Route size={20}/></span><div><small>کل مأموریت‌ها</small><b>{fa(data.missions.length)}</b><p>ماموریت ثبت‌شده</p></div></article>
      <article className="mission-kpi active"><span><Activity size={20}/></span><div><small>در حال اجرا</small><b>{fa(active.length)}</b><p>گشت فعال میدانی</p></div></article>
      <article className="mission-kpi progress-kpi"><span><Clock3 size={20}/></span><div><small>میانگین پیشرفت</small><b>{fa(average)}٪</b><p>پیشرفت کل عملیات</p></div></article>
      <article className="mission-kpi completed"><span><CheckCircle2 size={20}/></span><div><small>تکمیل‌شده</small><b>{fa(completed)}</b><p>مأموریت خاتمه‌یافته</p></div></article>
    </div>
    <PatrolPlanner data={data} busy={busy} act={act} theme={theme} />
    <MissionCommandsPanel act={act} busy={busy} />
    <div className="mission-section-head"><span><Route size={18}/></span><div><b>مأموریت‌های جاری</b><small>وضعیت، پیشرفت و ایستگاه‌های عملیاتی</small></div><em>{fa(data.missions.length)} مأموریت</em></div>
    <div className="mission-grid">
      {data.missions.map((m) => (
        <section className={`panel mission ${focusId === m.id ? "report-source-focus" : ""}`} id={`mission-${m.id}`} key={m.id}>
          <div className="mission-head">
            <div className="entity-icon">
              <Route size={23} />
            </div>
            <Badge value={m.status} />
          </div>
          <span className="eyebrow">{m.id}</span>
          <h2>{m.name}</h2>
          <p>
            <MapPin size={15} />
            {m.zone}
          </p>
          <div className="mission-assignee">
            <Car size={18} />
            {data.assets.find((a) => a.id === m.asset_id)?.name}
            <span>{fa(m.progress)}٪ تکمیل</span>
          </div>
          <div className="progress">
            <i style={{ width: m.progress + "%" }} />
          </div>
          <div className="checkpoints">
            {m.checkpoints.map((c, i) => (
              <div key={i} className={c.visited ? "visited" : ""}>
                <span>{c.visited ? <Check size={14} /> : fa(i + 1)}</span>
                {c.name}
                {c.due_at && <small>{new Date(c.due_at).toLocaleString("fa-IR", { timeZone: "Asia/Tehran" })}</small>}
              </div>
            ))}
          </div>
          <button
            className="secondary full"
            disabled={m.status === "completed" || busy || !!m.plan_id}
            onClick={() =>
              act(
                () => api(`/missions/${m.id}/checkpoint`, "POST"),
                "رسیدن به ایستگاه بعدی ثبت شد",
              )
            }
          >
            <MapPin size={16} />
            {m.plan_id ? "بازدید خودکار از پوشش گشت در مهلت" : "ثبت ایستگاه بعدی · نمایشی"}
          </button>
        </section>
      ))}
    </div>
    </section>
  );
}
