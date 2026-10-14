import {
  Camera,
  Check,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  Play,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, fa } from "../../api";
import type {
  AssistantAnswer,
  Data,
  Incident,
  NearbyPatrol,
} from "../../types";

// Design appendix: the five-minute presentation, driven through the real APIs.
const STORY_ASSET = "AST-S73";
type Phase = 1 | 2 | 3;
const steps: { title: string; phase: Phase; cta: string }[] = [
  { title: "وضعیت عادی", phase: 1, cta: "ورود خودروی بدون مجوز" },
  { title: "نقض سیاست", phase: 1, cta: "در انتظار تشخیص…" },
  { title: "فرماندهی حادثه", phase: 2, cta: "تأیید و تمرکز روی حادثه" },
  { title: "ارجاع گشت", phase: 2, cta: "اعزام گشت پیشنهادی" },
  { title: "دوربین و توضیح حادثه", phase: 3, cta: "نمایش نقشه راه فاز ۳" },
  { title: "خاتمه حادثه", phase: 2, cta: "ثبت حضور و خاتمه" },
  { title: "بازپخش", phase: 1, cta: "بازپخش وضعیت منطقه" },
];
const phaseName: Record<Phase, string> = {
  1: "فاز ۱",
  2: "فاز ۲",
  3: "نقشه راه · فاز ۳",
};

// The map sits below the KPI row; keep it on screen while presenting.
const showMap = () =>
  document
    .querySelector(".map-card")
    ?.scrollIntoView({ behavior: "smooth", block: "start" });

function clock(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  return `${fa(Math.floor(s / 60))}:${fa(String(s % 60).padStart(2, "0"))}`;
}

export default function DemoTour({
  data,
  refresh,
  focus,
  go,
  replay,
  close,
}: {
  data: Data;
  refresh: () => Promise<unknown>;
  focus: (i: Incident | null) => void;
  go: (page: string) => void;
  replay: () => void;
  close: () => void;
}) {
  const [step, setStep] = useState(0),
    [done, setDone] = useState<boolean[]>(steps.map(() => false)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [startedAt, setStartedAt] = useState(""),
    [patrol, setPatrol] = useState<NearbyPatrol | null>(null),
    [insight, setInsight] = useState("");
  const incident = data.incidents.find(
    (i) =>
      i.asset_id === STORY_ASSET &&
      !!startedAt &&
      Date.parse(i.created_at) >= Date.parse(startedAt),
  );
  const vehicle = data.assets.find((a) => a.id === STORY_ASSET);
  const dispatched = incident?.assigned_to
    ? data.assets.find((a) => a.id === incident.assigned_to)
    : undefined;
  const waiting =
    (step === 1 && done[0] && !incident) ||
    (step === 3 && done[3] && !incident?.arrived_at);
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  useEffect(() => {
    const t = setTimeout(showMap, 250);
    return () => clearTimeout(t);
  }, []);

  // Poll faster while the story waits on the engine or a moving patrol.
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(() => void refreshRef.current(), 1200);
    return () => clearInterval(t);
  }, [waiting]);
  useEffect(() => {
    if (step === 1 && incident && !done[1]) {
      setDone((d) => d.map((v, k) => (k === 1 ? true : v)));
      focus(incident);
    }
  }, [step, incident?.id]);

  const mark = (k: number) => setDone((d) => d.map((v, j) => (j === k ? true : v)));
  const transition = (status: string, extra: object = {}) =>
    api(`/incidents/${incident!.id}/transition`, "POST", { status, ...extra });

  const run = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      if (step === 0) {
        go("command");
        focus(null);
        setTimeout(showMap, 80);
        setStartedAt(new Date(Date.now() - 2000).toISOString());
        await api("/demo/story", "POST");
        mark(0);
        setStep(1);
      } else if (step === 2 && incident) {
        if (incident.status === "detected") await transition("confirmed");
        const rows = await api<NearbyPatrol[]>(`/incidents/${incident.id}/nearby`);
        setPatrol(rows[0] || null);
        focus(incident);
        setTimeout(showMap, 80);
        mark(2);
      } else if (step === 3 && incident && patrol) {
        if (incident.status === "confirmed")
          await transition("assigned", { asset_id: patrol.asset_id });
        await transition("en_route");
        mark(3);
      } else if (step === 4 && incident) {
        const r = await api<AssistantAnswer>("/assistant", "POST", {
          question: `چرا حادثه ${incident.id.slice(4)} بحرانی شده است؟`,
        });
        setInsight(r.answer);
        mark(4);
      } else if (step === 5 && incident) {
        if (incident.status === "en_route") await transition("on_scene");
        await transition("closed", {
          note: "بازرسی محل انجام شد؛ خودرو متوقف و موضوع به حراست گزارش شد (نمایشی).",
        });
        mark(5);
      } else if (step === 6) {
        replay();
        mark(6);
      }
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [step, incident, patrol]);

  const canRun =
    !busy &&
    !done[step] &&
    (step === 0 ||
      step === 6 ||
      (step === 2 && !!incident) ||
      (step === 3 && !!patrol) ||
      (step >= 4 && !!incident));
  const next = () => setStep((s) => Math.min(steps.length - 1, s + 1));
  const last = step === steps.length - 1;
  const primary = () => {
    if (waiting) return;
    if (done[step]) return last ? close() : next();
    if (canRun) void run();
  };

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input,textarea,select,dialog")) return;
      if (e.key === "Escape") close();
      if (e.key === "ArrowLeft" || e.key === " ") {
        e.preventDefault();
        primary();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  const cycle = (label: string) => {
    const hit = incident?.timeline.find((e) => e.action.startsWith(label));
    return hit && incident
      ? clock((Date.parse(hit.time) - Date.parse(incident.created_at)) / 1000)
      : "—";
  };

  const body = [
    <>
      <p>
        <b>{fa(data.summary.online)}</b> گشت و نیروی برخط،{" "}
        <b>{fa(data.zones.length)}</b> محدوده حفاظت‌شده و{" "}
        <b>{fa(data.summary.active_policies)}</b> سیاست فعال روی یک نقشه. گشت‌ها
        زنده حرکت می‌کنند؛ سرعت کنار نام هر خودرو دیده می‌شود.
      </p>
    </>,
    incident ? (
      <p>
        موتور سیاست ورود را تشخیص داد و پرونده <b dir="ltr">{incident.id}</b>{" "}
        را با سطح <b className="hot">{incident.severity === "critical" ? "بحرانی" : "زیاد"}</b>{" "}
        ساخت. محدوده قرمز شد. هیچ هشداری در کد نوشته نشده؛ این خروجی سیاست{" "}
        <b dir="ltr">{incident.policy_id}</b> است.
      </p>
    ) : (
      <p>
        {vehicle?.name || "خودروی سازمانی ۷۳"} ساعت <b>۲۳:۱۰</b> بدون مجوز تردد
        شبانه به سمت «حریم تأسیسات شرقی» می‌رود
        {vehicle ? ` · ${fa(Math.round(vehicle.speed))} کیلومتر بر ساعت` : ""}.
        <span className="tour-wait">
          <LoaderCircle size={14} className="spin" /> موتور سیاست در حال پایش…
        </span>
      </p>
    ),
    patrol ? (
      <p>
        نقشه روی محل متمرکز شد و نزدیک‌ترین گشت‌ها با خط‌چین نمایش داده می‌شوند.
        پیشنهاد سامانه: <b>{patrol.name}</b> با زمان رسیدن حدود{" "}
        <b>{fa(Math.round(patrol.eta_minutes))} دقیقه</b>
        <small> (تخمین از فاصله مستقیم {fa(patrol.distance_km)} کیلومتر)</small>.
      </p>
    ) : (
      <p>
        اپراتور هشدار را تأیید می‌کند. سامانه وارد «حالت فرماندهی حادثه» می‌شود:
        تمرکز نقشه، محدوده حادثه و گشت‌های نزدیک.
      </p>
    ),
    dispatched ? (
      <p>
        <b>{dispatched.name}</b>{" "}
        {incident?.arrived_at ? (
          <>به محل رسید؛ رسیدن از موقعیت ردیاب ثبت شد.</>
        ) : (
          <>
            در مسیر محل حادثه است · {fa(Math.round(dispatched.speed))} کیلومتر
            بر ساعت
            <span className="tour-wait">
              <LoaderCircle size={14} className="spin" /> حرکت روی نقشه (زمان
              فشرده‌شده برای نمایش)
            </span>
          </>
        )}
      </p>
    ) : (
      <p>
        فرمانده {patrol?.name || "گشت پیشنهادی"} را ارجاع می‌دهد و حرکت آن تا محل
        روی نقشه دیده می‌شود.
      </p>
    ),
    <>
      <div className="tour-roadmap">
        <div className="tour-camera">
          <Camera size={18} />
          <span>C-42 · تأیید تصویری</span>
          <small>اتصال ONVIF در فاز ۳</small>
        </div>
        <div className="tour-insight">
          <Sparkles size={16} />
          <p>
            {insight ||
              "علت حادثه از رکوردهای سامانه و قاعده فعال‌شده توضیح داده می‌شود؛ بدون مدل زبانی و بدون اختیار صدور فرمان."}
          </p>
        </div>
      </div>
    </>,
    incident?.status === "closed" ? (
      <div className="tour-metrics">
        {[
          ["تا تأیید", "تأیید حادثه"],
          ["تا اعزام", "ارجاع به گشت"],
          ["تا حضور", "حضور در محل"],
          ["تا خاتمه", "خاتمه حادثه"],
        ].map(([n, l]) => (
          <div key={n}>
            <small>{n}</small>
            <b dir="ltr">{cycle(l)}</b>
          </div>
        ))}
      </div>
    ) : (
      <p>
        گشت حضور را ثبت می‌کند و پرونده با گزارش خاتمه بسته می‌شود. خط زمانی و
        زمان‌های واکنش خودکار محاسبه می‌شوند.
      </p>
    ),
    <p>
      مدیر وضعیت منطقه را در بازه وقوع حادثه بازپخش می‌کند. همه فرمان‌ها و
      اقدامات این نمایش در مرکز سوابق با زنجیره رمزنگاری ثبت شده‌اند.
    </p>,
  ][step];

  const label = waiting
    ? "در جریان…"
    : done[step]
      ? last
        ? "پایان نمایش"
        : "مرحله بعد"
      : steps[step].cta;

  return (
    <section className="demo-tour" aria-label="تور نمایش پنج‌دقیقه‌ای">
      <header>
        <div>
          <span className="eyebrow">LIVE DEMO · ۵ دقیقه</span>
          <h2>
            <span className="tour-index">{fa(step + 1)}</span>
            {steps[step].title}
            <span className={`phase-chip p${steps[step].phase}`}>
              {phaseName[steps[step].phase]}
            </span>
          </h2>
        </div>
        <button className="tour-close" aria-label="بستن تور" onClick={close}>
          <X size={17} />
        </button>
      </header>
      <ol className="tour-rail">
        {steps.map((s, k) => (
          <li
            key={s.title}
            className={`${k === step ? "current" : ""} ${done[k] ? "done" : ""} p${s.phase}`}
          >
            <button
              aria-label={s.title}
              disabled={k > step && !done[k - 1]}
              onClick={() => setStep(k)}
            >
              {done[k] ? <Check size={11} /> : fa(k + 1)}
            </button>
          </li>
        ))}
      </ol>
      <div className="tour-body">{body}</div>
      {error && <p className="tour-error">{error}</p>}
      <footer>
        <button
          className="secondary"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
        >
          <ChevronRight size={16} /> قبلی
        </button>
        <span className="tour-hint">Space یا ← برای ادامه</span>
        <button
          className="primary"
          disabled={busy || waiting || (!done[step] && !canRun)}
          onClick={primary}
        >
          {busy || waiting ? (
            <LoaderCircle size={16} className="spin" />
          ) : done[step] ? (
            <ChevronLeft size={16} />
          ) : (
            <Play size={15} />
          )}
          {label}
        </button>
      </footer>
    </section>
  );
}
