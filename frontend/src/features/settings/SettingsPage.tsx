import { ExternalLink, FileText, RotateCcw } from "lucide-react";
import { useSession } from "../../shared/auth/session";

export default function SettingsPage({ connected, setResetConfirm }: { connected: boolean; setResetConfirm: (s: boolean) => void }) {
  const demo = useSession().config?.mode === "demo";
  const services = [
    { name: "سرویس API", detail: "FastAPI", state: connected ? "متصل" : "قطع", tone: connected ? "online" : "offline" },
    { name: "نقشه سازمانی", detail: "WMS / WFS و نقشه پایه داخلی؛ تنظیم در بخش اتصال GIS", state: "قابل تنظیم", tone: "config" },
    { name: "ردیاب و پیامک", detail: "چرخه فرمان شبیه‌سازی‌شده", state: "نمایشی", tone: "demo" },
    { name: "دوربین و IVA", detail: "اتصال در فاز سوم", state: "نمایشی", tone: "demo" },
    { name: "دستیار قاعده‌محور", detail: "پاسخ قالبی از رکوردهای سامانه؛ بدون مدل زبانی", state: "نمایشی", tone: "demo" },
  ];
  return (
    <section className="panel settings-overview">
      <div className="panel-title">
        <div><h2>اتصال‌ها</h2>{demo && <p>محیط نمایشی: رکوردها و هویت‌ها ساختگی‌اند و فرمانی به تجهیزات واقعی ارسال نمی‌شود.</p>}</div>
        <div className="heading-actions">
          <a className="secondary" href="/docs" target="_blank" rel="noreferrer"><FileText size={16}/> مستندات API <ExternalLink size={13}/></a>
          {demo && <button className="danger-button" onClick={() => setResetConfirm(true)}><RotateCcw size={15}/> بازنشانی داده‌های نمایشی</button>}
        </div>
      </div>
      <ul className="service-list">
        {services.map((service) => (
          <li key={service.name} className={service.tone}>
            <b>{service.name}</b><small>{service.detail}</small><span><i/>{service.state}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
