import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Database, Network, Shield, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { PanelTitle } from "../../shared/ui/primitives";
import type { RuntimeSettings } from "../../types";
export default function ConfigurationForm({
  act,
  busy,
}: {
  act: Act;
  busy: boolean;
}) {
  const client = useQueryClient();
  const q = useQuery({
    queryKey: ["settings"],
    queryFn: () => api<RuntimeSettings>("/settings"),
  });
  const [draft, setDraft] = useState<RuntimeSettings | null>(null);
  const [tab, setTab] = useState("policies");
  useEffect(() => {
    if (q.data) setDraft(q.data);
  }, [q.data]);
  function set<K extends keyof RuntimeSettings>(k: K, v: RuntimeSettings[K]) {
    setDraft((p) => (p ? { ...p, [k]: v } : p));
  }
  if (q.isError)
    return (
      <div className="error-banner">
        دریافت تنظیمات ناموفق بود.{" "}
        <button onClick={() => q.refetch()}>تلاش مجدد</button>
      </div>
    );
  if (!draft) return <div className="empty">در حال دریافت تنظیمات…</div>;
  return (
    <section className="panel configuration-panel">
      <PanelTitle
        title="تنظیمات عملیات و حاکمیت داده"
        sub="تنظیمات در حافظهٔ سرور ذخیره می‌شوند؛ اتصال GIS در نقشه اعمال می‌شود."
      />
      <div className="settings-tabs">
        {[
          { id: "policies", name: "کنترل هشدار", icon: Shield },
          { id: "gis", name: "اتصال GIS", icon: Network },
          { id: "privacy", name: "نگهداری و حریم خصوصی", icon: Database },
          { id: "roles", name: "نقش‌ها و دسترسی", icon: Users },
        ].map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? "selected" : ""}
            onClick={() => setTab(t.id)}
          >
            <t.icon size={16} />
            {t.name}
          </button>
        ))}
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const r = await act(
            () => api<RuntimeSettings>("/settings", "PUT", draft),
            "تنظیمات ذخیره شد",
          );
          if (r) client.setQueryData(["settings"], r);
        }}
      >
        {tab === "policies" && (
          <>
            <div className="form-grid">
              <label className="field">
                قطع ارتباط در پوشش عادی (دقیقه)
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={draft.normal_coverage_timeout}
                  onChange={(e) =>
                    set("normal_coverage_timeout", +e.target.value)
                  }
                />
              </label>
              <label className="field">
                قطع ارتباط در پوشش ضعیف (دقیقه)
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={draft.weak_coverage_timeout}
                  onChange={(e) =>
                    set("weak_coverage_timeout", +e.target.value)
                  }
                />
              </label>
              <label className="field">
                پنجره ادغام هشدار تکراری (ثانیه)
                <input
                  type="number"
                  min={5}
                  max={3600}
                  value={draft.dedupe_seconds}
                  onChange={(e) => set("dedupe_seconds", +e.target.value)}
                />
              </label>
              <label className="field">
                فاصله بررسی هوشمندی (ثانیه)
                <input
                  type="number"
                  min={1}
                  max={3600}
                  value={draft.intel_tick_seconds ?? 5}
                  onChange={(e) => set("intel_tick_seconds", +e.target.value)}
                />
              </label>
            </div>
            <div className="form-grid">
              {(
                [
                  [
                    "intel_coverage_buffer_m",
                    "حریم بازدید خط لوله (متر)",
                    0,
                    10000,
                  ],
                  [
                    "intel_coverage_backfill_hours",
                    "بازه بررسی مسیر گذشته (ساعت)",
                    0.1,
                    8760,
                  ],
                  [
                    "intel_coverage_stale_hours",
                    "مهلت بازدید خطوط و تأسیسات (ساعت)",
                    0.1,
                    8760,
                  ],
                  [
                    "intel_coverage_unmanned_stale_hours",
                    "مهلت بازدید تأسیسات بدون سرنشین (ساعت)",
                    0.1,
                    8760,
                  ],
                ] as const
              ).map(([key, label, min, max]) => (
                <label className="field" key={key}>
                  {label}
                  <input
                    type="number"
                    min={min}
                    max={max}
                    step="any"
                    value={draft[key]}
                    onChange={(e) => set(key, +e.target.value)}
                  />
                </label>
              ))}
              <label className="field">
                حالت یافته‌های پوشش گشت
                <select
                  value={draft.intel_coverage_mode}
                  onChange={(e) =>
                    set(
                      "intel_coverage_mode",
                      e.target.value as RuntimeSettings["intel_coverage_mode"],
                    )
                  }
                >
                  <option value="shadow">سایه</option>
                  <option value="active">فعال</option>
                </select>
              </label>
            </div>
            <div>
              <div className="form-grid">
                {([
                  ["intel_safety_stop_minutes", "آستانه توقف ایمنی (دقیقه)", 0.1, 120],
                  ["intel_safety_checkin_minutes", "مهلت تأیید سلامت (دقیقه)", 0.1, 120],
                  ["intel_safety_remote_km", "حریم دورافتاده خط لوله (کیلومتر)", 0, 100],
                  ["intel_hazard_approach_km", "حریم هشدار نزدیک‌شدن به خطر (کیلومتر)", 0, 100],
                ] as const).map(([key, label, min, max]) => <label className="field" key={key}>
                  {label}<input type="number" step="any" min={min} max={max} value={draft[key]}
                    onChange={(e) => set(key, +e.target.value)} />
                </label>)}
                <label className="field">ساعت عادی گشت
                  <input dir="ltr" value={draft.intel_safety_normal_hours}
                    onChange={(e) => set("intel_safety_normal_hours", e.target.value)} />
                </label>
                <label className="field">حالت پایش ایمنی گشت
                  <select value={draft.intel_safety_mode} onChange={(e) => set("intel_safety_mode", e.target.value as RuntimeSettings["intel_safety_mode"])}>
                    <option value="shadow">سایه</option><option value="active">فعال</option>
                  </select>
                </label>
              </div>
            </div>
            <div className="detail-section">
              <h3>ریسک و برنامه گشت</h3>
              <div className="form-grid">
                {(["incidents", "access", "staleness", "exposure"] as const).map(key => <label className="field" key={key}>
                  وزن {({ incidents: "رخدادها", access: "دسترسی", staleness: "دیرکرد", exposure: "بدون سرنشین" })[key]}
                  <input type="number" min={0} max={10} step="any" value={draft.intel_risk_weights?.[key] ?? 0}
                    onChange={e => set("intel_risk_weights", {
                      incidents: draft.intel_risk_weights?.incidents ?? 0,
                      access: draft.intel_risk_weights?.access ?? 0,
                      staleness: draft.intel_risk_weights?.staleness ?? 0,
                      exposure: draft.intel_risk_weights?.exposure ?? 0,
                      [key]: +e.target.value,
                    })} />
                </label>)}
                {([
                  ["intel_risk_incident_radius_m", "حریم رخداد در ریسک (متر)", 1, 100000],
                  ["intel_risk_half_life_days", "نیمه‌عمر رخداد (روز)", 0.1, 3650],
                  ["intel_risk_alpha", "توان وزن نمونه‌گیری", 0.1, 10],
                  ["intel_plan_dwell_minutes", "توقف در ایستگاه (دقیقه)", 0, 240],
                  ["intel_plan_time_jitter_minutes", "حریم تفاوت زمان بازدید (دقیقه)", 0, 720],
                  ["intel_plan_window_minutes", "پنجره ثبت بازدید (دقیقه)", 0, 240],
                ] as const).map(([key, label, min, max]) => <label className="field" key={key}>{label}
                  <input type="number" min={min} max={max} step="any" value={draft[key]} onChange={e => set(key, +e.target.value)} />
                </label>)}
              </div>
            </div>
            <div className="detail-section">
              <h3>شیفت‌های گزارش · زمان تهران</h3>
              <label className="field">بازه‌ها، هر شیفت در یک خط
                <textarea dir="ltr" rows={3} value={(draft.intel_shifts || []).join("\n")}
                  onChange={e => set("intel_shifts", e.target.value.split("\n"))} />
              </label>
            </div>
            <div className="detail-section">
              <h3>ورودی‌های مجاز فاز سوم</h3>
              <p className="muted">پیش‌فرض غیرفعال؛ ورودی فشار نیازمند مجوز بهره‌برداری و اتصال یک‌طرفه است.</p>
              <div className="form-grid">
                <label className="field">فعال‌سازی دریافت یک‌طرفه فشار
                  <input type="checkbox" checked={draft.intel_pressure_enabled ?? false} onChange={e => set("intel_pressure_enabled", e.target.checked)} />
                </label>
                <label className="field">حالت بررسی افت فشار
                  <select value={draft.intel_pressure_mode ?? "shadow"} onChange={e => set("intel_pressure_mode", e.target.value as RuntimeSettings["intel_pressure_mode"])}>
                    <option value="shadow">سایه · فقط یافته</option><option value="active">فعال · مسیریابی پرونده</option>
                  </select>
                </label>
                <label className="field">فعال‌سازی ورودی واقعی پلاک‌خوان
                  <input type="checkbox" checked={draft.intel_anpr_enabled ?? false} onChange={e => set("intel_anpr_enabled", e.target.checked)} />
                </label>
                <label className="field">بازه شب پلاک‌خوان · تهران
                  <input dir="ltr" value={draft.intel_anpr_night_hours ?? "22:00–06:00"} onChange={e => set("intel_anpr_night_hours", e.target.value)} />
                </label>
                <label className="field">پنجره تکرار پلاک (دقیقه)
                  <input type="number" min={0.1} max={1440} step="any" value={draft.intel_anpr_repeat_window_minutes ?? 30} onChange={e => set("intel_anpr_repeat_window_minutes", +e.target.value)} />
                </label>
                <label className="field">پلاک‌های مجاز · هر پلاک در یک خط
                  <textarea rows={3} value={(draft.intel_vehicle_allowlist || []).join("\n")} onChange={e => set("intel_vehicle_allowlist", e.target.value.split("\n").filter(v => v.trim()))} />
                </label>
                <label className="field">شناسه دوربین‌های حساس · هر شناسه در یک خط
                  <textarea dir="ltr" rows={3} value={(draft.intel_anpr_sensitive_camera_ids || []).join("\n")} onChange={e => set("intel_anpr_sensitive_camera_ids", e.target.value.split("\n").filter(v => v.trim()))} />
                </label>
              </div>
            </div>
            <div className="detail-section">
              <h3>تماس‌های اضطراری</h3>
              {(draft.intel_emergency_contacts || []).map((contact, index) => <div className="form-grid" key={index}>
                {(["name", "role", "phone"] as const).map((key) => <label className="field" key={key}>
                  {({ name: "نام تماس", role: "نقش تماس", phone: "شماره یا شناسه تماس" })[key]}
                  <input value={contact[key]} required dir={key === "phone" ? "ltr" : "rtl"} onChange={(e) => set("intel_emergency_contacts", draft.intel_emergency_contacts!.map((c, k) => k === index ? { ...c, [key]: e.target.value } : c))} />
                </label>)}
                <button type="button" className="text-button" onClick={() => set("intel_emergency_contacts", draft.intel_emergency_contacts!.filter((_, k) => k !== index))}>حذف تماس</button>
              </div>)}
              <button type="button" className="secondary" disabled={(draft.intel_emergency_contacts?.length || 0) >= 20}
                onClick={() => set("intel_emergency_contacts", [...(draft.intel_emergency_contacts || []), { name: "", role: "", phone: "" }])}>افزودن تماس اضطراری</button>
            </div>
            <label className="switch-row">
              <div>
                <b>حالت سایه سراسری</b>
                <small>ثبت هشدار همه سیاست‌ها بدون ایجاد پرونده</small>
              </div>
              <input
                type="checkbox"
                checked={draft.shadow_mode}
                onChange={(e) => set("shadow_mode", e.target.checked)}
              />
            </label>
            <label className="switch-row">
              <div>
                <b>سکوت دوره تعمیرات / مانور</b>
                <small>
                  هشدار سیاست ثبت می‌شود اما به اتاق کنترل ارسال نمی‌شود
                </small>
              </div>
              <input
                type="checkbox"
                checked={draft.maintenance_silence}
                onChange={(e) => set("maintenance_silence", e.target.checked)}
              />
            </label>
          </>
        )}
        {tab === "gis" && (
          <>
            <label className="field">
              لایهٔ GIS سازمانی روی نقشه
              <select
                value={draft.gis_mode}
                onChange={(e) =>
                  set("gis_mode", e.target.value as RuntimeSettings["gis_mode"])
                }
              >
                <option value="local">فقط OpenStreetMap و لایه‌های محلی</option>
                <option value="wms">سرویس WMS سازمان</option>
                <option value="wfs">سرویس WFS سازمان</option>
              </select>
            </label>
            <label className="field">
              آدرس سرویس
              <input
                dir="ltr"
                type="url"
                required={draft.gis_mode !== "local"}
                placeholder="https://gis.example.internal/service"
                value={draft.gis_url}
                onChange={(e) => set("gis_url", e.target.value)}
              />
            </label>
            {draft.gis_mode !== "local" && (
              <>
                <label className="field">
                  {draft.gis_mode === "wms"
                    ? "نام لایه‌های WMS (با کاما جدا کنید)"
                    : "نام نوع عارضه WFS"}
                  <input
                    dir="ltr"
                    required
                    value={draft.gis_layers || ""}
                    placeholder="workspace:layer"
                    onChange={(e) => set("gis_layers", e.target.value)}
                  />
                </label>
                {draft.gis_mode === "wms" ? (
                  <>
                    <label className="field">
                      نسخهٔ WMS
                      <select
                        value={draft.gis_wms_version || "1.3.0"}
                        onChange={(e) =>
                          set(
                            "gis_wms_version",
                            e.target
                              .value as RuntimeSettings["gis_wms_version"],
                          )
                        }
                      >
                        <option>1.3.0</option>
                        <option>1.1.1</option>
                      </select>
                    </label>
                    <label className="field">
                      شفافیت لایه
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={draft.gis_opacity ?? 0.7}
                        onChange={(e) => set("gis_opacity", +e.target.value)}
                      />
                    </label>
                  </>
                ) : (
                  <label className="field">
                    نسخهٔ WFS
                    <select
                      value={draft.gis_wfs_version || "2.0.0"}
                      onChange={(e) =>
                        set(
                          "gis_wfs_version",
                          e.target.value as RuntimeSettings["gis_wfs_version"],
                        )
                      }
                    >
                      <option>2.0.0</option>
                      <option>1.1.0</option>
                    </select>
                  </label>
                )}
              </>
            )}
            <div className="info-box">
              پس از ذخیره، لایه روی نقشه نمایش داده می‌شود. WMS باید EPSG:3857 و
              WFS باید خروجی GeoJSON با طول و عرض WGS 84 را پشتیبانی کند. دسترسی
              شبکه و CORS سرویس باید برای این برنامه مجاز باشد. وضعیت دریافت در
              ابزارهای GIS نقشه نمایش داده می‌شود.
            </div>
          </>
        )}
        {tab === "privacy" && (
          <>
            <label className="field">
              مدت نگهداری موقعیت (روز)
              <input
                type="number"
                min={7}
                max={3650}
                value={draft.retention_days}
                onChange={(e) => set("retention_days", +e.target.value)}
              />
            </label>
            <div className="privacy-principles">
              <p>
                <Check size={16} />
                ردیابی نیرو فقط در مأموریت و شیفت مصوب
              </p>
              <p>
                <Check size={16} />
                ثبت مشاهده تاریخچه در دفتر سوابق
              </p>
              <p>
                <Check size={16} />
                محدودکردن دسترسی بر اساس حوزه مأموریت
              </p>
            </div>
            <p className="info-box">
              این‌ها اصول طراحی نسخه عملیاتی‌اند؛ job حذف خودکار و محدودسازی
              هویتی در دمو اجرا نمی‌شوند.
            </p>
          </>
        )}
        {tab === "roles" && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>نقش نمونه</th>
                  <th>حوزه</th>
                  <th>مجوز موردنظر</th>
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    "اپراتور اتاق کنترل",
                    "ناحیه مأموریت",
                    "تأیید حادثه، اعزام، فرمان‌های مجاز",
                  ],
                  ["سرپرست حراست", "کل شرکت", "تأیید سیاست، گزارش و نظارت"],
                  ["نیروی میدانی", "مأموریت خود", "مشاهده مأموریت و ثبت حضور"],
                  ["مدیر فنی", "زیرساخت", "پایش سرویس؛ بدون حذف سوابق"],
                ].map((r) => (
                  <tr key={r[0]}>
                    {r.map((c) => (
                      <td key={c}>{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="info-box">
              ماتریس نقش‌ها برای طراحی است. حساب کاربری دمو احراز هویت نمی‌شود و
              این محدودیت‌ها در backend اعمال نشده‌اند.
            </p>
          </div>
        )}
        {tab !== "roles" && (
          <button className="primary" type="submit" disabled={busy}>
            <Check size={16} />
            ذخیره تنظیمات
          </button>
        )}
      </form>
    </section>
  );
}
