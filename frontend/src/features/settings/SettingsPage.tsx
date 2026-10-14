import { Activity, Database, ExternalLink, FileText, Map, Network, RadioTower, RotateCcw, ServerCog, ShieldCheck, Sparkles } from "lucide-react";

export default function SettingsPage({ connected, setResetConfirm }: { connected: boolean; setResetConfirm: (s: boolean) => void }) {
  const services = [
    { n: "سرویس API پایتون", d: "FastAPI · داده‌های حافظه‌ای", s: connected ? "متصل" : "قطع", icon: ServerCog, tone: connected ? "online" : "offline" },
    { n: "نقشه سازمانی", d: "WMS / WFS · تنظیم در اتصال GIS", s: "قابل تنظیم", icon: Map, tone: "config" },
    { n: "ردیاب و پیامک", d: "شبیه‌سازی چرخه فرمان", s: "نمایشی", icon: RadioTower, tone: "demo" },
    { n: "دوربین و IVA", d: "اتصال در فاز سوم", s: "نمایشی", icon: Activity, tone: "demo" },
    { n: "دستیار قاعده‌محور", d: "پاسخ قالبی از رکوردهای سامانه؛ بدون مدل زبانی", s: "نمایشی", icon: Sparkles, tone: "demo" },
  ];

  return <section className="settings-overview">
    <header className="settings-hero">
      <div className="settings-hero-copy">
        <span className="settings-kicker"><ServerCog size={15}/> SYSTEM CONTROL PLANE</span>
        <h2>تنظیمات و حاکمیت سامانه</h2>
        <p>مدیریت زیرساخت، قواعد عملیاتی، اتصال داده و کنترل‌های امنیتی</p>
        <div className="settings-system-state"><span className={connected ? "connected" : "disconnected"}><i className="live-dot"/> {connected ? "هسته سامانه متصل" : "ارتباط هسته قطع"}</span><small>محیط ارائه مستقل و محلی</small></div>
      </div>
      <div className="settings-hero-visual" aria-hidden="true"><ServerCog size={40}/><i/><i/><i/></div>
      <div className="settings-health-score"><small>آمادگی سرویس</small><strong>{connected ? "عملیاتی" : "نیازمند بررسی"}</strong><span>{connected ? "API پاسخ‌گو است" : "ارتباط API برقرار نیست"}</span></div>
    </header>

    <div className="settings-kpis">
      <article className="cyan"><span><Network size={18}/></span><div><small>وضعیت API</small><b>{connected ? "متصل" : "قطع"}</b><em>کانال داده سامانه</em></div></article>
      <article className="green"><span><ShieldCheck size={18}/></span><div><small>محیط اجرا</small><b>محلی</b><em>بدون فرمان واقعی</em></div></article>
      <article className="violet"><span><Database size={18}/></span><div><small>ذخیره‌سازی</small><b>حافظه‌ای</b><em>مخصوص ارائه</em></div></article>
      <article className="amber"><span><ServerCog size={18}/></span><div><small>سرویس‌های تعریف‌شده</small><b>{services.length.toLocaleString("fa-IR")}</b><em>اتصال و شبیه‌ساز</em></div></article>
    </div>

    <div className="settings-grid settings-service-grid">
      <section className="settings-service-panel">
        <header><div><span><Network size={18}/></span><div><b>اتصالات و زیرساخت</b><small>آمادگی اتصال به زیرساخت سازمان در نسخه عملیاتی</small></div></div><em>{services.filter(x => x.tone === "online").length.toLocaleString("fa-IR")} سرویس متصل</em></header>
        <div className="settings-service-list">{services.map((service) => <article className={`setting-row ${service.tone}`} key={service.n}>
          <span className="setting-service-icon"><service.icon size={17}/></span><div><b>{service.n}</b><small>{service.d}</small></div><span className="setting-state"><i/>{service.s}</span>
        </article>)}</div>
      </section>
      <section className="settings-environment-panel">
        <header><span><ShieldCheck size={18}/></span><div><b>محیط ارائه امن</b><small>DEMO ENVIRONMENT</small></div></header>
        <div className="setting-note"><ShieldCheck size={31}/><h3>دموی مستقل محلی</h3><p>تمام رکوردها، موقعیت‌ها و هویت‌ها ساختگی هستند. فرمان‌ها به تجهیزات واقعی ارسال نمی‌شوند.</p></div>
        <div className="settings-safety-note"><i/><span>کنترل دسترسی، احراز هویت چندعاملی و ذخیره‌سازی پایدار باید برای نسخه عملیاتی تکمیل شوند.</span></div>
        <div className="settings-environment-actions">
          <a className="secondary full" href="/docs" target="_blank" rel="noreferrer"><FileText size={16}/> مستندات تعاملی API <ExternalLink size={13}/></a>
          <button className="danger-button full" onClick={() => setResetConfirm(true)}><RotateCcw size={15}/> بازنشانی داده‌های نمایشی</button>
        </div>
      </section>
    </div>
  </section>;
}
