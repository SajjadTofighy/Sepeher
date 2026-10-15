import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fa } from "../../api";
import type { Act } from "../../shared/lib/actions";
import { Badge } from "../../shared/ui/primitives";
import type {
  Data,
  PatrolPlan,
  PatrolPlanInput,
  RiskFactor,
} from "../../types";
import { tehranLocalInput as localInput, tehranTime as when, tehranInputISO } from "../../shared/lib/time";
import OperationalMap from "../command/OperationalMap";
import StrategyView from "../patrol-game/StrategyView";

const key = ["intel", "patrol-plans"] as const;
const factors = {
  incidents: "رخدادها",
  access: "دسترسی",
  staleness: "دیرکرد بازدید",
  exposure: "بدون سرنشین",
};
function rawValue(factor: RiskFactor) {
  if (
    factor.factor === "access" &&
    factor.raw &&
    typeof factor.raw === "object"
  ) {
    const raw = factor.raw as Record<string, unknown>;
    return ["road_distance_m", "village_distance_m", "heavy_vehicle_access"]
      .map((key, index) => {
        const value = raw[key];
        return `${["فاصله راه", "فاصله روستا", "دسترسی خودروی سنگین"][index]}: ${typeof value === "number" ? `${fa(value)} متر` : typeof value === "boolean" ? (value ? "دارد" : "ندارد") : String(value)}`;
      })
      .join(" · ");
  }
  return typeof factor.raw === "number"
    ? `${fa(Number(factor.raw.toFixed(3)))}${factor.factor === "staleness" ? " ساعت" : ""}`
    : String(factor.raw);
}

export default function PatrolPlanner({
  data,
  busy,
  act,
  theme,
}: {
  data: Data;
  busy: boolean;
  act: Act;
  theme: "dark" | "light";
}) {
  const client = useQueryClient();
  const plans = useQuery({
    queryKey: key,
    queryFn: ({ signal }) =>
      api<PatrolPlan[]>("/intel/patrol-plans", "GET", undefined, signal),
    refetchInterval: 3000,
  });
  const eligible = data.assets.filter(
    (a) => a.kind === "vehicle" && a.unit === "patrol",
  );
  const [start, setStart] = useState(() =>
    localInput(new Date(Date.now() + 3600000)),
  );
  const [end, setEnd] = useState(() =>
    localInput(new Date(Date.now() + 9 * 3600000)),
  );
  const [assetIds, setAssetIds] = useState<string[]>(() =>
    eligible
      .filter((a) => a.status !== "offline")
      .slice(0, 2)
      .map((a) => a.id),
  );
  const [stops, setStops] = useState(3),
    [selectedId, setSelectedId] = useState("");
  const rows = [...(plans.data || [])].reverse();
  const selected =
    rows.find((p) => p.id === selectedId) ||
    rows.find((p) => p.status === "draft") ||
    rows[0];
  const saveResult = async (plan: PatrolPlan) => {
    client.setQueryData<PatrolPlan[]>(key, (old) => [
      ...(old || []).filter((p) => p.id !== plan.id),
      plan,
    ]);
    setSelectedId(plan.id);
    await client.invalidateQueries({ queryKey: key });
  };
  return (
    <section className="patrol-planner patrol-planner-console">
      <header className="patrol-planner-head"><div><b>پیشنهاد برنامه گشت</b><small>راهبرد بهینه بازی امنیتی و برآورد بیزی ریسک · نیازمند تأیید اپراتور</small></div></header>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const payload: PatrolPlanInput = {
            shift_start: tehranInputISO(start),
            shift_end: tehranInputISO(end),
            asset_ids: assetIds,
            stops_per_patrol: stops,
          };
          const plan = await act(
            () => api<PatrolPlan>("/intel/patrol-plans", "POST", payload),
            "پیش‌نویس برنامه گشت آماده شد",
          );
          if (plan) await saveResult(plan);
        }}
      >
        <div className="form-grid">
          <label className="field">
            آغاز شیفت (تهران)
            <input
              type="datetime-local"
              required
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label className="field">
            پایان شیفت (تهران)
            <input
              type="datetime-local"
              required
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          <label className="field">
            ایستگاه برای هر گشت
            <input
              type="number"
              required
              min={1}
              max={50}
              value={stops}
              onChange={(e) => setStops(+e.target.value)}
            />
          </label>
        </div>
        <fieldset className="patrol-plan-assets">
          <legend>گشت‌های شیفت</legend>
          {eligible.map((asset) => (
            <label key={asset.id}>
              <input
                type="checkbox"
                checked={assetIds.includes(asset.id)}
                onChange={() =>
                  setAssetIds((ids) =>
                    ids.includes(asset.id)
                      ? ids.filter((id) => id !== asset.id)
                      : [...ids, asset.id],
                  )
                }
              />
              {asset.name}
              <Badge value={asset.status} />
            </label>
          ))}
        </fieldset>
        <button className="primary" disabled={busy || !assetIds.length}>
          ساخت پیش‌نویس برنامه
        </button>
      </form>
      {plans.isError && <p role="alert">دریافت برنامه‌ها ناموفق بود.</p>}
      {!!rows.length && (
        <label className="field">
          برنامه گشت
          <select
            value={selected?.id || ""}
            onChange={(e) => setSelectedId(e.target.value)}
          >
            {rows.map((plan) => (
              <option key={plan.id} value={plan.id}>
                {plan.id} ·{" "}
                {plan.status === "draft"
                  ? "پیش‌نویس"
                  : plan.status === "approved"
                    ? "تأییدشده"
                    : "کنارگذاشته‌شده"}
              </option>
            ))}
          </select>
        </label>
      )}
      {selected && (
        <div className="patrol-plan-preview">
          <div className="detail-tags">
            <Badge
              value={
                selected.status === "approved"
                  ? "confirmed"
                  : selected.status === "discarded"
                    ? "closed"
                    : "draft"
              }
            />
            <span dir="ltr">{selected.id}</span>
            <span>
              {when(selected.shift_start)} تا {when(selected.shift_end)}
            </span>
          </div>
          {selected.warnings.map((warning, index) => (
            <p key={index} className="muted">
              {warning}
            </p>
          ))}
          <p className="muted">
            مسیرها خطوط مستقیم و شماتیک‌اند؛ تأیید برنامه فقط مأموریت ایجاد
            می‌کند.
          </p>
          {selected.strategy && (
            <details className="patrol-plan-strategy">
              <summary>راهبرد بازی امنیتی و حساب احتمال انتخاب اهداف این برنامه</summary>
              <StrategyView strategy={selected.strategy} />
            </details>
          )}
          <div className="patrol-plan-map">
            <OperationalMap
              data={data}
              theme={theme}
              onAsset={() => {}}
              onIncident={() => {}}
              patrolPlan={selected}
            />
          </div>
          {selected.patrols.map((patrol) => (
            <section className="patrol-plan-route" key={patrol.asset_id}>
              <h3>
                {data.assets.find((a) => a.id === patrol.asset_id)?.name ||
                  patrol.asset_id}
              </h3>
              {!patrol.stops.length && <p>هدف اختصاص‌یافته ندارد.</p>}
              {patrol.stops.map((stop, index) => (
                <details key={stop.target_id} className="patrol-plan-stop">
                  <summary>
                    {fa(index + 1)}. {stop.name} · {when(stop.due_at)} · ریسک{" "}
                    {fa(Number(stop.score.toFixed(3)))}{" "}
                    {stop.mandatory && (
                      <span className="muted">· بازدید الزامی</span>
                    )}
                  </summary>
                  <div className="risk-table-scroll">
                    <table className="risk-breakdown">
                      <thead>
                        <tr>
                          <th>عامل</th>
                          <th>مقدار خام</th>
                          <th>نرمال‌شده</th>
                          <th>وزن</th>
                          <th>سهم</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stop.breakdown.map((factor) => (
                          <tr key={factor.factor}>
                            <td>{factors[factor.factor]}</td>
                            <td>{rawValue(factor)}</td>
                            <td>{fa(Number(factor.normalized.toFixed(3)))}</td>
                            <td>{fa(factor.weight)}</td>
                            <td>
                              {fa(Number(factor.contribution.toFixed(3)))}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <small>
                    منبع: <span dir="ltr">{stop.finding_id}</span>
                  </small>
                </details>
              ))}
            </section>
          ))}
          {selected.status === "draft" && (
            <div className="gis-actions">
              <button
                className="primary"
                disabled={busy}
                onClick={async () => {
                  const result = await act(
                    () =>
                      api<PatrolPlan>(
                        `/intel/patrol-plans/${selected.id}/approve`,
                        "POST",
                      ),
                    "برنامه تأیید و مأموریت‌ها ایجاد شدند",
                  );
                  if (result) await saveResult(result);
                }}
              >
                تأیید برنامه و ایجاد مأموریت
              </button>
              <button
                className="secondary"
                disabled={busy}
                onClick={async () => {
                  const result = await act(
                    () =>
                      api<PatrolPlan>(
                        `/intel/patrol-plans/${selected.id}/discard`,
                        "POST",
                      ),
                    "پیش‌نویس کنار گذاشته شد",
                  );
                  if (result) await saveResult(result);
                }}
              >
                کنارگذاشتن پیش‌نویس
              </button>
            </div>
          )}
          {selected.status === "approved" && (
            <p>مأموریت‌های ایجادشده: {selected.mission_ids.join("، ")}</p>
          )}
        </div>
      )}
    </section>
  );
}
