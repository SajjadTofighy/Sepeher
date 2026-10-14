import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import type { SafetyStatus } from "../../types";

export const safetyKey = ["intel", "safety"] as const;
export function usePatrolSafety() {
  return useQuery({
    queryKey: safetyKey,
    queryFn: ({ signal }) =>
      api<SafetyStatus>("/intel/safety", "GET", undefined, signal),
    refetchInterval: 3000,
  });
}
