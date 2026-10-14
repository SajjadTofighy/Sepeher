import { api, fa, labels } from "../../api";
import type { Data, Incident, IncidentReport } from "../../types";

import {
  escapePrintText as esc,
  openPrintWindow,
  writePrintReport,
} from "../../shared/lib/print";
import { tehranTime as when } from "../../shared/lib/time";

function since(i: Incident, label: string) {
  const hit = i.timeline.find((e) => e.action.startsWith(label));
  if (!hit) return "—";
  const s = Math.round(
    (Date.parse(hit.time) - Date.parse(i.created_at)) / 1000,
  );
  return `${fa(Math.floor(s / 60))} دقیقه و ${fa(s % 60)} ثانیه`;
}

// Design §8: automatic incident report with timeline, actions, units and response times.
export async function printIncidentReport(i: Incident, data: Data) {
  const w = openPrintWindow();
  let report: IncidentReport;
  try {
    report = await api<IncidentReport>(`/incidents/${i.id}/report`);
  } catch (error) {
    w.close();
    throw error;
  }
  i = report.incident;
  const name = (id?: string | null) =>
    data.assets.find((a) => a.id === id)?.name || id || "—";
  const policy = data.policies.find((p) => p.id === i.policy_id);
  const rows = i.timeline
    .map(
      (e) =>
        `<tr><td>${esc(when(e.time))}</td><td>${esc(e.actor)}</td><td>${esc(e.action)}</td></tr>`,
    )
    .join("");
  const area = i.hazard_area;
  const hazard = area
    ? `<h2>محدوده خطر</h2>
<p>${area.type === "circle" ? `دایره · مرکز ${esc(area.center.join("، "))} · شعاع ${fa(area.radius_m)} متر` : `چندضلعی · نقاط ${esc(area.points.map((p) => p.join("، ")).join(" / "))}`}</p>
${area.access_points?.length ? `<p>نقاط دسترسی: ${esc(area.access_points.map((p) => p.join("، ")).join(" / "))}</p>` : ""}
<h3>داخل محدوده</h3><p>${esc(report.hazard.inside.map((a) => a.name).join("، ") || "تجهیزی داخل محدوده نیست.")}</p>
<h3>در حال نزدیک‌شدن</h3><p>${esc(report.hazard.approaching.map((a) => `${a.name} · ${fa(a.distance_to_boundary_km)} کیلومتر تا مرز · ${a.finding_id || "—"}`).join("، ") || "تجهیزی در حال نزدیک‌شدن نیست.")}</p>`
    : "";
  const body = `
<p>${esc(i.description)}</p>
<p class="muted">محدوده: ${esc(i.zone)} · موضوع: ${esc(name(i.asset_id))} · گشت اعزامی: ${esc(name(i.assigned_to))}${
    policy
      ? ` · سیاست: ${esc(policy.id)} «${esc(policy.name)}» نسخه ${fa(policy.version)}`
      : ""
  }</p>
<div class="grid">
<div><small>تا تأیید</small><b>${since(i, "تأیید حادثه")}</b></div>
<div><small>تا اعزام</small><b>${since(i, "ارجاع به گشت")}</b></div>
<div><small>تا حضور در محل</small><b>${since(i, "حضور در محل")}</b></div>
<div><small>تا خاتمه</small><b>${since(i, "خاتمه حادثه")}</b></div>
</div>
${hazard}
<table><thead><tr><th>زمان</th><th>اقدام‌کننده</th><th>اقدام</th></tr></thead><tbody>${rows}</tbody></table>`;
  return writePrintReport(w, {
    title: `گزارش حادثه ${i.id}`,
    header: `<small>سپهر حراست · گزارش خودکار حادثه</small><h1>${esc(i.title)}</h1>
<span class="tag">${esc(i.id)}</span><span class="tag">${esc(labels[i.severity])}</span><span class="tag">${esc(labels[i.status])}</span>`,
    generatedAt: report.generated_at,
    body,
    footer:
      "زمان‌ها از لحظه ثبت هشدار در سامانه محاسبه شده‌اند. داده‌ها نمایشی و ساختگی‌اند.",
  });
}
