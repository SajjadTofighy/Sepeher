import {
  Bell,
  Camera,
  Car,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ClipboardList,
  History,
  Layers,
  LayoutDashboard,
  LoaderCircle,
  MapPinned,
  Map,
  Moon,
  Search,
  Plus,
  Presentation,
  Siren,
  Radio,
  Route,
  Settings,
  ShieldCheck,
  Smartphone,
  ListChecks,
  BookOpen,
  FileCheck2,
  LogOut,
  KeyRound,
  MessagesSquare,
  SlidersHorizontal,
  Sparkles,
  Sun,
  TriangleAlert,
  X,
} from "lucide-react";
import { Fragment, lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, fa, labels, timeFa } from "./api";
import Stats from "./features/analytics/Stats";
import AssetPanel from "./features/assets/AssetPanel";
import AssetsPage from "./features/assets/AssetsPage";
import Assistant from "./features/assistant/Assistant";
import AuditPage from "./features/audit/AuditPage";
import CamerasPage from "./features/cameras/CamerasPage";
import CommandPage from "./features/command/CommandPage";
import DemoTour from "./features/demo/DemoTour";
import GeographyPage from "./features/geography/GeographyPage";
import IncidentPanel from "./features/incidents/IncidentPanel";
import IncidentsPage from "./features/incidents/IncidentsPage";
import MissionsPage from "./features/missions/MissionsPage";
import PoliciesPage from "./features/policies/PoliciesPage";
import PolicyModal from "./features/policies/PolicyModal";
import ConfigurationForm from "./features/settings/ConfigurationForm";
import FieldApp from "./features/field-comms/FieldApp";
import FieldCommsPage from "./features/field-comms/FieldCommsPage";
import SupervisionPage from "./features/supervision/SupervisionPage";
import GuidesPage from "./features/guides/GuidesPage";
import SettingsPage from "./features/settings/SettingsPage";
import { useOperations } from "./shared/api/useOperations";
import { useSession } from "./shared/auth/session";
import AssessmentPage from "./features/assessment/AssessmentPage";
import { download } from "./shared/lib/download";
import { IconButton, Modal } from "./shared/ui/primitives";
import type { Asset, Incident } from "./types";
const Analytics = lazy(() => import("./features/analytics/Analytics"));
const nav = [
  { id: "command", name: "مرکز فرماندهی", icon: Radio },
  { id: "incidents", name: "مدیریت حوادث", icon: TriangleAlert },
  { id: "assets", name: "پایگاه داده تجهیزات", icon: Car },
  { id: "missions", name: "عملیات گشت", icon: Route },
  { id: "geography", name: "محدوده‌ها و ناحیه‌ها", icon: MapPinned },
  { id: "cameras", name: "دوربین‌ها و IVA", icon: Camera, roadmap: true },
  { id: "policies", name: "سیاست‌های حراست", icon: SlidersHorizontal },
  { id: "replay", name: "تاریخچه و بازپخش", icon: History },
  { id: "analytics", name: "داشبورد مدیریتی", icon: LayoutDashboard },
  { id: "supervision", name: "نظارت استثنامحور گشت", icon: ListChecks },
  { id: "field-comms", name: "پیام، رسانه و گزارش میدانی", icon: MessagesSquare },
  { id: "field", name: "اپ میدانی نگهبان", icon: Smartphone },
  { id: "guides", name: "راهنما و فرم پشتیبان", icon: BookOpen },
  { id: "audit", name: "گزارش‌ها و پایش", icon: ClipboardList },
  { id: "assessment", name: "ارزیابی امنیتی (افتا)", icon: FileCheck2 },
  { id: "settings", name: "تنظیمات سامانه", icon: Settings },
];
// Navigation convenience only: the server decides every permission.
const NAV_ROLES: Record<string, string[]> = {
  supervision: ["shift_supervisor", "security_officer", "security_manager", "admin"],
  "field-comms": ["shift_supervisor", "security_officer", "security_manager", "admin"],
  assessment: ["auditor"],
  settings: ["admin", "security_manager", "security_officer", "shift_supervisor"],
};
export default function App() {
  const session = useSession();
  const roles = session.status === "demo" ? Object.values(NAV_ROLES).flat() : session.principal?.roles || [];
  const visibleNav = nav.filter((n) => !NAV_ROLES[n.id] || NAV_ROLES[n.id].some((role) => roles.includes(role)));
  const userName = session.principal?.username || (session.status === "demo" ? "اپراتور نمایشی" : "");
  const userRoles = session.status === "demo" ? "حالت نمایشی" : roles.map((role) => labels[role] || role).join("، ");
  const initials = userName.slice(0, 2) || "؟";
  const operations = useOperations();
  const searchInput = useRef<HTMLInputElement>(null);
  const headerMenuRef = useRef<HTMLDivElement>(null);
  const data = operations.data;
  const connected = operations.isSuccess;
  const error = operations.error?.message || "";
  const [page, setPage] = useState(location.pathname === "/auth/callback" ? "field" : location.hash.slice(1) || "command"),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState(""),
    [incident, setIncident] = useState<Incident | null>(null),
    [asset, setAsset] = useState<Asset | null>(null),
    [mapFocus, setMapFocus] = useState<Incident | null>(null),
    [reportTargetId, setReportTargetId] = useState<string>(),
    [reportMissionId, setReportMissionId] = useState<string>(),
    [hazardDrawingId, setHazardDrawingId] = useState<string | null>(null),
    [trackAsset, setTrackAsset] = useState<Asset | null>(null),
    [assistant, setAssistant] = useState(false),
    [clock, setClock] = useState(new Date()),
    [newPolicy, setNewPolicy] = useState(false),
    [resetConfirm, setResetConfirm] = useState(false),
    [tour, setTour] = useState(false),
    [replay, setReplay] = useState(100),
    [playing, setPlaying] = useState(false),
    [theme, setTheme] = useState<"dark" | "light">(() => localStorage.getItem("sepehr-theme") === "light" ? "light" : "dark"),
    [headerMenu, setHeaderMenu] = useState<"notifications" | "profile" | null>(null),
    [incidentFilter, setIncidentFilter] = useState("all");
  const load = async () => {
    await operations.refetch();
  };
  useEffect(() => {
    const tick = setInterval(() => setClock(new Date()), 1000);
    const hash = () => setPage(location.hash.slice(1) || "command");
    const focusSearch = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInput.current?.focus();
      }
    };
    window.addEventListener("hashchange", hash);
    window.addEventListener("keydown", focusSearch);
    return () => {
      clearInterval(tick);
      window.removeEventListener("hashchange", hash);
      window.removeEventListener("keydown", focusSearch);
    };
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("sepehr-theme", theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#eef5f8" : "#09151e");
  }, [theme]);
  useEffect(() => {
    if (!headerMenu) return;
    const close = (event: PointerEvent) => {
      if (!headerMenuRef.current?.contains(event.target as Node)) setHeaderMenu(null);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setHeaderMenu(null);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [headerMenu]);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(
      () =>
        setReplay((v) => {
          if (v >= 100) {
            setPlaying(false);
            return 100;
          }
          return v + 2;
        }),
      400,
    );
    return () => clearInterval(t);
  }, [playing]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 4500);
      return () => clearTimeout(t);
    }
  }, [toast]);
  async function act<T>(fn: () => Promise<T>, message = "عملیات انجام شد") {
    setBusy(true);
    try {
      const r = await fn();
      await load();
      setToast(message);
      return r;
    } catch (e) {
      setToast((e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }
  const go = (p: string) => {
    setPage(p);
    location.hash = p;
    setSearch("");
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  const selectedIncident =
    (incident && data?.incidents.find((i) => i.id === incident.id)) || incident;
  const selectedAsset =
    (asset && data?.assets.find((a) => a.id === asset.id)) || asset;
  const openIncident = useCallback((i: Incident) => {
    setIncident(i);
    setMapFocus(i);
    setAsset(null);
  }, []);
  const openAsset = useCallback((a: Asset) => {
    setAsset(a);
    setTrackAsset(a);
    setIncident(null);
  }, []);
  const openReportSource = (id: string) => {
    const i = data?.incidents.find(i => i.id === id);
    const a = data?.assets.find(a => a.id === id);
    if (i) { go("command"); openIncident(i); }
    else if (a) { go("command"); openAsset(a); }
    else if (data?.missions.some(m => m.id === id)) { setReportMissionId(id); go("missions"); }
    else if (id.includes("-SEG-") || data?.facilities.some(f => f.id === id)) { setReportTargetId(id); go("geography"); }
    else if (id.startsWith("AUD-")) go("audit");
    else if (data?.commands.some(c => c.id === id)) go("assets");
  };
  if (!data)
    return (
      <div className={`system-loader ${error ? "has-error" : ""}`} role="status" aria-live="polite">
        <div className="loader-grid" aria-hidden="true" />
        <div className="loader-orb loader-orb-one" aria-hidden="true" />
        <div className="loader-orb loader-orb-two" aria-hidden="true" />
        <div className="loader-console">
          <div className="loader-brand">
            <div className="loader-emblem">
              <span className="loader-ring ring-one" />
              <span className="loader-ring ring-two" />
              <span className="loader-scan" />
              <img src="/new-logo.png" alt="لوگوی سپهر حراست" />
            </div>
            <div className="loader-wordmark">
              <span>AGHAJARI SOC</span>
              <small>SECURITY OPERATIONS CENTER</small>
            </div>
          </div>
          <div className="loader-copy">
            <span className="loader-kicker">SEPEHR COMMAND SYSTEM</span>
            <h1>{error ? "ارتباط با مرکز فرماندهی برقرار نشد" : "در حال راه‌اندازی سامانه"}</h1>
            <p>{error ? "سرویس مرکزی در دسترس نیست؛ اتصال شبکه و وضعیت API را بررسی کنید." : "در حال همگام‌سازی نقشه، تجهیزات و جریان رخدادهای عملیاتی"}</p>
          </div>
          {!error ? (
            <>
              <div className="loader-progress" aria-label="در حال بارگذاری">
                <span/><span/><span/><span/><span/><span/><span/><span/><span/>
              </div>
              <div className="loader-steps" aria-hidden="true">
                <span><i className="live-dot"/>اتصال امن</span>
                <span><LoaderCircle className="spin" size={12}/>همگام‌سازی داده‌ها</span>
                <span>آماده‌سازی نقشه</span>
              </div>
            </>
          ) : (
            <button className="loader-retry" onClick={load}>
              <LoaderCircle size={17}/>
              تلاش مجدد برای اتصال
            </button>
          )}
          <div className="loader-footer">
            <span><ShieldCheck size={13}/> کانال ارتباطی رمزنگاری‌شده</span>
            <b>نسخه ۱.۰.۰</b>
          </div>
        </div>
      </div>
    );
  const filteredIncidents = data.incidents.filter(
    (i) =>
      (incidentFilter === "all" || i.severity === incidentFilter) &&
      (i.title + i.id + i.zone).includes(search),
  );
  return (
    <div className="app">
      <aside className="sidebar">
        <a className="brand" href="#command" onClick={() => go("command")}>
          <div className="brand-symbol">
            <img src="/new-logo.png" alt="" />
          </div>
          <div>
            <strong>AGHAJARI SOC</strong>
            <small>Security Operations Center</small>
          </div>
        </a>
        <div className="sidebar-network">
          <span className={connected ? "live-dot" : "offline-dot"} />
          <div><b>شبکه امن عملیاتی</b><small>SECURE COMMAND NETWORK</small></div>
          <span className="network-bars" aria-hidden="true"><i/><i/><i/></span>
        </div>
        <nav>
          {visibleNav.map((n, i) => (
            <Fragment key={n.id}>
              {(n.id === "command" || n.id === "policies" || n.id === "supervision") && (
                <div className="nav-section">
                  <span>{n.id === "command" ? "عملیات زنده" : n.id === "policies" ? "کنترل و تحلیل" : "گشت پیاده و سامانه"}</span>
                  <i />
                </div>
              )}
              <button
                className={page === n.id ? "nav-item current" : "nav-item"}
                onClick={() => go(n.id)}
              >
                <span className="nav-icon"><n.icon size={19} /></span>
                <span>{n.name}</span>
                {n.id === "incidents" && <em>{fa(data.summary.open_incidents)}</em>}
                {"roadmap" in n && <small className="nav-phase">فاز ۳</small>}
                {page === n.id && <ChevronLeft className="nav-arrow" size={15} />}
              </button>
            </Fragment>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="secure-box">
            <img className="secure-logo" src="/new-logo.png" alt="" />
            <div>
              <b>سپهر حراست</b><small>AGHAJARI SECURITY</small>
            </div>
            <div className="secure-version"><span>نسخه ۱.۰.۰</span><i className="live-dot" /></div>
          </div>
          <div className="profile">
            <div className="avatar">ح</div>
            <div>
              اپراتور حراست<small>شیفت عصر · دسترسی نمایشی</small>
            </div>
            <span className="live-dot" />
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="header-status-cluster">
            <div className="system-health">
              <span className={connected ? "live-dot" : "offline-dot"} />
              <div><small>وضعیت سامانه</small><strong>{connected ? "عملیاتی و پایدار" : "ارتباط با سرویس قطع است"}</strong></div>
            </div>
            <div className="date-clock">
              <small>{clock.toLocaleDateString("fa-IR", { timeZone: "Asia/Tehran", weekday: "long", day: "numeric", month: "long" })}</small>
              <span dir="ltr">{clock.toLocaleTimeString("fa-IR", { timeZone: "Asia/Tehran", hour: "2-digit", minute: "2-digit" })}</span>
            </div>
          </div>
          <div className="global-search" role="search">
            <Search className="search-icon" size={20}/>
            <input ref={searchInput} aria-label="جستجوی سراسری" placeholder="جستجوی رویداد، تجهیز، موقعیت یا آدرس IP ..." value={search} onChange={e => setSearch(e.target.value)}/>
          </div>
          <div className="header-account" ref={headerMenuRef}>
            <div className="header-actions">
              <div className="header-menu-anchor notification-anchor">
                <button className={`header-action notification-action ${headerMenu === "notifications" ? "active" : ""}`} aria-label="نمایش اعلان‌ها" aria-expanded={headerMenu === "notifications"} title="اعلان‌ها" onClick={() => setHeaderMenu(headerMenu === "notifications" ? null : "notifications")}>
                  <Bell size={19}/><span>{fa(data.summary.open_incidents)}</span>
                </button>
                {headerMenu === "notifications" && (
                  <section className="header-popover notification-popover" aria-label="اعلان‌های اخیر">
                    <header><div><b>اعلان‌های عملیاتی</b><small>{fa(data.summary.open_incidents)} مورد نیازمند توجه</small></div><span className="popover-live"><i className="live-dot"/> زنده</span></header>
                    <div className="notification-list">
                      {data.incidents.filter(i => i.status !== "closed").slice(0, 4).map(i => (
                        <button key={i.id} className={`notification-row ${i.severity}`} onClick={() => { setHeaderMenu(null); go("command"); openIncident(i); }}>
                          <span className="notification-mark"><TriangleAlert size={15}/></span>
                          <span><b>{i.title}</b><small>{i.zone} · {timeFa(i.created_at)}</small></span>
                          <ChevronLeft size={14}/>
                        </button>
                      ))}
                    </div>
                    <button className="popover-footer" onClick={() => { setHeaderMenu(null); go("incidents"); }}>مشاهده همه حوادث <ChevronLeft size={14}/></button>
                  </section>
                )}
              </div>
              <button className={`header-action theme-toggle ${theme}`} aria-label={theme === "dark" ? "فعال‌کردن حالت روشن" : "فعال‌کردن حالت تاریک"} aria-pressed={theme === "light"} title={theme === "dark" ? "حالت روشن" : "حالت تاریک"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
                <span className="theme-icon"><Moon className="theme-moon" size={18}/><Sun className="theme-sun" size={18}/></span>
              </button>
            </div>
            <span className="header-separator" />
            <div className="header-menu-anchor profile-anchor">
              <button className={`top-profile ${headerMenu === "profile" ? "active" : ""}`} aria-label="منوی کاربر" aria-expanded={headerMenu === "profile"} onClick={() => setHeaderMenu(headerMenu === "profile" ? null : "profile")}>
                <div className="avatar">{initials}<span className="profile-online" /></div>
                <span><b>{userName}</b><small>{userRoles}</small></span>
                <ChevronDown size={14}/>
              </button>
              {headerMenu === "profile" && (
                <section className="header-popover profile-popover" aria-label="منوی حساب کاربری">
                  <div className="profile-card"><div className="avatar">{initials}<span className="profile-online"/></div><div><b>{userName}</b><small>{userRoles}</small></div><span className="profile-access">{session.principal?.zone_ids.length ? `محوطه ${session.principal.zone_ids.join("، ")}` : session.status === "demo" ? "نمایشی" : "بدون محوطه"}</span></div>
                  {session.principal?.contractor_id && <div className="profile-roles"><span>پیمانکار {session.principal.contractor_id}</span></div>}
                  <div className="profile-menu">
                    <button onClick={() => { setHeaderMenu(null); go("settings"); }}><Settings size={16}/><span><b>تنظیمات سامانه</b><small>پیکربندی و وضعیت سرویس</small></span><ChevronLeft size={14}/></button>
                    <button onClick={() => { setHeaderMenu(null); go("audit"); }}><ClipboardList size={16}/><span><b>سوابق و گزارش‌ها</b><small>مشاهده فعالیت‌های ثبت‌شده</small></span><ChevronLeft size={14}/></button>
                  </div>
                  {session.principal?.roles.includes("admin") && session.config?.admin_url && (
                    <div className="profile-menu"><a href={session.config.admin_url} target="_blank" rel="noreferrer"><KeyRound size={16}/><span><b>کنسول کیکلاک</b><small>کاربران و نقش‌ها (شبکه مدیریت)</small></span></a></div>
                  )}
                  {session.status === "authenticated" && (
                    <div className="profile-menu"><button onClick={() => { setHeaderMenu(null); session.logout(); }}><LogOut size={16}/><span><b>خروج</b><small>پایان نشست و خروج از کیکلاک</small></span></button></div>
                  )}
                  <div className="profile-session"><span><i className={connected ? "live-dot" : "offline-dot"}/> {session.status === "demo" ? "حالت نمایشی بدون هویت" : "نشست امن فعال"}</span><small>{session.status === "demo" ? "DEMO MODE" : "SECURE SESSION"}</small></div>
                </section>
              )}
            </div>
          </div>
        </header>
        <main className={`${page}-main`}>
          <div className={`page-heading ${page === "command" ? "command-heading" : ""}`}>
            <div>
              <div className="eyebrow">AGHAJARI SECURITY OPERATIONS</div>
              <h1>
                {nav.find((n) => n.id === page)?.name || "مرکز فرماندهی"}
                <span className="title-dot" />
              </h1>
              <p>
                {page === "command"
                  ? "تصویر یکپارچه از منطقه؛ از آگاهی تا اقدام."
                  : page === "policies"
                    ? "دستورالعمل‌های حراست، قابل تعریف و قابل ارزیابی."
                    : page === "analytics"
                      ? "تصویر مدیریتی عملکرد شیفت و آمادگی عملیاتی."
                      : "شرکت بهره‌برداری نفت و گاز آغاجاری · محیط نمایشی"}
              </p>
            </div>
            <div className="heading-actions">
              {page === "policies" ? (
                <button className="primary" onClick={() => setNewPolicy(true)}>
                  <Plus size={17} />
                  سیاست جدید
                </button>
              ) : (
                <>
                  <button
                    className="secondary"
                    onClick={() => setAssistant(true)}
                  >
                    <Sparkles size={17} />
                    دستیار سپهر
                  </button>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={async () => {
                      const i = await act(
                        () => api<Incident>("/demo/scenario", "POST"),
                        "سناریوی اضطراری آغاز شد",
                      );
                      if (i) {
                        go("command");
                        openIncident(i);
                      }
                    }}
                  >
                    <Siren size={16} />
                    سناریوی اضطراری
                  </button>
                  <button
                    className="primary tour-launch"
                    disabled={tour}
                    onClick={() => {
                      setIncident(null);
                      setAsset(null);
                      setAssistant(false);
                      setPlaying(false);
                      go("command");
                      setTour(true);
                    }}
                  >
                    <Presentation size={17} />
                    نمایش ۵ دقیقه‌ای
                  </button>
                </>
              )}
            </div>
          </div>
          {error && (
            <div className="error-banner">
              ارتباط با API قطع شده است؛ داده‌های نمایش‌داده‌شده ممکن است قدیمی
              باشند. <button onClick={load}>اتصال مجدد</button>
            </div>
          )}
          {(page === "incidents" || page === "assets" || page === "missions" || page === "geography" || page === "cameras") && (
            <div className="operational-action-dock">
              <div className="action-dock-label"><span className="live-dot"/><div><b>ابزارهای عملیاتی</b><small>OPERATIONAL ACTIONS</small></div></div>
              <div className="action-dock-buttons">
                <button className="dock-action assistant-action" onClick={() => setAssistant(true)}><span><Sparkles size={17}/></span><div><b>دستیار سپهر</b><small>تحلیل هوشمند وضعیت</small></div></button>
                <button className="dock-action emergency-action" disabled={busy} onClick={async () => {
                  const i = await act(() => api<Incident>("/demo/scenario", "POST"), "سناریوی اضطراری آغاز شد");
                  if (i) { go("command"); openIncident(i); }
                }}><span><Siren size={17}/></span><div><b>سناریوی اضطراری</b><small>اجرای شبیه‌سازی بحران</small></div></button>
                <button className="dock-action presentation-action" disabled={tour} onClick={() => {
                  setIncident(null); setAsset(null); setAssistant(false); setPlaying(false); go("command"); setTour(true);
                }}><span><Presentation size={17}/></span><div><b>نمایش ۵ دقیقه‌ای</b><small>تور معرفی قابلیت‌ها</small></div></button>
              </div>
            </div>
          )}
          {page === "command" && (
            <Stats data={data} />
          )}
          {page === "command" && (
            <div className="command-toolbar">
              <div className="toolbar-status">
                <span className="live-dot"/>
                <div><b>نمای عملیاتی</b><small>LIVE VIEW</small></div>
              </div>
              <div className="command-tabs">
                <button className="active"><Map size={18}/><span>نقشه عملیاتی</span></button>
                <button onClick={() => go("incidents")}><ClipboardList size={17}/><span>رخدادها</span></button>
                <button onClick={() => go("missions")}><Route size={17}/><span>مأموریت‌ها</span></button>
                <button onClick={() => go("assets")}><Car size={17}/><span>تجهیزات</span></button>
              </div>
              <div className="toolbar-tools">
                <label className="map-search"><Search size={17}/><input aria-label="جستجو در نقشه" placeholder="جستجو در نقشه ..." value={search} onChange={e => setSearch(e.target.value)}/></label>
                <span className="toolbar-divider"/>
                <button className="region-select"><MapPinned size={16}/><span>همه مناطق</span><ChevronDown size={14}/></button>
              </div>
            </div>
          )}
          {(page === "command" || page === "replay") && (
            <CommandPage
              data={data}
              theme={theme}
              page={page}
              asset={asset || trackAsset}
              selectedIncident={mapFocus}
              replay={replay}
              playing={playing}
              incidentFilter={incidentFilter}
              filteredIncidents={filteredIncidents}
              openAsset={openAsset}
              openIncident={openIncident}
              go={go}
              setReplay={setReplay}
              setPlaying={setPlaying}
              setIncidentFilter={setIncidentFilter}
              setAssistant={setAssistant}
              presenting={tour}
              act={act}
              busy={busy}
              hazardDrawing={hazardDrawingId ? {
                busy,
                onCancel: () => setHazardDrawingId(null),
                onSave: async area => {
                  const result = await act(() => api(`/incidents/${hazardDrawingId}/hazard-area`, "PUT", area), "محدوده خطر ثبت شد");
                  if (result) setHazardDrawingId(null);
                },
              } : undefined}
            />
          )}
          {page === "geography" && (
            <GeographyPage
              data={data}
              theme={theme}
              focusTargetId={reportTargetId}
              act={act}
              busy={busy}
              onAsset={openAsset}
              onIncident={openIncident}
            />
          )}
          {page === "cameras" && (
            <CamerasPage />
          )}
          {page === "incidents" && (
            <IncidentsPage
              rows={filteredIncidents}
              allRows={data.incidents}
              search={search}
              setSearch={setSearch}
              filter={incidentFilter}
              setFilter={setIncidentFilter}
              onOpen={openIncident}
            />
          )}
          {page === "assets" && (
            <AssetsPage
              data={data}
              search={search}
              setSearch={setSearch}
              onOpen={openAsset}
              onRetry={(c) =>
                act(
                  () =>
                    api("/commands", "POST", {
                      asset_id: c.asset_id,
                      command: c.command,
                      channel: c.channel,
                      request_id: crypto.randomUUID(),
                    }),
                  "فرمان مجدداً ارسال شد",
                )
              }
            />
          )}
          {page === "missions" && (
            <MissionsPage data={data} busy={busy} act={act} focusId={reportMissionId} theme={theme} />
          )}
          {page === "policies" && (
            <PoliciesPage
              data={data}
              busy={busy}
              act={act}
              setToast={setToast}
              onNew={() => setNewPolicy(true)}
            />
          )}
          {page === "analytics" && (
            <Suspense
              fallback={<div className="empty">در حال بارگذاری نمودارها…</div>}
            >
              <Analytics
                data={data}
                onSource={openReportSource}
                onExport={() => download("sepehr-analytics.json", data.summary)}
                theme={theme}
              />
            </Suspense>
          )}
          {page === "supervision" && <SupervisionPage />}
          {page === "field-comms" && <FieldCommsPage data={data} act={act} busy={busy} />}
          {page === "field" && <FieldApp />}
          {page === "guides" && <GuidesPage />}
          {page === "assessment" && <AssessmentPage />}
          {page === "audit" && (
            <AuditPage data={data} act={act} setToast={setToast} />
          )}
          {page === "settings" && (
            <>
              <SettingsPage
                connected={connected}
                setResetConfirm={setResetConfirm}
              />
              <ConfigurationForm act={act} busy={busy} />
            </>
          )}
        </main>
        <footer className="footer">
          <span>
            سپهر حراست <i /> فرماندهی، کنترل و آگاهی موقعیتی
          </span>
          <span>نقشه OpenStreetMap · داده‌های عملیاتی نمونه</span>
        </footer>
      </div>
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={19} />
          {toast}
          <button aria-label="بستن اعلان" onClick={() => setToast("")}>
            <X size={15} />
          </button>
        </div>
      )}
      {selectedIncident && (
        <IncidentPanel
          incident={selectedIncident}
          data={data}
          busy={busy}
          close={() => setIncident(null)}
          act={act}
          onDrawHazard={() => {
            setMapFocus(selectedIncident);
            setHazardDrawingId(selectedIncident.id);
            go("command");
          }}
          onMap={() => {
            setMapFocus(selectedIncident);
            go("command");
          }}
        />
      )}
      {selectedAsset && (
        <AssetPanel
          asset={selectedAsset}
          data={data}
          busy={busy}
          act={act}
          close={() => setAsset(null)}
          onReplay={() => {
            setTrackAsset(selectedAsset);
            go("replay");
            setReplay(0);
            setPlaying(true);
            setAsset(null);
          }}
        />
      )}
      {assistant && (
        <Assistant
          data={data}
          close={() => setAssistant(false)}
          onIncident={(i) => {
            setAssistant(false);
            openIncident(i);
          }}
        />
      )}
      {newPolicy && (
        <PolicyModal
          data={data}
          close={() => setNewPolicy(false)}
          busy={busy}
          onSave={async (p) => {
            const r = await act(
              () => api("/policies", "POST", p),
              "پیش‌نویس سیاست ذخیره شد",
            );
            if (r) setNewPolicy(false);
          }}
        />
      )}
      {tour && (
        <DemoTour
          data={data}
          refresh={load}
          go={go}
          focus={(i) => {
            setIncident(null);
            setMapFocus(i);
            if (i) go("command");
          }}
          replay={() => {
            setTrackAsset(null);
            setMapFocus(null);
            go("replay");
            setReplay(0);
            setPlaying(true);
          }}
          close={() => setTour(false)}
        />
      )}
      {resetConfirm && (
        <Modal
          title="بازنشانی محیط نمایشی"
          onClose={() => setResetConfirm(false)}
        >
          <p className="modal-description">
            فرمان‌ها، سیاست‌های جدید و اقدامات این جلسه حذف و داده‌های اولیه
            بارگذاری می‌شوند.
          </p>
          <div className="modal-actions">
            <button
              className="danger-button"
              disabled={busy}
              onClick={async () => {
                const r = await act(
                  () => api("/demo/reset", "POST"),
                  "محیط نمایشی بازنشانی شد",
                );
                if (r) {
                  setResetConfirm(false);
                  setIncident(null);
                  setAsset(null);
                }
              }}
            >
              بازنشانی داده‌ها
            </button>
            <button
              className="secondary"
              onClick={() => setResetConfirm(false)}
            >
              انصراف
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
