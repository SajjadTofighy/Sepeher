import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, ClipboardCheck, Download, FilePen, FileSpreadsheet, Gauge, MapPinCheck, Printer, ShieldAlert, UserSearch } from "lucide-react";
import { useState } from "react";
import { api, fa, labels, parseResponse, sessionHeaders, timeFa } from "../../api";
import { escapePrintText, openPrintWindow, writePrintReport } from "../../shared/lib/print";
import { tehranInputISO, tehranLocalInput, tehranTime } from "../../shared/lib/time";
import { Badge } from "../../shared/ui/primitives";
import type { ExceptionBoard, GuardDetailReport, GuardRecord, PaperScanInput, PatrolReport, PilotMetrics, ScanRecord, ScheduledTour } from "../../types";

type Tab = "exceptions" | "stations" | "report" | "guard" | "paper" | "pilot";
const KINDS = ["station_missed", "station_overdue", "scan_low_trust", "scan_pending_review", "alarm_unacked", "duress_unacked",
  "man_down_unacked", "device_silent", "muster_open", "message_urgent_unacked", "integrity"] as const;
const persianDate = (value: string) => new Date(value).toLocaleString("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran", dateStyle: "short", timeStyle: "short" });

export default function SupervisionPage() {
  const [tab, setTab] = useState<Tab>("exceptions");
  const board = useQuery({ queryKey: ["supervision", "board"], queryFn: () => api<ExceptionBoard>("/tour/exceptions"), refetchInterval: 5000 });
  const critical = board.data?.items.filter((i) => i.severity === "critical").length || 0;
  return (
    <section className="supervision">
      <div className="comms-tabs" role="tablist">
        {([["exceptions", "تابلوی استثنا", AlertOctagon, board.data?.items.length || 0], ["stations", "وضعیت ایستگاه‌ها", MapPinCheck, 0],
          ["report", "گزارش گشت", ClipboardCheck, 0], ["guard", "نمای فردی", UserSearch, 0],
          ["paper", "ورود فرم کاغذی", FilePen, 0], ["pilot", "شاخص‌های پایلوت", Gauge, 0]] as const).map(([id, name, Icon, count]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "current" : ""} onClick={() => setTab(id)}>
            <Icon size={16} />{name}{count > 0 && <em className={critical ? "critical" : ""}>{fa(count)}</em>}
          </button>
        ))}
      </div>
      {board.isError && <div className="error-banner">{(board.error as Error).message}</div>}
      {tab === "exceptions" && <Exceptions board={board.data} loading={board.isPending} />}
      {tab === "stations" && <Stations board={board.data} />}
      {tab === "report" && <Report />}
      {tab === "guard" && <GuardView />}
      {tab === "paper" && <PaperEntry />}
      {tab === "pilot" && <Pilot />}
    </section>
  );
}

function Exceptions({ board, loading }: { board?: ExceptionBoard; loading: boolean }) {
  const [kind, setKind] = useState("");
  if (loading || !board) return <div className="panel empty">در حال دریافت تابلوی استثنا…</div>;
  const items = board.items.filter((i) => !kind || i.kind === kind);
  return (
    <div className="supervision-grid">
      <div className="panel exception-list">
        <div className="exception-kpis">
          <button className={!kind ? "current" : ""} onClick={() => setKind("")}><b>{fa(board.items.length)}</b><small>همه موارد</small></button>
          {KINDS.filter((k) => board.counts[k]).map((k) => (
            <button key={k} className={kind === k ? "current" : ""} onClick={() => setKind(k)}><b>{fa(board.counts[k])}</b><small>{labels[k]}</small></button>
          ))}
        </div>
        {!items.length ? (
          <div className="empty"><ClipboardCheck size={26} /><p>موردی نیازمند اقدام نیست</p><small>به‌روزرسانی {board.generated_at_jalali}</small></div>
        ) : (
          <ul>{items.map((i) => (
            <li key={i.id} className={`exception-row ${i.severity}`}>
              <Badge value={i.severity} />
              <div><b>{i.title}</b><p>{i.detail}</p>
                <small>{labels[i.kind]} · {i.zone_id} · {i.guard_id || "—"} · {i.station_id || "—"} · از {timeFa(i.since)}</small></div>
              <code dir="ltr">{i.source_ids[0].slice(0, 18)}</code>
            </li>
          ))}</ul>
        )}
      </div>
      <aside className="panel suspended-list">
        <h3><ShieldAlert size={16} />وضعیت اضطرار و مهلت‌های تعلیق‌شده</h3>
        <p className="muted">این موارد جزو ازدست‌رفته شمرده نمی‌شوند.</p>
        {board.emergency_zone_ids.length ? <p className="flag">اضطرار فعال: {board.emergency_zone_ids.join("، ")}</p> : <p>اضطرار فعالی نیست.</p>}
        <ul>{board.suspended.map((s) => (
          <li key={s.scheduled_tour_id}><b>{s.zone_id} · {s.guard_id}</b><small>{timeFa(s.due_at)} تا {timeFa(s.ends_at)} · {fa(s.station_count)} ایستگاه · {s.reason}</small></li>
        ))}</ul>
      </aside>
    </div>
  );
}

function Stations({ board }: { board?: ExceptionBoard }) {
  if (!board) return <div className="panel empty">در حال دریافت…</div>;
  return (
    <div className="panel comms-list">
      <p className="muted">«تأییدشده» فقط وقتی اعتماد آخرین اسکن پذیرفته‌شده دست‌کم متوسط باشد؛ در غیر این صورت «تأییدنشده».</p>
      <div className="table-wrap"><table>
        <thead><tr><th>ایستگاه</th><th>محوطه</th><th>نوع تگ</th><th>وضعیت</th><th>اعتماد آخرین اسکن</th><th>زمان</th></tr></thead>
        <tbody>{board.stations.map((s) => (
          <tr key={s.station_id}>
            <td>{s.name}<small>{s.station_id}</small></td><td>{s.zone_id}</td>
            <td>{s.tag_mode}{s.tag_mode === "nfc_counter" && <small className="flag">تگ ضعیف</small>}</td>
            <td><Badge value={s.status === "ok" ? "online" : s.status === "unverified" ? "warning" : "offline"} /> {labels[s.status]}</td>
            <td>{s.last_trust ? labels[s.last_trust] : "—"}</td>
            <td>{s.last_scan_at ? persianDate(s.last_scan_at) : "—"}</td>
          </tr>
        ))}</tbody>
      </table></div>
    </div>
  );
}

function usePeriod() {
  const [from, setFrom] = useState(() => tehranLocalInput(new Date(Date.now() - 86400000)));
  const [to, setTo] = useState(() => tehranLocalInput(new Date()));
  const query = `window_from=${encodeURIComponent(tehranInputISO(from))}&window_to=${encodeURIComponent(tehranInputISO(to))}`;
  const inputs = (
    <div className="comms-filters">
      <label className="field">از (وقت تهران)<input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
      <label className="field">تا<input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} /></label>
    </div>
  );
  return { query, inputs };
}

function Totals({ t }: { t: PatrolReport["totals"] }) {
  return (
    <div className="report-totals">
      {([["planned", "برنامه‌ریزی‌شده"], ["visited", "انجام‌شده"], ["verified", "تأییدشده"], ["missed", "ازدست‌رفته"], ["pending", "باز"], ["suspended", "تعلیق اضطرار"]] as const).map(([k, l]) => (
        <div key={k}><b>{fa(t[k])}</b><small>{l}</small></div>
      ))}
      <div><b>{t.verified_percent === null ? "—" : fa(t.verified_percent) + "٪"}</b><small>درصد تأیید</small></div>
    </div>
  );
}

function Report() {
  const { query, inputs } = usePeriod();
  const [report, setReport] = useState<PatrolReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const csv = () => run(async () => {
    const response = await fetch(`/api/v1/reports/tour/summary?format=csv&${query}`, { headers: sessionHeaders(), cache: "no-store" });
    if (!response.ok) await parseResponse(response);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await response.blob());
    a.download = "sepehr-patrol-report.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  const print = (r: PatrolReport) => {
    const w = openPrintWindow();
    const row = (cells: (string | number | null)[]) => `<tr>${cells.map((c) => `<td>${escapePrintText(String(c ?? "—"))}</td>`).join("")}</tr>`;
    writePrintReport(w, {
      title: "گزارش گشت نگهبانی",
      header: `<div class="classification">${escapePrintText(r.classification_label)}</div><h1>گزارش گشت نگهبانی</h1><small>${escapePrintText(r.period.from_jalali)} تا ${escapePrintText(r.period.to_jalali)} · شناسه ممیزی ${escapePrintText(r.audit_id)}</small>`,
      generatedAt: r.generated_at,
      watermark: `${r.viewer} · ${r.generated_at_jalali}`,
      body: `<div class="grid">${Object.entries(r.totals).map(([k, v]) => `<div><small>${escapePrintText(labels[k] || k)}</small><b>${escapePrintText(String(v ?? "—"))}</b></div>`).join("")}</div>
<h3>پایبندی پیمانکار و پست (بدون رتبه‌بندی فردی)</h3><table><tr><th>پیمانکار</th><th>پست</th><th>برنامه</th><th>انجام</th><th>تأیید</th><th>درصد</th><th>ازدست‌رفته</th><th>تعلیق</th></tr>
${r.contractors.map((c) => row([c.contractor_id, c.zone_id, c.planned, c.visited, c.verified, c.verified_percent, c.missed, c.suspended])).join("")}</table>
<h3>اعتماد اسکن</h3><table>${Object.entries(r.trust).map(([k, v]) => row([k, v])).join("")}</table>
<h3>یکپارچگی و استثناها</h3><table>${Object.entries({ ...r.integrity, ...r.exceptions }).map(([k, v]) => row([labels[k] || k, v])).join("")}</table>
<h3>وضعیت اضطرار (جدا از ازدست‌رفته)</h3><table>${r.emergency.map((e) => row([e.zone_id, e.active ? "فعال" : "پایان", e.reason])).join("") || row(["—"])}</table>
<h3>سلامت زنجیره ممیزی</h3><p>${r.audit_chain.valid ? "سالم" : "ناسازگار — بررسی فوری لازم است"} · ${r.audit_chain.count} رکورد · ${escapePrintText(r.audit_chain.scope)}</p>`,
      footer: `${r.classification_label} · بیننده ${r.viewer} · ${r.generated_at_jalali}`,
    });
  };
  return (
    <div className="panel comms-list">
      {inputs}
      <div className="report-actions">
        <button className="primary" disabled={busy} onClick={() => run(async () => setReport(await api<PatrolReport>(`/reports/tour/summary?${query}`)))}><ClipboardCheck size={16} />ساخت گزارش</button>
        <button className="secondary" disabled={busy} onClick={csv}><FileSpreadsheet size={16} />خروجی CSV</button>
        {report && <button className="secondary" onClick={() => { try { print(report); } catch (e) { setError((e as Error).message); } }}><Printer size={16} />چاپ نشان‌دار</button>}
        {report && <button className="secondary" onClick={() => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" })); a.download = "sepehr-patrol-report.json"; a.click(); }}><Download size={16} />JSON</button>}
      </div>
      <p className="muted">هر ساخت گزارش و خروجی با شناسه ممیزی ثبت می‌شود.</p>
      {error && <div className="error-banner">{error}</div>}
      {report && (
        <div className="patrol-report">
          <div className="classification-banner">{report.classification_label}</div>
          <p>بازه {report.period.from_jalali} تا {report.period.to_jalali} · ممیزی {report.audit_id}</p>
          <Totals t={report.totals} />
          <h3>پیمانکار و پست</h3>
          <div className="table-wrap"><table>
            <thead><tr><th>پیمانکار</th><th>پست</th><th>برنامه</th><th>انجام</th><th>تأیید</th><th>درصد</th><th>ازدست‌رفته</th><th>تعلیق</th></tr></thead>
            <tbody>{report.contractors.map((c) => <tr key={c.contractor_id + c.zone_id}><td>{c.contractor_id}</td><td>{c.zone_id}</td><td>{fa(c.planned)}</td><td>{fa(c.visited)}</td><td>{fa(c.verified)}</td><td>{c.verified_percent === null ? "—" : fa(c.verified_percent) + "٪"}</td><td>{fa(c.missed)}</td><td>{fa(c.suspended)}</td></tr>)}</tbody>
          </table></div>
          <h3>اعتماد اسکن</h3>
          <div className="report-totals">{([["high", "زیاد"], ["medium", "متوسط"], ["low", "کم"], ["manual", "دستی"], ["pending_review", "در انتظار بازبینی"], ["weak_tag", "تگ ضعیف"], ["rejected_replay", "تکرار رد‌شده"]] as const).map(([k, l]) => <div key={k}><b>{fa(report.trust[k])}</b><small>{l}</small></div>)}</div>
          <h3>سلامت زنجیره ممیزی</h3>
          <p className={report.audit_chain.valid ? "ack-done" : "flag"}>{report.audit_chain.valid ? "سالم" : "ناسازگار"} · {fa(report.audit_chain.count)} رکورد</p>
          <div className="classification-banner">{report.classification_label}</div>
        </div>
      )}
    </div>
  );
}

function GuardView() {
  const { query, inputs } = usePeriod();
  const guards = useQuery({ queryKey: ["supervision", "guards"], queryFn: () => api<GuardRecord[]>("/guards") });
  const [guardId, setGuardId] = useState("");
  const [detail, setDetail] = useState<GuardDetailReport | null>(null);
  const [error, setError] = useState("");
  return (
    <div className="panel comms-list">
      <p className="muted">فقط سرپرست شیفت همان محوطه و ممیز؛ هر مشاهده در ممیزی ثبت می‌شود. این نما رتبه‌بندی نیست.</p>
      {inputs}
      <div className="comms-filters">
        <label className="field">نگهبان<select value={guardId} onChange={(e) => setGuardId(e.target.value)}>
          <option value="">انتخاب کنید</option>
          {(guards.data || []).map((g) => <option key={g.id} value={g.id}>{g.name} · {g.zone_id || "—"}</option>)}
        </select></label>
        <button className="primary" disabled={!guardId} onClick={async () => {
          setError(""); setDetail(null);
          try { setDetail(await api<GuardDetailReport>(`/reports/tour/guards/${guardId}?${query}`)); } catch (e) { setError((e as Error).message); }
        }}>نمایش</button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {detail && (
        <div className="patrol-report">
          <div className="classification-banner">{detail.classification_label} · بیننده {detail.viewer} · ممیزی {detail.audit_id}</div>
          <Totals t={detail.totals} />
          <div className="table-wrap"><table>
            <thead><tr><th>موعد</th><th>ایستگاه</th><th>نتیجه</th><th>اعتماد</th></tr></thead>
            <tbody>{detail.checks.map((c) => <tr key={c.scheduled_tour_id + c.station_id}><td>{tehranTime(c.due_at)}</td><td>{c.station_id}</td><td>{labels[c.outcome]}</td><td>{c.trust_level ? labels[c.trust_level] : "—"}</td></tr>)}</tbody>
          </table></div>
          <h3>اسکن‌ها و شواهد</h3>
          <div className="table-wrap"><table>
            <thead><tr><th>زمان</th><th>ایستگاه</th><th>شواهد</th><th>اعتماد</th><th>وضعیت</th></tr></thead>
            <tbody>{detail.scans.map((s) => <tr key={s.id}><td>{tehranTime(s.received_at)}</td><td>{s.station_id}</td><td dir="ltr">{Object.values(s.evidence).join(" · ")}</td><td>{labels[s.trust_level]}</td><td>{s.status}</td></tr>)}</tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}

function PaperEntry() {
  const queue = useQuery({ queryKey: ["supervision", "queue"], queryFn: () => api<ScheduledTour[]>("/tour/queue") });
  const [form, setForm] = useState({ scheduled_tour_id: "", station_id: "", recorded_at: tehranLocalInput(new Date()), form_serial: "", notes: "" });
  const [result, setResult] = useState<ScanRecord | null>(null);
  const [error, setError] = useState("");
  const scheduled = (queue.data || []).find((q) => q.id === form.scheduled_tour_id);
  const submit = async () => {
    setError(""); setResult(null);
    const body: PaperScanInput = { ...form, recorded_at: tehranInputISO(form.recorded_at) };
    try { setResult(await api<ScanRecord>("/tour/paper-scans", "POST", body)); } catch (e) { setError((e as Error).message); }
  };
  return (
    <form className="panel comms-list" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <p className="muted">ردیف‌های فرم کاغذی پشتیبان (زمان قطع سامانه یا شبکه) با روش «کاغذی» و اعتماد کم ثبت می‌شوند؛ ایستگاه «تأییدنشده» می‌ماند ولی ازدست‌رفته شمرده نمی‌شود. هر ورود ممیزی می‌شود.</p>
      <div className="comms-filters">
        <label className="field">دور برنامه‌ریزی‌شده<select required value={form.scheduled_tour_id} onChange={(e) => setForm({ ...form, scheduled_tour_id: e.target.value, station_id: "" })}>
          <option value="">انتخاب کنید</option>
          {(queue.data || []).map((q) => <option key={q.id} value={q.id}>{q.guard_id} · {tehranTime(q.due_at)} · {labels[q.status] || q.status}</option>)}
        </select></label>
        <label className="field">ایستگاه<select required value={form.station_id} onChange={(e) => setForm({ ...form, station_id: e.target.value })}>
          <option value="">انتخاب کنید</option>
          {(scheduled?.station_ids || []).map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label>
        <label className="field">زمان روی فرم (تهران)<input type="datetime-local" required value={form.recorded_at} onChange={(e) => setForm({ ...form, recorded_at: e.target.value })} /></label>
        <label className="field">شماره سریال فرم<input dir="ltr" required pattern="[0-9A-Za-z_\-]+" value={form.form_serial} onChange={(e) => setForm({ ...form, form_serial: e.target.value })} /></label>
      </div>
      <label className="field">توضیح<input maxLength={1000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></label>
      <button className="primary" disabled={!form.station_id || !form.form_serial}><FilePen size={16} />ثبت ردیف فرم</button>
      {error && <div className="error-banner">{error}</div>}
      {result && <p className="ack-done">ثبت شد: {result.id} · روش {result.method} · اعتماد {labels[result.trust_level]}</p>}
    </form>
  );
}

function Pilot() {
  const { query, inputs } = usePeriod();
  const [data, setData] = useState<PilotMetrics | null>(null);
  const [error, setError] = useState("");
  return (
    <div className="panel comms-list">
      <p className="muted">شاخص‌های قابل محاسبه از رکوردهای پایدار، هر کدام با روش سنجش. موارد دستی جدا فهرست شده‌اند. هر دریافت ممیزی می‌شود.</p>
      {inputs}
      <div className="report-actions">
        <button className="primary" onClick={async () => { setError(""); try { setData(await api<PilotMetrics>(`/reports/pilot?${query}`)); } catch (e) { setError((e as Error).message); } }}><Gauge size={16} />محاسبه شاخص‌ها</button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      {data && (
        <div className="patrol-report">
          <div className="classification-banner">{data.classification_label} · ممیزی {data.audit_id}</div>
          <div className="table-wrap"><table>
            <thead><tr><th>شاخص</th><th>مقدار</th><th>نمونه</th><th>روش سنجش</th></tr></thead>
            <tbody>{data.metrics.map((m) => (
              <tr key={m.key}><td>{m.label}</td><td dir="ltr">{m.value === null ? "—" : `${fa(m.value)} ${m.unit === "count" ? "" : m.unit}`}</td><td>{fa(m.samples)}</td><td className="muted">{m.method}</td></tr>
            ))}</tbody>
          </table></div>
          <h3>سنجش دستی در پایلوت</h3>
          <ul>{data.manual_measurements.map((m) => <li key={m}>{m}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

