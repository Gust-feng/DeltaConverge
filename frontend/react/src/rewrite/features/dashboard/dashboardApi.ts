import type { DashboardSummary } from "./types";

/**
 * 1:1 复刻 legacy/dashboard.js 的 dashboardCache：
 * - key = projectRoot || '__none__'
 * - TTL 60s，命中期间复用同一个 promise
 * - 失败时删除该 key 的缓存
 */
const DASHBOARD_CACHE_TTL_MS = 60 * 1000;

type CacheEntry = { ts: number; promise: Promise<DashboardSummary> };

const dashboardCache = new Map<string, CacheEntry>();

function cacheKey(projectRoot: string | null): string {
  return projectRoot || "__none__";
}

export function hasFreshDashboardCache(projectRoot: string | null): boolean {
  const cached = dashboardCache.get(cacheKey(projectRoot));
  return Boolean(cached && Date.now() - cached.ts < DASHBOARD_CACHE_TTL_MS);
}

async function fetchDashboardSummary(projectRoot: string | null): Promise<DashboardSummary> {
  const suffix = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
  const response = await fetch(`/api/v2/dashboard/summary${suffix}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as DashboardSummary;
}

export function loadDashboardSummary(projectRoot: string | null, options: { force?: boolean } = {}): Promise<DashboardSummary> {
  const key = cacheKey(projectRoot);
  const now = Date.now();
  const cached = dashboardCache.get(key);

  if (!options.force && cached && now - cached.ts < DASHBOARD_CACHE_TTL_MS) {
    return cached.promise;
  }

  const promise = fetchDashboardSummary(projectRoot);
  dashboardCache.set(key, { ts: now, promise });

  promise.catch(() => {
    const latest = dashboardCache.get(key);
    if (latest && latest.promise === promise) {
      dashboardCache.delete(key);
    }
  });

  return promise;
}
