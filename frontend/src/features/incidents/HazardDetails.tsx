import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, fa } from "../../api";
import type { HazardStatus, Incident } from "../../types";
import type { Act } from "../../shared/lib/actions";

export default function HazardDetails({
  incident,
  act,
  busy,
  onDraw,
}: {
  incident: Incident;
  act: Act;
  busy: boolean;
  onDraw: () => void;
}) {
  const client = useQueryClient();
  const hazard = useQuery({
    queryKey: ["intel", "hazard", incident.id],
    queryFn: ({ signal }) =>
      api<HazardStatus>(
        `/intel/hazard/${incident.id}`,
        "GET",
        undefined,
        signal,
      ),
    refetchInterval: 3000,
    enabled: !!incident.hazard_area,
  });
  const invalidate = () =>
    client.invalidateQueries({ queryKey: ["intel", "hazard", incident.id] });
  return (
    <section className="detail-section hazard-details">
      <h3>محدوده خطر حادثه</h3>
      {incident.hazard_area && (
        <p>
          {incident.hazard_area.type === "circle"
            ? `دایره با شعاع ${fa(incident.hazard_area.radius_m)} متر`
            : `چندضلعی با ${fa(incident.hazard_area.points.length)} نقطه`}
        </p>
      )}
      {incident.status !== "closed" && (
        <div className="gis-actions">
          <button className="secondary" disabled={busy} onClick={onDraw}>
            ترسیم محدوده خطر
          </button>
          {incident.hazard_area && (
            <button
              className="secondary"
              disabled={busy}
              onClick={async () => {
                const result = await act(
                  () => api(`/incidents/${incident.id}/hazard-area`, "DELETE"),
                  "محدوده خطر حذف شد",
                );
                if (result) await invalidate();
              }}
            >
              حذف محدوده خطر
            </button>
          )}
        </div>
      )}
      {incident.hazard_area &&
        (hazard.isError ? (
          <p role="alert">دریافت وضعیت محدوده خطر ناموفق بود.</p>
        ) : hazard.isPending ? (
          <p>در حال دریافت…</p>
        ) : (
          <>
            <h4>داخل محدوده</h4>
            <p>
              {hazard.data.inside.map((a) => a.name).join("، ") ||
                "تجهیزی داخل محدوده نیست."}
            </p>
            <h4>در حال نزدیک‌شدن</h4>
            {hazard.data.approaching.map((a) => (
              <p key={a.asset_id}>
                {a.name} · {fa(a.distance_to_boundary_km)} کیلومتر تا مرز{" "}
                {a.finding_id && <span dir="ltr">· {a.finding_id}</span>}
              </p>
            ))}
            {!hazard.data.approaching.length && (
              <p>تجهیزی در حال نزدیک‌شدن نیست.</p>
            )}
            <h4>پیشنهاد کنترل دسترسی</h4>
            <p className="muted">
              ETA تا مرز یا نقطه دسترسی تخمینی است. ارجاع، همان گشت پرونده را به
              محل حادثه می‌فرستد.
            </p>
            {incident.status === "detected" && (
              <p className="muted">برای ارجاع ابتدا حادثه را تأیید کنید.</p>
            )}
            {hazard.data.closure_suggestions.map((a, index) => (
              <div className="hazard-suggestion" key={`${a.asset_id}-${index}`}>
                <span>
                  {a.name}
                  {a.access_point_index != null
                    ? ` · دسترسی ${fa(a.access_point_index + 1)}`
                    : ""}{" "}
                  · {a.eta_label} {fa(a.eta_minutes)} دقیقه
                </span>
                <button
                  className="secondary"
                  disabled={busy || incident.status !== "confirmed"}
                  onClick={async () => {
                    const result = await act(
                      () =>
                        api(`/incidents/${incident.id}/transition`, "POST", {
                          status: "assigned",
                          asset_id: a.asset_id,
                        }),
                      "گشت به پرونده ارجاع شد",
                    );
                    if (result) await invalidate();
                  }}
                >
                  ارجاع
                </button>
              </div>
            ))}
            {!hazard.data.closure_suggestions.length && (
              <p>گشت آزاد در دسترس نیست.</p>
            )}
          </>
        ))}
    </section>
  );
}
