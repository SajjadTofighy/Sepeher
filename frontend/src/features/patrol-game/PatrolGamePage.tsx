import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, Crosshair, Database, Footprints, Plus, Scale, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, fa, timeFa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { tehranInputISO } from "../../shared/lib/time";
import type {
  EventWeights,
  PatrolGameApproval,
  PatrolGameSettings,
  PatrolStrategy,
  RiskEvent,
  RiskEventImportResult,
  RiskEventInput,
  RiskStatus,
  RouteCoverageInput,
  RuntimeSettings,
  Station,
  TargetClassParameters,
  TargetOverride,
  TourRoute,
} from "../../types";
import StrategyView, { MODEL_LABELS, num } from "./StrategyView";

type Tab = "parameters" | "events" | "routes" | "preview";
// Server responses always carry these defaulted lists; the generated input types mark them optional.
type Draft = PatrolGameSettings & { classes: TargetClassParameters[]; overrides: TargetOverride[]; event_weights: EventWeights };
const BASE_KEYS = ["facility_unmanned", "facility_manned", "pipeline_segment", "station_default"];
const WEIGHT_LABELS: Record<keyof EventWeights, string> = {
  incident: "حادثه ثبت‌شده در سامانه",
  import_theft: "سابقه سرقت",
  import_sabotage: "سابقه خرابکاری",
  import_intrusion: "سابقه نفوذ",
  import_tampering: "سابقه دستکاری",
  import_vandalism: "سابقه تخریب",
  import_other: "سابقه سایر",
  report_security: "گزارش میدانی امنیتی",
  report_damage: "گزارش آسیب",
  report_uxo: "گزارش مهمات عمل‌نکرده",
  report_drone_sighting: "گزارش مشاهده پهپاد",
  report_operations: "گزارش عملیاتی",
  report_safety_hse: "گزارش ایمنی",
  report_other: "گزارش سایر",
  seal_anomaly: "ناهنجاری پلمب",
  tag_replay: "تکرار برچسب (اسکن جعلی)",
};
const CATEGORIES: Record<RiskEventInput["category"], string> = {
  theft: "سرقت",
  sabotage: "خرابکاری",
  intrusion: "نفوذ",
  tampering: "دستکاری",
  vandalism: "تخریب",
  other: "سایر",
};
const SOURCES: Record<string, string> = {
  import: "سوابق واردشده",
  incident: "حادثه",
  field_report: "گزارش میدانی",
  station_task: "وظیفه ایستگاه",
  scan: "اسکن",
};

function useSettings() {
  return useQuery({ queryKey: ["settings"], queryFn: () => api<RuntimeSettings>("/settings") });
}

function useTargets() {
  const risk = useQuery({ queryKey: ["intel", "risk"], queryFn: () => api<RiskStatus>("/intel/risk") });
  const stations = useQuery({ queryKey: ["tour", "stations"], queryFn: () => api<Station[]>("/tour/stations") });
  return [
    ...(risk.data?.items || []).map((item) => ({ id: item.id, name: item.name })),
    ...(stations.data || []).map((station) => ({ id: station.id, name: `ایستگاه ${station.name}` })),
  ];
}

export default function PatrolGamePage({ act, busy }: { act: Act; busy: boolean }) {
  const [tab, setTab] = useState<Tab>("parameters");
  const approval = useQuery({
    queryKey: ["patrol-game", "approval"],
    queryFn: () => api<PatrolGameApproval>("/intel/patrol-game/approval"),
  });
  return (
    <section className="supervision patrol-game">
      <p className={`status-line ${approval.data?.approved ? "" : "flag"}`}>
        {approval.data?.approved ? "پارامترهای سازمان تأییدشده است" : "پارامترهای سازمان هنوز تأیید نشده است"}
      </p>
      <div className="comms-tabs" role="tablist">
        {(
          [
            ["parameters", "پارامترهای سازمان", Scale],
            ["events", "دفتر رخدادهای تاریخی", Database],
            ["routes", "تصمیم بازدید ایستگاه‌ها", Footprints],
            ["preview", "پیش‌نمایش راهبرد خودرویی", Crosshair],
          ] as const
        ).map(([id, name, Icon]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "current" : ""} onClick={() => setTab(id)}>
            <Icon size={16} />
            {name}
          </button>
        ))}
      </div>
      {tab === "parameters" && <Parameters act={act} busy={busy} approval={approval.data} />}
      {tab === "events" && <Events act={act} busy={busy} />}
      {tab === "routes" && <Routes act={act} busy={busy} />}
      {tab === "preview" && <Preview />}
    </section>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 0.01,
  hint,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  hint?: string;
}) {
  return (
    <label className="field" title={hint}>
      {label}
      <input type="number" required min={min} max={max} step={step} value={value} onChange={(e) => onChange(+e.target.value)} />
      {hint && <small className="muted">{hint}</small>}
    </label>
  );
}

function Parameters({ act, busy, approval }: { act: Act; busy: boolean; approval?: PatrolGameApproval }) {
  const client = useQueryClient();
  const settings = useSettings();
  const targets = useTargets();
  const [local, setLocal] = useState<Draft | null>(null);
  const game = settings.data?.patrol_game;
  if (!settings.data || !game?.classes || !game.event_weights) return <div className="panel empty">در حال دریافت پارامترها…</div>;
  const draft: Draft = local ?? { ...game, classes: game.classes, overrides: game.overrides ?? [], event_weights: game.event_weights };
  const set = (changes: Partial<Draft>) => setLocal({ ...draft, ...changes });
  const labels = settings.data.station_sensitivity_labels ?? [];
  const missing = labels.filter((label) => !draft.classes.some((c) => c.key === `station:${label}`));
  const fallback = draft.classes.find((c) => c.key === "station_default");
  const overrides: TargetOverride[] = draft.overrides;
  const setOverride = (index: number, changes: Partial<TargetOverride>) =>
    set({ overrides: overrides.map((row, i) => (i === index ? { ...row, ...changes } : row)) });
  const save = async () => {
    const saved = await act(
      () => api<RuntimeSettings>("/settings", "PUT", { ...settings.data, patrol_game: draft }),
      "پارامترهای راهبرد گشت ذخیره شد؛ برای اعمال، مدیر حراست باید آن‌ها را تأیید کند",
    );
    if (saved) {
      setLocal(null);
      client.setQueryData(["settings"], saved);
      await client.invalidateQueries({ queryKey: ["patrol-game"] });
      await client.invalidateQueries({ queryKey: ["intel", "risk"] });
    }
  };
  const approve = async () => {
    const result = await act(
      () => api<PatrolGameApproval>("/intel/patrol-game/approve", "POST"),
      "پارامترهای سازمان تأیید شد",
    );
    if (result) await client.invalidateQueries({ queryKey: ["patrol-game"] });
  };
  return (
    <form
      className="patrol-game-grid"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <section className="panel">
        <h3>مدل تصمیم و فرض‌های تهدید</h3>
        <div className="form-grid">
          <label className="field">
            مدل راهبرد
            <select value={draft.model} onChange={(e) => set({ model: e.target.value as PatrolGameSettings["model"] })}>
              {Object.entries(MODEL_LABELS).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <NumberField
            label="نمایه تهدید (۰ سارق فرصت‌طلب، ۱ خرابکار پیامدمحور)"
            value={draft.threat_profile}
            min={0}
            max={1}
            onChange={(threat_profile) => set({ threat_profile })}
          />
          {draft.model === "quantal" && (
            <NumberField
              label="عقلانیت مهاجم (λ)"
              value={draft.quantal_rationality}
              min={0}
              max={50}
              step={0.1}
              hint="۰ یعنی انتخاب تصادفی؛ مقدار زیاد یعنی مهاجم کاملاً منطقی"
              onChange={(quantal_rationality) => set({ quantal_rationality })}
            />
          )}
          <NumberField
            label="مدت لازم برای اقدام مهاجم (دقیقه)"
            value={draft.attack_minutes}
            min={1}
            max={1440}
            step={1}
            onChange={(attack_minutes) => set({ attack_minutes })}
          />
          <NumberField
            label="سقف احتمال کشف با یک بازدید"
            value={draft.max_detection}
            min={0.01}
            max={1}
            onChange={(max_detection) => set({ max_detection })}
          />
          <NumberField
            label="بازدارندگی دستگیری برای مهاجم"
            value={draft.capture_penalty}
            min={0}
            max={10}
            onChange={(capture_penalty) => set({ capture_penalty })}
          />
        </div>
      </section>
      <section className="panel">
        <h3>برآورد بیزی نرخ رخداد</h3>
        <div className="form-grid">
          <NumberField
            label="چندک برنامه‌ریزی نرخ"
            value={draft.risk_quantile}
            min={0.5}
            max={0.99}
            hint="۰٫۵ میانه؛ مقدار بالاتر برنامه‌ریزی محتاطانه‌تر"
            onChange={(risk_quantile) => set({ risk_quantile })}
          />
          <NumberField label="سطح بازه باور" value={draft.credible_level} min={0.5} max={0.99} onChange={(credible_level) => set({ credible_level })} />
          <NumberField
            label="وزن دانش کارشناسی (سال معادل مشاهده)"
            value={draft.prior_strength_years}
            min={0.1}
            max={20}
            step={0.1}
            onChange={(prior_strength_years) => set({ prior_strength_years })}
          />
          <NumberField
            label="نیمه‌عمر اثر رخدادها (روز)"
            value={draft.half_life_days}
            min={7}
            max={3650}
            step={1}
            onChange={(half_life_days) => set({ half_life_days })}
          />
          <NumberField
            label="شعاع اثر مکانی رخداد (متر)"
            value={draft.spatial_bandwidth_m}
            min={10}
            max={10000}
            step={10}
            onChange={(spatial_bandwidth_m) => set({ spatial_bandwidth_m })}
          />
          <label className="field">
            آغاز سوابق ثبت‌شده سازمان
            <input type="date" value={draft.history_start || ""} onChange={(e) => set({ history_start: e.target.value || null })} />
            <small className="muted">برای سوابق واردشده الزامی است تا نرخ بیش‌برآورد نشود</small>
          </label>
        </div>
      </section>
      <section className="panel patrol-game-wide">
        <h3>ارزش و نرخ پایه دسته‌های هدف</h3>
        <p className="muted">ارزش (۱ تا ۱۰۰) پیامد از دست رفتن هدف برای سازمان است؛ نرخ پایه تعداد اقدام مورد انتظار در سال بر پایه دانش کارشناسی حراست است.</p>
        <div className="risk-table-scroll">
          <table className="risk-breakdown">
            <thead>
              <tr>
                <th>دسته</th>
                <th>عنوان</th>
                <th>ارزش پیامد</th>
                <th>نرخ پایه در سال</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {draft.classes.map((row, index) => (
                <tr key={row.key}>
                  <td dir="ltr">{row.key}</td>
                  <td>
                    <input
                      required
                      value={row.label}
                      onChange={(e) => set({ classes: draft.classes.map((c, i) => (i === index ? { ...c, label: e.target.value } : c)) })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      required
                      min={0.1}
                      max={100}
                      step={0.1}
                      value={row.value}
                      onChange={(e) => set({ classes: draft.classes.map((c, i) => (i === index ? { ...c, value: +e.target.value } : c)) })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      required
                      min={0.001}
                      max={1000}
                      step={0.001}
                      value={row.prior_rate_per_year}
                      onChange={(e) =>
                        set({ classes: draft.classes.map((c, i) => (i === index ? { ...c, prior_rate_per_year: +e.target.value } : c)) })
                      }
                    />
                  </td>
                  <td>
                    {!BASE_KEYS.includes(row.key) && (
                      <button type="button" className="secondary" aria-label="حذف دسته" onClick={() => set({ classes: draft.classes.filter((_, i) => i !== index) })}>
                        <Trash2 size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!!missing.length && fallback && (
          <button
            type="button"
            className="secondary"
            onClick={() =>
              set({
                classes: [
                  ...draft.classes,
                  ...missing.map((label) => ({ key: `station:${label}`, label: `ایستگاه ${label}`, value: fallback.value, prior_rate_per_year: fallback.prior_rate_per_year })),
                ],
              })
            }
          >
            <Plus size={14} /> افزودن دسته برای برچسب‌های حساسیت: {missing.join("، ")}
          </button>
        )}
      </section>
      <section className="panel patrol-game-wide">
        <h3>مقادیر اختصاصی اهداف</h3>
        <p className="muted">برای هدف خاص ارزش یا نرخ دسته را جایگزین کنید یا بازدید آن را در هر برنامه و هر دور الزامی کنید. ذکر دلیل الزامی است.</p>
        <div className="risk-table-scroll">
          <table className="risk-breakdown">
            <thead>
              <tr>
                <th>هدف</th>
                <th>ارزش اختصاصی</th>
                <th>نرخ اختصاصی در سال</th>
                <th>بازدید الزامی</th>
                <th>دلیل</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {overrides.map((row, index) => (
                <tr key={index}>
                  <td>
                    <select required value={row.target_id} onChange={(e) => setOverride(index, { target_id: e.target.value })}>
                      <option value="">انتخاب هدف</option>
                      {targets.map((target) => (
                        <option key={target.id} value={target.id}>
                          {target.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0.1}
                      max={100}
                      step={0.1}
                      value={row.value ?? ""}
                      onChange={(e) => setOverride(index, { value: e.target.value === "" ? null : +e.target.value })}
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      min={0.001}
                      max={1000}
                      step={0.001}
                      value={row.prior_rate_per_year ?? ""}
                      onChange={(e) => setOverride(index, { prior_rate_per_year: e.target.value === "" ? null : +e.target.value })}
                    />
                  </td>
                  <td>
                    <input type="checkbox" checked={!!row.always_visit} onChange={(e) => setOverride(index, { always_visit: e.target.checked })} />
                  </td>
                  <td>
                    <input required minLength={3} value={row.note} onChange={(e) => setOverride(index, { note: e.target.value })} />
                  </td>
                  <td>
                    <button type="button" className="secondary" aria-label="حذف مقدار اختصاصی" onClick={() => set({ overrides: overrides.filter((_, i) => i !== index) })}>
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button
          type="button"
          className="secondary"
          onClick={() => set({ overrides: [...overrides, { target_id: "", value: null, prior_rate_per_year: null, always_visit: false, note: "" }] })}
        >
          <Plus size={14} /> افزودن مقدار اختصاصی
        </button>
      </section>
      <section className="panel">
        <h3>وزن شواهد در برآورد</h3>
        <div className="form-grid">
          {(Object.keys(WEIGHT_LABELS) as (keyof EventWeights)[]).map((key) => (
            <NumberField
              key={key}
              label={WEIGHT_LABELS[key]}
              value={draft.event_weights[key] ?? 0}
              min={0}
              max={10}
              step={0.1}
              onChange={(value) => set({ event_weights: { ...draft.event_weights, [key]: value } })}
            />
          ))}
        </div>
      </section>
      <section className="panel">
        <h3>بازدید زیرمجموعه ایستگاه‌ها و تأیید</h3>
        <label className="check-field">
          <input type="checkbox" checked={draft.allow_subset_tours} onChange={(e) => set({ allow_subset_tours: e.target.checked })} />
          اجازه بازدید زیرمجموعه بهینه ایستگاه‌ها در گشت پیاده (تصمیم هر مسیر جداگانه گرفته می‌شود)
        </label>
        <p className="muted">
          هر تغییر پارامتر تأیید قبلی را باطل می‌کند. تا تأیید مدیر حراست، برنامه‌ها با هشدار ساخته می‌شوند و هیچ مسیر پیاده‌ای زیرمجموعه
          نمی‌شود.
        </p>
        {approval && (
          <p>
            اثر انگشت پارامترها <code dir="ltr">{approval.fingerprint.slice(0, 16)}</code> ·{" "}
            {approval.approved ? `تأیید ${approval.approved_by} در ${approval.approved_at ? timeFa(approval.approved_at) : ""}` : "تأییدنشده"}
          </p>
        )}
        <div className="gis-actions">
          <button className="primary" disabled={busy || local === null}>
            ذخیره پارامترها
          </button>
          {local !== null && (
            <button type="button" className="secondary" onClick={() => setLocal(null)}>
              انصراف از تغییرات
            </button>
          )}
          <button type="button" className="secondary" disabled={busy || local !== null || approval?.approved} onClick={() => void approve()}>
            <BadgeCheck size={14} /> تأیید پارامترها توسط مدیر حراست
          </button>
        </div>
      </section>
    </form>
  );
}

function parseCsv(text: string): RiskEventInput[] {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const header = lines[0]?.split(",").map((cell) => cell.trim());
  if (!header || !header.includes("time") || !header.includes("source_ref")) throw new Error("سطر اول باید سرستون‌ها از جمله time و source_ref باشد");
  return lines.slice(1).map((line, row) => {
    const cells = line.split(",").map((cell) => cell.trim());
    const value = (key: string) => cells[header.indexOf(key)] ?? "";
    const category = value("category") as RiskEventInput["category"];
    if (!(category in CATEGORIES)) throw new Error(`دسته سطر ${fa(row + 2)} معتبر نیست`);
    const time = value("time");
    const lon = value("lon"), lat = value("lat"), weight = value("weight");
    return {
      time: /[zZ]|[+-]\d\d:\d\d$/.test(time) ? time : tehranInputISO(time.replace(" ", "T").slice(0, 16)),
      category,
      lon: lon ? +lon : null,
      lat: lat ? +lat : null,
      target_id: value("target_id") || null,
      weight: weight ? +weight : 1,
      source_ref: value("source_ref"),
      description: value("description") || "سابقه واردشده از فایل سازمان",
    };
  });
}

function Events({ act, busy }: { act: Act; busy: boolean }) {
  const client = useQueryClient();
  const targets = useTargets();
  const events = useQuery({ queryKey: ["patrol-game", "events"], queryFn: () => api<RiskEvent[]>("/intel/risk/events") });
  const [pending, setPending] = useState<RiskEventInput[]>([]);
  const [csv, setCsv] = useState("");
  const [error, setError] = useState("");
  const [form, setForm] = useState({ time: "", category: "theft" as RiskEventInput["category"], target_id: "", weight: 1, source_ref: "", description: "" });
  const submit = async () => {
    const result = await act(
      () => api<RiskEventImportResult>("/intel/risk/events", "POST", { events: pending }),
      "رخدادها در دفتر ثبت شدند",
    );
    if (result) {
      setPending([]);
      await client.invalidateQueries({ queryKey: ["patrol-game"] });
      await client.invalidateQueries({ queryKey: ["intel", "risk"] });
    }
  };
  return (
    <div className="patrol-game-grid">
      <section className="panel">
        <h3>ثبت رخداد تاریخی</h3>
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            setPending((rows) => [...rows, { ...form, time: tehranInputISO(form.time), target_id: form.target_id, lon: null, lat: null }]);
            setForm({ ...form, source_ref: "", description: "" });
          }}
        >
          <label className="field">
            زمان (تهران)
            <input type="datetime-local" required value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} />
          </label>
          <label className="field">
            نوع
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as RiskEventInput["category"] })}>
              {Object.entries(CATEGORIES).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            هدف
            <select required value={form.target_id} onChange={(e) => setForm({ ...form, target_id: e.target.value })}>
              <option value="">انتخاب هدف</option>
              {targets.map((target) => (
                <option key={target.id} value={target.id}>
                  {target.name}
                </option>
              ))}
            </select>
          </label>
          <NumberField label="وزن شاهد" value={form.weight} min={0.1} max={10} step={0.1} onChange={(weight) => setForm({ ...form, weight })} />
          <label className="field">
            شماره سند/پرونده (کلید یکتا)
            <input required value={form.source_ref} onChange={(e) => setForm({ ...form, source_ref: e.target.value })} />
          </label>
          <label className="field">
            شرح
            <input required minLength={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </label>
          <button className="secondary">
            <Plus size={14} /> افزودن به فهرست ورود
          </button>
        </form>
        <h3>ورود گروهی از فایل CSV</h3>
        <textarea
          rows={5}
          dir="ltr"
          value={csv}
          placeholder={"time,category,lon,lat,target_id,weight,source_ref,description\n2023-05-01 22:30,theft,,,FAC-001,1,HRS-1402-118,بریدن فنس"}
          onChange={(e) => setCsv(e.target.value)}
        />
        <button
          type="button"
          className="secondary"
          onClick={() => {
            try {
              setPending((rows) => [...rows, ...parseCsv(csv)]);
              setCsv("");
              setError("");
            } catch (reason) {
              setError((reason as Error).message);
            }
          }}
        >
          خواندن فایل
        </button>
        {error && <p className="flag">{error}</p>}
        {!!pending.length && (
          <>
            <p>
              {fa(pending.length)} رخداد آماده ثبت. ثبت در دفتر غیرقابل ویرایش است و شماره سند تکراری با محتوای متفاوت پذیرفته نمی‌شود.
            </p>
            <div className="gis-actions">
              <button className="primary" disabled={busy} onClick={() => void submit()}>
                ثبت در دفتر رخدادها
              </button>
              <button className="secondary" onClick={() => setPending([])}>
                پاک کردن فهرست
              </button>
            </div>
          </>
        )}
      </section>
      <section className="panel patrol-game-wide">
        <h3>شواهد مورد استفاده در برآورد ({fa(events.data?.length || 0)})</h3>
        {events.isError && <div className="error-banner">{(events.error as Error).message}</div>}
        <div className="risk-table-scroll">
          <table className="risk-breakdown">
            <thead>
              <tr>
                <th>زمان</th>
                <th>منبع</th>
                <th>نوع</th>
                <th>محل/هدف</th>
                <th>وزن</th>
                <th>مرجع</th>
              </tr>
            </thead>
            <tbody>
              {(events.data || []).slice(0, 300).map((event) => (
                <tr key={event.id}>
                  <td>{timeFa(event.time)}</td>
                  <td>{SOURCES[event.source] || event.source}</td>
                  <td>{CATEGORIES[event.category as RiskEventInput["category"]] || WEIGHT_LABELS[event.category as keyof EventWeights] || event.category}</td>
                  <td dir="ltr">{event.target_id || (event.lon != null && event.lat != null ? `${num(event.lon, 4)}, ${num(event.lat, 4)}` : "—")}</td>
                  <td>{num(event.weight, 2)}</td>
                  <td dir="ltr">{event.source_ref}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function RouteDecision({ route, act, busy, allowed }: { route: TourRoute; act: Act; busy: boolean; allowed: boolean }) {
  const client = useQueryClient();
  const [decision, setDecision] = useState<RouteCoverageInput>({
    coverage_mode: route.coverage_mode,
    stations_per_tour: route.stations_per_tour ?? null,
    subset_mode: route.subset_mode,
  });
  const [horizon, setHorizon] = useState(2);
  const [preview, setPreview] = useState<PatrolStrategy | null>(null);
  const total = (route.station_ids ?? []).length;
  const perTour = decision.stations_per_tour ?? Math.max(1, total - 1);
  return (
    <section className="panel">
      <h3>
        {route.name} <small className="muted">· {fa(total)} ایستگاه · نگهبان {route.guard_id}</small>
      </h3>
      <div className="form-grid">
        <label className="field">
          تصمیم پوشش
          <select
            value={decision.coverage_mode}
            onChange={(e) =>
              setDecision(
                e.target.value === "all"
                  ? { coverage_mode: "all", stations_per_tour: null, subset_mode: decision.subset_mode }
                  : { coverage_mode: "optimized", stations_per_tour: perTour, subset_mode: decision.subset_mode },
              )
            }
          >
            <option value="all">بازدید همه ایستگاه‌ها در هر دور</option>
            <option value="optimized" disabled={total < 2}>
              زیرمجموعه بهینه در هر دور
            </option>
          </select>
        </label>
        {decision.coverage_mode === "optimized" && (
          <>
            <NumberField
              label="تعداد ایستگاه هر دور"
              value={perTour}
              min={1}
              max={Math.max(1, total - 1)}
              step={1}
              onChange={(value) => setDecision({ ...decision, stations_per_tour: value })}
            />
            <label className="field">
              حالت اجرا
              <select value={decision.subset_mode} onChange={(e) => setDecision({ ...decision, subset_mode: e.target.value as RouteCoverageInput["subset_mode"] })}>
                <option value="shadow">سایه: فقط ثبت پیشنهاد، بازدید همه ایستگاه‌ها</option>
                <option value="active">فعال: اعمال زیرمجموعه پس از تأیید پارامترها</option>
              </select>
            </label>
          </>
        )}
      </div>
      {decision.coverage_mode === "optimized" && decision.subset_mode === "active" && !allowed && (
        <p className="flag">بازدید زیرمجموعه در پارامترهای سازمان مجاز نشده است؛ تا مجاز شدن، همه ایستگاه‌ها بازدید می‌شوند.</p>
      )}
      <div className="gis-actions">
        <button
          className="primary"
          disabled={busy}
          onClick={async () => {
            const saved = await act(() => api<TourRoute>(`/tour/routes/${route.id}/coverage`, "PUT", decision), "تصمیم پوشش مسیر ثبت شد");
            if (saved) await client.invalidateQueries({ queryKey: ["patrol-game", "routes"] });
          }}
        >
          ثبت تصمیم
        </button>
        <NumberField label="فاصله دورها (ساعت)" value={horizon} min={0.25} max={24} step={0.25} onChange={setHorizon} />
        <button
          className="secondary"
          disabled={busy}
          onClick={async () => {
            const query = new URLSearchParams({ horizon_hours: String(horizon), stations_per_tour: String(decision.coverage_mode === "optimized" ? perTour : total) });
            const result = await act(() => api<PatrolStrategy>(`/tour/routes/${route.id}/strategy?${query}`));
            if (result) setPreview(result);
          }}
        >
          پیش‌نمایش احتمال بازدید ایستگاه‌ها
        </button>
      </div>
      {preview && <StrategyView strategy={preview} />}
    </section>
  );
}

function Routes({ act, busy }: { act: Act; busy: boolean }) {
  const settings = useSettings();
  const routes = useQuery({ queryKey: ["patrol-game", "routes"], queryFn: () => api<TourRoute[]>("/tour/routes") });
  if (routes.isError) return <div className="error-banner">{(routes.error as Error).message}</div>;
  if (!routes.data) return <div className="panel empty">در حال دریافت مسیرها…</div>;
  return (
    <div className="patrol-game-routes">
      <p className="muted">
        حراست برای هر مسیر پیاده تصمیم می‌گیرد همه ایستگاه‌ها در هر دور بازدید شوند یا زیرمجموعه‌ای با احتمال بهینه. ایستگاه ابتدا/انتهای ثابت و
        ایستگاه‌های «بازدید الزامی» همیشه بازدید می‌شوند و انتخاب از بذر ذخیره‌شده هر دور قابل بازتولید است.
      </p>
      {!routes.data.length && <div className="panel empty">مسیر پیاده‌ای تعریف نشده است.</div>}
      {routes.data.map((route) => (
        <RouteDecision key={route.id} route={route} act={act} busy={busy} allowed={!!settings.data?.patrol_game?.allow_subset_tours} />
      ))}
    </div>
  );
}

function Preview() {
  const [stops, setStops] = useState(4);
  const [horizon, setHorizon] = useState(8);
  const [request, setRequest] = useState<{ stops: number; horizon: number } | null>(null);
  const strategy = useQuery({
    queryKey: ["patrol-game", "preview", request],
    queryFn: () => api<PatrolStrategy>(`/intel/patrol-strategy?stops=${request?.stops}&horizon_hours=${request?.horizon}`),
    enabled: request !== null,
  });
  return (
    <div className="patrol-game-routes">
      <form
        className="panel form-grid"
        onSubmit={(event) => {
          event.preventDefault();
          setRequest({ stops, horizon });
        }}
      >
        <NumberField label="مجموع توقف خودروهای شیفت" value={stops} min={1} max={200} step={1} onChange={setStops} />
        <NumberField label="طول شیفت (ساعت)" value={horizon} min={0.5} max={72} step={0.5} onChange={setHorizon} />
        <button className="primary">محاسبه راهبرد</button>
      </form>
      {strategy.isError && <div className="error-banner">{(strategy.error as Error).message}</div>}
      {strategy.isFetching && <div className="panel empty">در حال حل بازی…</div>}
      {strategy.data && <StrategyView strategy={strategy.data} />}
    </div>
  );
}
