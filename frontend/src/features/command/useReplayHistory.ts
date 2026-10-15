import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../../api";
import type { Data, TrackBatch } from "../../types";

export const REPLAY_HOURS = 2;

// Replay reads history from the track API over a fixed window; the live picture keeps only a
// short trail and is never modified by playback.
export function useReplayHistory(active: boolean, data: Data | undefined) {
  const ids = useMemo(() => (data?.assets ?? []).map((a) => a.id), [data?.assets]);
  const history = useQuery({
    queryKey: ["replay", "tracks", ids.join(",")],
    enabled: active && ids.length > 0,
    staleTime: 60000,
    queryFn: ({ signal }) => {
      const until = new Date();
      const since = new Date(until.getTime() - REPLAY_HOURS * 3600000);
      const params = new URLSearchParams({ since: since.toISOString(), until: until.toISOString(), limit_per_asset: "2000" });
      ids.forEach((id) => params.append("asset_id", id));
      return api<TrackBatch>(`/tracks?${params}`, "GET", undefined, signal);
    },
  });
  return useMemo(() => {
    if (!active || !data || !history.data) return { data, truncated: false, loading: active && history.isPending };
    const tracks = history.data.tracks;
    return {
      data: { ...data, assets: data.assets.map((a) => ({ ...a, track: tracks[a.id] ?? [] })) },
      truncated: history.data.truncated,
      loading: false,
    };
  }, [active, data, history.data, history.isPending]);
}
