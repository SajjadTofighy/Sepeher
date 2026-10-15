import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../../api";
import type { ChangeSet, Data } from "../../types";
export const operationsKey = ["operations", "bootstrap"] as const;

type Keyed = { id: string };
const COLLECTIONS = ["assets", "incidents", "alerts", "missions", "commands"] as const;

function merge<T extends Keyed>(rows: T[], changed: T[], removed: string[] = [], newestFirst = false): T[] {
  const updates = new Map(changed.map((row) => [row.id, row]));
  const gone = new Set(removed);
  const kept = rows.filter((row) => !gone.has(row.id)).map((row) => updates.get(row.id) ?? row);
  const known = new Set(rows.map((row) => row.id));
  const added = changed.filter((row) => !known.has(row.id));
  return newestFirst ? [...added, ...kept] : [...kept, ...added];
}

export function applyChanges(data: Data, delta: ChangeSet): Data {
  // meta (snapshot cursor) is left alone: the polling loop keeps its own position.
  const next = { ...data } as Data;
  for (const kind of COLLECTIONS) {
    const rows = (data[kind] ?? []) as Keyed[];
    (next as unknown as Record<string, Keyed[]>)[kind] = merge(
      rows,
      (delta[kind] ?? []) as Keyed[],
      delta.removed?.[kind],
      kind === "incidents" || kind === "alerts",
    );
  }
  if (delta.summary) next.summary = delta.summary;
  return next;
}

// Snapshot once, then long-poll only what changed (cursor/resume). reset=true or an error reloads
// the snapshot; a slow periodic reload reconciles anything a long outage could have missed.
export function useOperations() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: operationsKey,
    queryFn: ({ signal }) => api<Data>("/bootstrap", "GET", undefined, signal),
    refetchInterval: 120000,
  });
  const cursor = query.data?.meta?.cursor;
  useEffect(() => {
    if (!cursor) return;
    const controller = new AbortController();
    let position = cursor;
    let stopped = false;
    (async () => {
      let backoff = 1000;
      while (!stopped) {
        try {
          const delta = await api<ChangeSet>(
            `/changes?cursor=${encodeURIComponent(position)}&wait=20`, "GET", undefined, controller.signal,
          );
          backoff = 1000;
          if (delta.reset) {
            await client.invalidateQueries({ queryKey: operationsKey });
            return; // the new snapshot carries a new cursor and restarts this loop
          }
          position = delta.cursor;
          client.setQueryData<Data>(operationsKey, (old) => (old ? applyChanges(old, delta) : old));
        } catch {
          if (stopped) return;
          await new Promise((resolve) => setTimeout(resolve, backoff));
          backoff = Math.min(backoff * 2, 30000);
        }
      }
    })();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [cursor, client]);
  return query;
}
