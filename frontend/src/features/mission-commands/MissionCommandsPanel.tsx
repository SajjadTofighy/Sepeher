import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, fa, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge } from "../../shared/ui/primitives";
import type { CommandCandidate, MissionCommand, MissionCommandPreview } from "../../types";

const TYPES: Record<MissionCommand["type"], string> = {
  visit_point: "بازدید نقطه", inspect_area: "بررسی محدوده", patrol_line: "گشت مسیر",
  check_alarm: "بررسی هشدار", presence: "حضور همه مخاطبان",
};
export const STATUS: Record<string, string> = {
  dispatched: "ارسال‌شده", delivered: "تحویل روی دستگاه", acknowledged: "پذیرفته", in_progress: "در حال اجرا",
  completed: "تکمیل", rejected: "ردشده", failed: "ناموفق", expired: "منقضی", cancelled: "لغوشده",
};
const POSITION: Record<string, string> = { fresh: "تازه", stale: "کهنه", no_fix: "بدون موقعیت", unknown: "نامعلوم", simulated: "شبیه‌سازی" };

function Candidates({ title, rows, chosen, toggle }: { title: string; rows: CommandCandidate[]; chosen: string[]; toggle?: (id: string) => void }) {
  if (!rows.length) return null;
  return (
    <fieldset className="patrol-plan-assets">
      <legend>{title} ({fa(rows.length)})</legend>
      {rows.map((r) => (
        <label key={r.asset_id}>
          {toggle && <input type="checkbox" checked={chosen.includes(r.asset_id)} onChange={() => toggle(r.asset_id)} />}
          {r.name} · موقعیت {POSITION[r.position_state] || r.position_state}
          {r.distance_m != null && ` · ${fa(Math.round(r.distance_m))} متر`}
          {r.reason && <small className="muted"> · {r.reason}</small>}
        </label>
      ))}
    </fieldset>
  );
}

export default function MissionCommandsPanel({ act, busy }: { act: Act; busy: boolean }) {
  const client = useQueryClient();
  const commands = useQuery({ queryKey: ["mission-commands"], queryFn: () => api<MissionCommand[]>("/mission-commands"), refetchInterval: 5000 });
  const [lon, setLon] = useState(49.71), [lat, setLat] = useState(30.71), [radius, setRadius] = useState(300);
  const [type, setType] = useState<MissionCommand["type"]>("visit_point");
  const [title, setTitle] = useState(""), [instructions, setInstructions] = useState("");
  const [priority, setPriority] = useState<"normal" | "urgent">("normal"), [ttl, setTtl] = useState(15);
  const [preview, setPreview] = useState<MissionCommandPreview | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const geometry = { type: "Point" as const, coordinates: [lon, lat] };
  const toggle = (id: string) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const loadPreview = async () => {
    const result = await act(() => api<MissionCommandPreview>("/mission-commands/preview", "POST", { geometry, radius_m: radius }));
    if (result) { setPreview(result); setChosen(result.eligible.map((r) => r.asset_id)); }
  };
  const send = async () => {
    if (!preview) return;
    const created = await act(
      () => api<MissionCommand>("/mission-commands", "POST", {
        idempotency_key: crypto.randomUUID(), type, title, instructions, priority, geometry, radius_m: radius,
        recipients: chosen, snapshot_id: preview.snapshot_id, ack_ttl_minutes: ttl,
      }),
      "فرمان مأموریت ارسال شد؛ تحویل فقط با دریافت روی دستگاه ثبت می‌شود",
    );
    if (created) { setPreview(null); setChosen([]); setTitle(""); await client.invalidateQueries({ queryKey: ["mission-commands"] }); }
    else await loadPreview();
  };
  const cancel = async (c: MissionCommand) => {
    const reason = window.prompt("دلیل لغو فرمان");
    if (!reason) return;
    await act(() => api(`/mission-commands/${c.id}/cancel`, "POST", { reason, revision: c.revision }), "فرمان لغو شد");
    await client.invalidateQueries({ queryKey: ["mission-commands"] });
  };
  return (
    <section className="patrol-planner patrol-planner-console">
      <header className="patrol-planner-head"><div><b>فرمان مأموریت مکانی</b><small>دستور انسانی با رسید تحویل، پذیرش و انجام؛ جدا از فرمان دستگاه</small></div></header>
      <div className="form-grid">
        <label className="field">طول جغرافیایی<input type="number" step="0.0001" value={lon} onChange={(e) => setLon(+e.target.value)} /></label>
        <label className="field">عرض جغرافیایی<input type="number" step="0.0001" value={lat} onChange={(e) => setLat(+e.target.value)} /></label>
        <label className="field">شعاع (متر)<input type="number" min={0} max={20000} value={radius} onChange={(e) => setRadius(+e.target.value)} /></label>
        <label className="field">نوع<select value={type} onChange={(e) => setType(e.target.value as MissionCommand["type"])}>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <label className="field">اولویت<select value={priority} onChange={(e) => setPriority(e.target.value as "normal" | "urgent")}><option value="normal">عادی</option><option value="urgent">فوری</option></select></label>
        <label className="field">مهلت پذیرش (دقیقه)<input type="number" min={1} max={1440} value={ttl} onChange={(e) => setTtl(+e.target.value)} /></label>
        <label className="field">عنوان<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <label className="field">شرح<input value={instructions} onChange={(e) => setInstructions(e.target.value)} /></label>
      </div>
      <div className="gis-actions">
        <button className="secondary" disabled={busy} onClick={loadPreview}>پیش‌نمایش مخاطبان</button>
        <button className="primary" disabled={busy || !preview || !chosen.length || title.trim().length < 3} onClick={send}>ارسال به {fa(chosen.length)} مخاطب</button>
      </div>
      {preview && (
        <>
          <p className="muted">محاسبه در {timeFa(preview.computed_at)}؛ فقط موقعیت تازه «داخل محدوده» حساب می‌شود.</p>
          <Candidates title="داخل محدوده با موقعیت تازه" rows={preview.eligible} chosen={chosen} toggle={toggle} />
          <Candidates title="نیازمند بازبینی (موقعیت کهنه/نامعلوم)" rows={preview.needs_review} chosen={chosen} toggle={toggle} />
          <Candidates title="خارج از محدوده" rows={preview.outside} chosen={chosen} toggle={toggle} />
          <Candidates title="غیرقابل تحویل" rows={preview.cannot_receive} chosen={chosen} />
        </>
      )}
      {commands.isError && <div className="error-banner">{(commands.error as Error).message}</div>}
      {(commands.data || []).slice(0, 20).map((c) => (
        <details key={c.id} className="patrol-plan-stop">
          <summary>
            <Badge value={c.status === "completed" ? "confirmed" : ["expired", "cancelled", "rejected", "failed"].includes(c.status) ? "closed" : "draft"} />{" "}
            {c.title} · {TYPES[c.type]} · {STATUS[c.status] || c.status}{c.priority === "urgent" && " · فوری"}{c.overdue && " · دیرکرد"}
          </summary>
          <ul>{c.recipients.map((r) => <li key={r.asset_id}>{r.name}: {STATUS[r.status]}{r.note && ` — ${r.note}`}</li>)}</ul>
          <ol className="muted">{c.timeline.map((e, i) => <li key={i}>{timeFa(e.time)} · {e.actor} · {e.action}{!e.applied && " (فقط سابقه)"}</li>)}</ol>
          {!["completed", "expired", "cancelled", "rejected", "failed"].includes(c.status) && <button className="secondary" disabled={busy} onClick={() => cancel(c)}>لغو فرمان</button>}
        </details>
      ))}
    </section>
  );
}
