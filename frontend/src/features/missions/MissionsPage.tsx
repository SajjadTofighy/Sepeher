import { Check, MapPin } from "lucide-react";
import { api,fa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge, StatStrip } from "../../shared/ui/primitives";
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
    <StatStrip items={[
      { label: "کل مأموریت‌ها", value: fa(data.missions.length) },
      { label: "در حال اجرا", value: fa(active.length) },
      { label: "میانگین پیشرفت", value: `${fa(average)}٪` },
      { label: "تکمیل‌شده", value: fa(completed) },
    ]} />
    <PatrolPlanner data={data} busy={busy} act={act} theme={theme} />
    <MissionCommandsPanel act={act} busy={busy} />
    <h2 className="section-heading">مأموریت‌های جاری <small>{fa(data.missions.length)} مورد</small></h2>
    <div className="mission-grid">
      {data.missions.map((m) => (
        <section className={`panel mission ${focusId === m.id ? "report-source-focus" : ""}`} id={`mission-${m.id}`} key={m.id}>
          <div className="mission-head">
            <h2>{m.name}</h2>
            <Badge value={m.status} />
          </div>
          <p className="mission-meta">
            <span dir="ltr">{m.id}</span> · {m.zone} · {data.assets.find((a) => a.id === m.asset_id)?.name} · {fa(m.progress)}٪
          </p>
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
            className="secondary"
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
