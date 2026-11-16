import { useEffect, useRef, useState } from "react";

import { hasFreshDashboardCache, loadDashboardSummary } from "./dashboardApi";
import type { DashboardSummary } from "./types";

type DashboardState = {
  key: string | null;
  summary: DashboardSummary | null;
  checking: boolean;
  failed: boolean;
};

function keyOf(projectRoot: string | null): string {
  return projectRoot || "__none__";
}

/**
 * 旧版进入仪表盘会调用 loadDashboardData()，项目切换时也会预取同一份数据。
 * 这里合并为一次 GET /api/v2/dashboard/summary，并保留 60s 缓存语义。
 */
export function useDashboardSummary(active: boolean, projectRoot: string | null, refreshToken = 0): {
  summary: DashboardSummary | null;
  checking: boolean;
  failed: boolean;
} {
  const [state, setState] = useState<DashboardState>({ key: null, summary: null, checking: false, failed: false });
  const lastToken = useRef(refreshToken);

  useEffect(() => {
    // 旧版启动时若已有项目路径会预取仪表盘数据；没有项目且未进入仪表盘时不请求。
    if (!active && !projectRoot) return;

    const key = keyOf(projectRoot);
    const force = refreshToken !== lastToken.current;
    lastToken.current = refreshToken;
    let cancelled = false;
    const fresh = !force && hasFreshDashboardCache(projectRoot);

    setState((previous) => {
      if (fresh) {
        return previous.key === key ? previous : { key, summary: null, checking: false, failed: false };
      }
      // 同一项目刷新时保留旧内容（旧版只把 Diff 状态改成 Checking...，不清空其它卡片）。
      // 切换项目时旧版同样保留旧数据直到新响应返回，因此这里不主动清空 summary。
      return { ...previous, key, checking: Boolean(projectRoot), failed: false };
    });

    void loadDashboardSummary(projectRoot, { force })
      .then((summary) => {
        if (cancelled) return;
        setState({ key, summary, checking: false, failed: false });
      })
      .catch(() => {
        if (cancelled) return;
        setState((previous) =>
          previous.key === key
            ? { ...previous, checking: false, failed: true }
            : { key, summary: null, checking: false, failed: true }
        );
      });

    return () => {
      cancelled = true;
    };
  }, [active, projectRoot, refreshToken]);

  const currentKey = keyOf(projectRoot);
  if (state.key !== currentKey) {
    return { summary: null, checking: false, failed: false };
  }
  return { summary: state.summary, checking: state.checking, failed: state.failed };
}
