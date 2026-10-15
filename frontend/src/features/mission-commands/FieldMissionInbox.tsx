import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, timeFa } from "../../api";
import type { MissionCommand } from "../../types";
import { STATUS } from "./MissionCommandsPanel";

const ACTIONS: Record<string, [string, string][]> = {
  delivered: [["acknowledge", "پذیرش"], ["reject", "رد"]],
  dispatched: [["acknowledge", "پذیرش"], ["reject", "رد"]],
  acknowledged: [["start", "شروع"], ["complete", "تکمیل"], ["fail", "عدم امکان"]],
  in_progress: [["complete", "تکمیل"], ["fail", "عدم امکان"]],
};

export default function FieldMissionInbox() {
  const client = useQueryClient();
  const inbox = useQuery({ queryKey: ["field", "mission-commands"], queryFn: () => api<MissionCommand[]>("/tour/mission-commands"), refetchInterval: 10000 });
  const run = async (c: MissionCommand, action: string) => {
    const note = ["reject", "fail", "complete"].includes(action) ? window.prompt("توضیح (الزامی)") || "" : "";
    try {
      await api(`/tour/mission-commands/${c.id}/events`, "POST", { event_id: crypto.randomUUID(), action, note });
    } catch (error) {
      window.alert((error as Error).message);
    }
    await client.invalidateQueries({ queryKey: ["field", "mission-commands"] });
  };
  if (!inbox.data?.length) return null;
  return (
    <section className="panel">
      <h3>فرمان‌های مأموریت</h3>
      {inbox.data.map((c) => {
        const mine = c.recipients[0];
        return (
          <article key={c.id} className={c.priority === "urgent" ? "flag" : ""}>
            <b>{c.title}</b> · {STATUS[mine?.status] || mine?.status}
            <p>{c.instructions}</p>
            <small className="muted">مهلت پذیرش تا {timeFa(c.expires_at)}</small>
            <div className="gis-actions">
              {(ACTIONS[mine?.status] || []).map(([a, label]) => <button key={a} className="secondary" onClick={() => run(c, a)}>{label}</button>)}
            </div>
          </article>
        );
      })}
    </section>
  );
}
