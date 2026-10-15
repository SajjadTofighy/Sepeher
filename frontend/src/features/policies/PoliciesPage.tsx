import { Play } from "lucide-react";
import { api, executableConditions, fa, labels, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge, PanelTitle, StatStrip } from "../../shared/ui/primitives";
import type { Data, PolicyTestResult } from "../../types";


export default function PoliciesPage({ data, busy, act, setToast, onNew }: {
  data: Data; busy: boolean; act: Act; setToast: (s: string) => void; onNew: () => void;
}) {
  const active = data.policies.filter((policy) => policy.status === "active").length;
  const shadow = data.policies.filter((policy) => policy.status === "shadow").length;

  return <section className="policies-workspace">
    <StatStrip items={[
      { label: "کل سیاست‌ها", value: fa(data.policies.length) },
      { label: "فعال", value: fa(active), tone: "ok" },
      { label: "حالت سایه", value: fa(shadow) },
      { label: "هشدار موتور", value: fa(data.summary.policy_alerts), note: `${fa(data.summary.shadow_alerts)} هشدار سایه` },
    ]} />

    <section className="panel policy-list">{data.policies.map((p) => <article className={`policy-row status-${p.status}`} key={p.id}>
      <div className="policy-main">
        <div className="policy-name"><b>{p.name}</b><Badge value={p.status} /></div>
        <small dir="auto">{p.id} · نسخه {fa(p.version)} · {data.zones.find((z) => z.id === p.zone)?.name} · {p.schedule}</small>
        <p className="rule-sentence">اگر {labels[p.condition]}، آنگاه {labels[p.action]} با اهمیت <b>{labels[p.severity]}</b></p>
        {!executableConditions.includes(p.condition) && <small className="policy-notice warning">این شرط هنوز موتور اجرایی ندارد و فقط به‌صورت پیش‌نویس نگهداری می‌شود.</small>}
        {(p.condition === "unknown_vehicle" || p.condition === "camera_event") && <small className="policy-notice">نیازمند ورودی واقعی و فعال‌سازی ANPR؛ آزمون گذشته روی خوانش‌های ثبت‌شده اجرا می‌شود.</small>}
      </div>
      <dl className="policy-figures">
        <div><dt>انطباق</dt><dd>{fa(p.matches)}</dd></div>
        <div><dt>هشدار کاذب</dt><dd>{fa(p.false_positives)}</dd></div>
        <div><dt>آستانه</dt><dd>{p.condition === "camera_event" ? fa(2) : p.condition === "unknown_vehicle" ? fa(1) : fa(p.threshold)}</dd></div>
      </dl>
      <div className="policy-actions">
        <button className="secondary" disabled={busy || !executableConditions.includes(p.condition)} onClick={async () => { const result = await act(() => api<PolicyTestResult>(`/policies/${p.id}/test`, "POST"), "آزمون تاریخچه انجام شد"); if (result) setToast(`${result.period}: ${fa(result.matches)} انطباق از ${fa(result.samples)} رکورد؛ نرخ هشدار کاذب هنوز ارزیابی نشده است`); }}><Play size={14} /> آزمون گذشته</button>
        {p.status === "tested" && <button className="primary" disabled={busy} onClick={() => act(() => api(`/policies/${p.id}/status`, "PATCH", { status: "shadow" }), "سیاست وارد حالت سایه شد")}>ورود به سایه</button>}
        {p.status === "shadow" && <button className="primary" disabled={busy} onClick={() => act(() => api(`/policies/${p.id}/status`, "PATCH", { status: "active" }), "سیاست با تأیید نمایشی فعال شد")}>تأیید و فعال‌سازی</button>}
        {p.status === "active" && <button className="text-button" disabled={busy} onClick={() => act(() => api(`/policies/${p.id}/status`, "PATCH", { status: "shadow" }), "سیاست وارد حالت سایه شد")}>انتقال به سایه</button>}
      </div>
    </article>)}</section>

    <section className="panel engine-log policy-engine-log">
      <PanelTitle title="جریان هشدار موتور سیاست" sub="رویدادهای فعال پرونده می‌سازند؛ رویدادهای سایه برای ارزیابی نگهداری می‌شوند." />
      {data.alerts.length ? <ul>{data.alerts.slice(0, 8).map((alert) => <li key={alert.id} className={alert.routed ? "routed" : "held"}><span className="policy-log-time"><i />{timeFa(alert.time)}</span><b>{alert.policy}</b><span>{alert.zone}</span><span className="engine-route">{alert.routed ? `پرونده ${alert.incident_id}` : `نگه‌داشته · ${alert.reason}`}</span></li>)}</ul> : <div className="empty policy-log-empty"><span>هنوز هشداری ثبت نشده است</span><small>«نمایش ۵ دقیقه‌ای» یک ورود بدون مجوز را شبیه‌سازی می‌کند.</small></div>}
    </section>
  </section>;
}
