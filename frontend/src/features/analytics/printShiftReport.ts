import type { ShiftReport } from "../../types";
import {
  escapePrintText as esc,
  openPrintWindow,
  writePrintReport,
} from "../../shared/lib/print";
import { tehranTime } from "../../shared/lib/time";

export function printShiftReport(report: ShiftReport) {
  const range = `${tehranTime(report.window_from)} تا ${tehranTime(report.window_to)}`;
  const body = `<p>${esc(range)}</p><p class="muted">داده‌های موجود از: ${esc(tehranTime(report.data_since))} · منبع آغاز دوره: ${esc(report.data_source_id)}</p>
${Object.values(report.sections)
  .map(
    (
      section,
    ) => `<section><h2>${esc(section.title)}${section.partial ? " · گزارش جزئی" : ""}</h2>
${section.notes.map((note) => `<p class="muted">${esc(note)}</p>`).join("")}
<ul>${section.lines.map((line) => `<li>${esc(line.text)} <small>منابع: ${esc(line.source_ids.join("، "))}</small></li>`).join("")}</ul></section>`,
  )
  .join("")}`;
  return writePrintReport(openPrintWindow(), {
    title: "گزارش شیفت",
    header: `<small>سپهر حراست · گزارش خودکار شیفت</small><h1>گزارش شیفت${report.partial ? " · جزئی" : ""}</h1>`,
    generatedAt: report.generated_at,
    body,
    footer:
      "بازه شمارش شامل آغاز و بدون لحظه پایان است. داده‌های این محیط نمایشی و ساختگی‌اند؛ تاریخچه ناموجود تکمیل نمی‌شود.",
  });
}
