import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, fa, timeFa } from "../../api";
import type { PatrolStrategy, RuntimeSettings, StrategyTarget } from "../../types";

export const MODEL_LABELS: Record<PatrolStrategy["model"], string> = {
  stackelberg: "تعادل استکلبرگ قوی (مهاجم کاملاً منطقی)",
  quantal: "پاسخ کوانتالی (مهاجم با عقلانیت محدود)",
  weighted: "نمونه‌گیری وزن‌دار قدیمی (فقط برای مقایسه)",
};
const BASELINES: Record<string, string> = {
  uniform: "پوشش یکنواخت",
  proportional: "پوشش متناسب با ریسک (روش قبلی)",
  stackelberg: "راهبرد بهینه استکلبرگ",
};

export const num = (value: number, digits = 3) => fa(Number(value.toFixed(digits)));
export const pct = (value: number) => {
  const percent = value * 100;
  // Small attempt probabilities stay visible instead of rounding to zero.
  return `${fa(Number(percent > 0 && percent < 1 ? percent.toPrecision(2) : percent.toFixed(1)))}٪`;
};

export function useClassLabels() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<RuntimeSettings>("/settings") });
  const labels = Object.fromEntries((settings.data?.patrol_game?.classes || []).map((c) => [c.key, c.label]));
  return (key: string) => labels[key] || key.replace(/^station:/, "ایستگاه ");
}

function Row({ target, classLabel }: { target: StrategyTarget; classLabel: (key: string) => string }) {
  const b = target.bayes;
  return (
    <tr className={target.selected ? "strategy-selected" : ""}>
      <td>
        <b>{target.name}</b>
        <small dir="ltr">{target.id}</small>
      </td>
      <td>{classLabel(target.target_class)}</td>
      <td>{num(target.value, 1)}</td>
      <td title={`Gamma(${num(b.shape)}, ${num(b.rate)}) · ${fa((b.event_ids || []).length)} شاهد`}>
        {num(b.mean, 2)} <small>[{num(b.lower, 2)}–{num(b.upper, 2)}]</small>
      </td>
      <td>{num(b.weighted_events, 2)}</td>
      <td>{pct(target.attempt_probability)}</td>
      <td>{pct(target.detection)}</td>
      <td>
        <span className="strategy-bar" aria-label={pct(target.coverage)}>
          <i style={{ inlineSize: `${Math.min(100, target.coverage * 100)}%` }} />
        </span>
        {pct(target.coverage)}
      </td>
      <td>{pct(target.attack_probability)}</td>
      <td>
        {target.mandatory ? "الزامی" : target.selected ? "انتخاب‌شده" : "—"}
      </td>
    </tr>
  );
}

export default function StrategyView({ strategy }: { strategy: PatrolStrategy }) {
  const classLabel = useClassLabels();
  const [all, setAll] = useState(false);
  const sorted = [...strategy.targets].sort((a, b) => b.coverage - a.coverage);
  const relevant = sorted.filter((t) => t.coverage > 0 || t.selected || t.attack_probability > 0.001);
  const targets = all || relevant.length === sorted.length ? sorted : relevant;
  const loss = strategy.outcome.expected_loss;
  return (
    <div className="strategy-view">
      <div className="strategy-summary">
        <article>
          <small>مدل</small>
          <b>{MODEL_LABELS[strategy.model]}</b>
          <p>نمایه تهدید {num(strategy.threat_profile, 2)} · منابع {num(strategy.resources, 2)} · افق {num(strategy.horizon_hours, 1)} ساعت</p>
        </article>
        <article>
          <small>زیان مورد انتظار (مقیاس ارزش سازمان)</small>
          <b>{num(loss, 3)}</b>
          <p>
            {Object.entries(strategy.baselines).map(([key, value]) => (
              <span key={key}>
                {BASELINES[key] || key}: {num(value.expected_loss, 3)}
                <br />
              </span>
            ))}
          </p>
        </article>
        <article>
          <small>بهبود نسبت به مبنا</small>
          <b>{strategy.improvement_vs_uniform == null ? "—" : pct(strategy.improvement_vs_uniform)}</b>
          <p>
            نسبت به یکنواخت؛ نسبت به روش قبلی{" "}
            {strategy.improvement_vs_proportional == null ? "—" : pct(strategy.improvement_vs_proportional)}
          </p>
        </article>
        <article>
          <small>پیش‌بینی‌ناپذیری (آنتروپی نرمال)</small>
          <b>{num(strategy.entropy, 3)}</b>
          <p>۱ یعنی کمترین الگوی قابل پیش‌بینی</p>
        </article>
        <article className={strategy.parameters_approved ? "" : "flag"}>
          <small>پارامترهای سازمان</small>
          <b>{strategy.parameters_approved ? "تأییدشده" : "تأییدنشده"}</b>
          <p>
            <code dir="ltr">{strategy.parameters_fingerprint.slice(0, 16)}</code>
            {strategy.approved_by && (
              <>
                <br />
                {strategy.approved_by} · {strategy.approved_at ? timeFa(strategy.approved_at) : ""}
              </>
            )}
          </p>
        </article>
      </div>
      {strategy.warnings.map((warning) => (
        <p key={warning} className="flag">
          {warning}
        </p>
      ))}
      {strategy.conformity && (
        <p className="muted">
          انطباق {fa(strategy.conformity.plans)} برنامه تأییدشده با احتمال‌های برنامه‌ریزی‌شده: آماره χ²{" "}
          {num(strategy.conformity.chi_square, 2)} با {fa(strategy.conformity.degrees_of_freedom)} درجه آزادی · بیشترین
          انحراف استاندارد {num(strategy.conformity.max_standardized_deviation, 2)}
        </p>
      )}
      <div className="risk-table-scroll">
        <table className="risk-breakdown strategy-table">
          <thead>
            <tr>
              <th>هدف</th>
              <th>دسته</th>
              <th>ارزش</th>
              <th>نرخ پسین در سال [بازه باور]</th>
              <th>شواهد وزن‌دار</th>
              <th>احتمال اقدام در افق</th>
              <th>احتمال کشف با یک بازدید</th>
              <th>احتمال پوشش</th>
              <th>احتمال انتخاب مهاجم</th>
              <th>وضعیت</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((target) => (
              <Row key={target.id} target={target} classLabel={classLabel} />
            ))}
          </tbody>
        </table>
      </div>
      {relevant.length < sorted.length && (
        <button type="button" className="secondary" onClick={() => setAll((value) => !value)}>
          {all ? "فقط اهداف دارای پوشش" : `نمایش همه ${fa(sorted.length)} هدف (${fa(sorted.length - relevant.length)} هدف بدون پوشش)`}
        </button>
      )}
      <p className="muted">
        خروجی فقط پیشنهادی است و هیچ فرمانی ارسال نمی‌کند؛ احتمال پوشش هر هدف دقیقاً با نمونه‌گیری شانه‌ای رعایت
        می‌شود و مسیرها نیازمند تأیید انسانی‌اند.
      </p>
    </div>
  );
}
