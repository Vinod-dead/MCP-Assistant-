"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
/** GET helper: `useApi(["servers"], "/api/servers", { refetchInterval: 5000 })` */
export function useApi<T = any>(key: unknown[], path: string, opts: { refetchInterval?: number; enabled?: boolean } = {}) {
  return useQuery<T>({ queryKey: key, queryFn: () => api.get<T>(path), ...opts });
}
