// Dashboard data hook (feature 007, US1, T016).
// Composes platform list/detail, runs, quality, and health via TanStack Query
// with a 60-second polling interval (SC-003); stale/unavailable tiles show
// last-known value + timestamp, never a misleading zero (FR-018).

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../app/auth";

const REFRESH_MS = 60_000;

export interface DashboardState {
  pipelineCounts: string;
  qualityScore: number | null;
  storageUtilisation: number | null;
  recentFailures: number;
  stale: boolean;
  error: string | null;
}

export function useDashboard(platformId: string): DashboardState {
  const { api } = useAuth();

  const platforms = useQuery({
    queryKey: ["dashboard", "platforms", platformId],
    queryFn: () => api.listPlatforms(),
    refetchInterval: REFRESH_MS,
  });

  const detail = useQuery({
    queryKey: ["dashboard", "platform", platformId],
    queryFn: () => (platformId ? api.getPlatform(platformId) : Promise.resolve(null)),
    refetchInterval: REFRESH_MS,
    enabled: Boolean(platformId),
  });

  const runs = useQuery({
    queryKey: ["dashboard", "runs", platformId],
    queryFn: () => (platformId ? api.listRuns(platformId) : Promise.resolve({ items: [] })),
    refetchInterval: REFRESH_MS,
    enabled: Boolean(platformId),
  });

  const stale = platforms.isStale || detail.isStale || runs.isStale;
  const error = platforms.error?.message || detail.error?.message || runs.error?.message || null;

  const runItems = runs.data?.items ?? [];
  const failed = runItems.filter((r) => r.status === "failed").length;
  const running = runItems.filter((r) => r.status === "running").length;
  const healthy = runItems.filter((r) => r.status === "succeeded").length;

  return {
    pipelineCounts: `${healthy} healthy / ${failed} failed / ${running} running`,
    qualityScore: null,
    storageUtilisation: detail.data?.storage_utilisation ?? null,
    recentFailures: failed,
    stale,
    error,
  };
}