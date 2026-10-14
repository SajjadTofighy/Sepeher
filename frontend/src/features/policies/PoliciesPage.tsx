import { Activity, BellRing, ChevronLeft, CircleDot, FilePlus2, FlaskConical, Play, Radar, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { api, executableConditions, fa, labels, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge } from "../../shared/ui/primitives";
import type { Data, PolicyTestResult } from "../../types";

const lifecycle = ["draft", "tested", "shadow", "active"];

export default function PoliciesPage({ data, busy, act, setToast, onNew }: {
  data: Data; busy: boolean; act: Act; setToast: (s: string) => void; onNew: () => void;
}) {
  const active = data.policies.filter((policy) => policy.status === "active").length;
  const shadow = data.policies.filter((policy) => policy.status === "shadow").length;

  return <section className="policies-workspace">
    <header className="policies-hero">
      <div className="policies-hero-copy">
        <span className="policies-kicker"><ShieldCheck size={15} /> POLICY CONTROL CENTER</span>
        <h2>فرماندهی سیاست‌های حراست</h2>
        <p>تعریف، ارزیابی و انتشار کنترل‌شده قواعد حفاظتی با نظارت کامل اپراتور</p>
        <div className="policies-engine-state"><span><i className="live-dot" /> موتور سیاست فعال</span><small>{fa(active)} سیاست در حال پایش عملیاتی</small></div>
      </div>
      <div className="policies-hero-visual" aria-hidden="true"><span className="policy-radar-ring ring-one" /><span className="policy-radar-ring ring-two" /><Radar size={38} /></div>
      <button className="primary policy-new-action" onClick={onNew}><FilePlus2 size={18} /> تعریف سیاست جدید</button>
    </header>

    <div className="policy-kpis">
      <article className="policy-kpi cyan"><span><SlidersHorizontal size={18} /></span><div><small>کل سیاست‌ها</small><strong>{fa(data.policies.length)}</strong><em>قواعد ثبت‌شده</em></div></article>
      <article className="policy-kpi green"><span><ShieldCheck size={18} /></span><div><small>سیاست فعال</small><strong>{fa(active)}</strong><em>در مسیر عملیاتی</em></div></article>
      <article className="policy-kpi violet"><span><FlaskConical size={18} /></span><div><small>حالت سایه</small><strong>{fa(shadow)}</strong><em>تحت ارزیابی</em></div></article>
      <article className="policy-kpi amber"><span><BellRing size={18} /></span><div><small>هشدار موتور</small><strong>{fa(data.summary.policy_alerts)}</strong><em>{fa(data.summary.shadow_alerts)} هشدار سایه</em></div></article>
    </div>

    <section className="policy-lifecycle">
      <div className="policy-lifecycle-title"><span><Activity size={18} /></span><div><b>خط انتشار امن</b><small>هر سیاست پیش از اجرا از چهار دروازه کنترلی عبور می‌کند</small></div></div>
      <div className="policy-lifecycle-track">{lifecycle.map((status, index) => <div className={`lifecycle-step step-${status}`} key={status}>
        <span>{fa(index + 1)}</span><div><b>{labels[status]}</b><small>{index === 0 ? "تعریف قاعده" : index === 1 ? "آزمون تاریخچه" : index === 2 ? "پایش بدون اقدام" : "اجرای تأییدشده"}</small></div>{index < lifecycle.length - 1 && <ChevronLeft size={16} />}
      </div>)}</div>
    </section>

    <div className="policy-section-heading"><div><span><CircleDot size={16} /></span><div><h3>دفتر سیاست‌های حفاظتی</h3><p>وضعیت، منطق تصمیم و کارایی هر سیاست در یک نمای یکپارچه</p></div></div><span className="policy-registry-count">{fa(data.policies.length)} سیاست ثبت‌شده</span></div>

    <div className="policy-grid policy-registry">{data.policies.map((p) => <article className={`panel policy policy-card status-${p.status}`} key={p.id}>
      <div className="policy-card-accent" />
      <div className="policy-head"><div className="policy-identity"><span className="policy-status-orb" /><span><small>شناسه سیاست</small><b>{p.id}</b></span></div><Badge value={p.status} /></div>
      <div className="policy-card-title"><div><h2>{p.name}</h2><p>{data.zones.find((z) => z.id === p.zone)?.name} · {p.schedule}</p></div><span className="policy-version">V {fa(p.version)}</span></div>
      <div className="rule-sentence"><small>منطق تصمیم</small><div><span>اگر</span> {labels[p.condition]} <span>آنگاه</span> {labels[p.action]} با اهمیت <b>{labels[p.severity]}</b></div></div>
      <div className="policy-metrics"><span><small>انطباق ثبت‌شده</small><b>{fa(p.matches)}</b></span><span><small>هشدار کاذب</small><b>{fa(p.false_positives)}</b></span><span><small>آستانه اجرا</small><b>{p.condition === "camera_event" ? fa(2) : p.condition === "unknown_vehicle" ? fa(1) : fa(p.threshold)}</b></span></div>
      {!executableConditions.includes(p.condition) && <p className="policy-notice warning">این شرط هنوز موتور اجرایی ندارد و فقط به‌صورت پیش‌نویس نگهداری می‌شود.</p>}
      {(p.condition === "unknown_vehicle" || p.condition === "camera_event") && <p className="policy-notice info">نیازمند ورودی واقعی و فعال‌سازی ANPR؛ آزمون گذشته روی خوانش‌های ثبت‌شده اجرا می‌شود.</p>}
      <div className="policy-actions">
        <button className="secondary" disabled={busy || !executableConditions.includes(p.condition)} onClick={async () => { const result = await act(() => api<PolicyTestResult>(`/policies/${p.id}/test`, "POST"), "آزمون تاریخچه انجام شد"); if (result) setToast(`${result.period}: ${fa(result.matches)} انطباق از ${fa(result.samples)} رکورد؛ نرخ هشدار کاذب هنوز ارزیابی نشده است`); }}><Play size={14} /> آزمون گذشته</button>
        {p.status === "tested" && <button className="primary" disabled={busy} onClick={() => act(() => api(`/policies/${p.id}/status`, "PATCH", { status: "shadow" }), "سیاست وارد حالت سایه شد")}>ورود به سایه</button>}
        {p.status === "shadow" && <button className="primary" disabled={busy} onClick={() => act(() => api(`/policies/${p.id}/status`, "PATCH", { status: "active" }), "سیاست با تأیید نمایشی فعال شد")}>تأیید و فعال‌سازی</button>}
        {p.status === "active" && <button className="text-button" disabled={busy} onClick={() => act(() => api(`/policies/${p.id}/status`, "PATCH", { status: "shadow" }), "سیاست وارد حالت سایه شد")}>انتقال به سایه</button>}
      </div>
    </article>)}</div>

    <section className="panel engine-log policy-engine-log">
      <div className="policy-log-head"><div className="policy-log-title"><span><Radar size={20} /></span><div><h2>جریان هشدار موتور سیاست</h2><p>رویدادهای فعال پرونده می‌سازند؛ رویدادهای سایه برای ارزیابی نگهداری می‌شوند.</p></div></div><div className="policy-log-summary"><span><b>{fa(data.summary.policy_alerts)}</b> کل هشدار</span><span><b>{fa(data.summary.shadow_alerts)}</b> سایه</span></div></div>
      {data.alerts.length ? <ul>{data.alerts.slice(0, 8).map((alert) => <li key={alert.id} className={alert.routed ? "routed" : "held"}><span className="policy-log-time"><i />{timeFa(alert.time)}</span><b>{alert.policy}</b><span>{alert.zone}</span><span className="engine-route">{alert.routed ? `پرونده ${alert.incident_id}` : `نگه‌داشته · ${alert.reason}`}</span></li>)}</ul> : <div className="empty policy-log-empty"><Radar size={30} /><span>هنوز هشداری ثبت نشده است</span><small>«نمایش ۵ دقیقه‌ای» یک ورود بدون مجوز را شبیه‌سازی می‌کند.</small></div>}
    </section>
  </section>;
}
