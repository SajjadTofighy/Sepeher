import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import type { Data } from "../../types";
export const operationsKey = ["operations", "bootstrap"] as const;
export function useOperations() {
  return useQuery({
    queryKey: operationsKey,
    queryFn: ({ signal }) => api<Data>("/bootstrap", "GET", undefined, signal),
    refetchInterval: 3000,
  });
}
