import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, fa } from "../../api";
import { operationsKey } from "../../shared/api/useOperations";
import { Badge, Modal } from "../../shared/ui/primitives";
import type { Data, SafetyEpisode } from "../../types";
import { safetyKey, usePatrolSafety } from "./usePatrolSafety";

export default function PatrolSafetyList({ data }: { data: Data }) {
  const query = usePatrolSafety();
  const client = useQueryClient();
  const [now, setNow] = useState(Date.now());
  const [selected, setSelected] = useState<SafetyEpisode | null>(null);
  const [note, setNote] = useState("");
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const confirmation = useMutation({
    mutationFn: (assetId: string) =>
      api(`/intel/safety/${assetId}/confirm`, "POST", { note }),
    onSuccess: async () => {
      setSelected(null);
      setNote("");
      await Promise.all([
        client.invalidateQueries({ queryKey: safetyKey }),
        client.invalidateQueries({ queryKey: operationsKey }),
        client.invalidateQueries({ queryKey: ["intel", "findings"] }),
      ]);
    },
  });
  const episodes =
    query.data?.episodes.filter(
      (e) => e.state === "check_pending" || e.state === "escalated",
    ) || [];
  return (
    <section className="patrol-safety-panel" aria-label="پایش ایمنی گشت">
      <h3>
        پایش ایمنی گشت <span>{fa(episodes.length)}</span>
      </h3>
      {query.isError ? (
        <p role="alert">دریافت وضعیت ایمنی ناموفق بود.</p>
      ) : (
        <div className="patrol-safety-list">
          {episodes.map((episode) => {
            const seconds = episode.deadline
              ? Math.max(
                  0,
                  Math.ceil((Date.parse(episode.deadline) - now) / 1000),
                )
              : 0;
            return (
              <div className="patrol-safety-row" key={episode.asset_id}>
                <b>
                  {data.assets.find((a) => a.id === episode.asset_id)?.name ||
                    episode.asset_id}
                </b>
                <Badge value={episode.state} />
                <p>{episode.reason}</p>
                {episode.state === "check_pending" && (
                  <>
                    <span aria-label="زمان باقی‌مانده">
                      {fa(Math.floor(seconds / 60))}:{fa(seconds % 60)} تا پایان
                      مهلت
                    </span>
                    <button
                      className="secondary"
                      onClick={() => {
                        confirmation.reset();
                        setNote("");
                        setSelected(episode);
                      }}
                    >
                      تأیید سلامت گشت
                    </button>
                  </>
                )}
              </div>
            );
          })}
          {!episodes.length && (
            <p>
              {query.isPending
                ? "در حال دریافت وضعیت…"
                : "گشتی در انتظار تأیید سلامت نیست."}
            </p>
          )}
        </div>
      )}
      {selected && (
        <Modal title="تأیید سلامت گشت" onClose={() => setSelected(null)}>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              confirmation.mutate(selected.asset_id);
            }}
          >
            <p>
              {data.assets.find((a) => a.id === selected.asset_id)?.name} ·{" "}
              {selected.reason}
            </p>
            <label className="field">
              یادداشت تأیید (اختیاری)
              <textarea
                value={note}
                maxLength={1000}
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
            {confirmation.isError && (
              <p role="alert">{confirmation.error.message}</p>
            )}
            <button className="primary" disabled={confirmation.isPending}>
              ثبت تأیید سلامت
            </button>
          </form>
        </Modal>
      )}
    </section>
  );
}
