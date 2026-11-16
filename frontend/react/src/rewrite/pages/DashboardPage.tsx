import { useEffect, useState } from "react";

import { IntentPanel } from "../features/intent/IntentPanel";
import { ProjectCard } from "../features/dashboard/ProjectCard";
import { ProviderCard } from "../features/dashboard/ProviderCard";
import { ScannerCard } from "../features/dashboard/ScannerCard";
import { SessionStatsCard } from "../features/dashboard/SessionStatsCard";
import { getDetectedLanguages } from "../features/dashboard/types";
import { useDashboardSummary } from "../features/dashboard/useDashboardSummary";
import { useAppStore } from "../state/appStore";

export function DashboardPage({ active }: { active: boolean }) {
  const projectRoot = useAppStore((state) => state.projectRoot);
  const setFolderPickerOpen = useAppStore((state) => state.setFolderPickerOpen);
  const setModelManagementOpen = useAppStore((state) => state.setModelManagementOpen);

  const [refreshToken, setRefreshToken] = useState(0);
  const { summary, checking, failed } = useDashboardSummary(active, projectRoot, refreshToken);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (event.type === "dc:reload-dashboard" || detail === "dashboard") {
        setRefreshToken((value) => value + 1);
      }
    };
    window.addEventListener("dc:reload-page", handler);
    window.addEventListener("dc:reload-dashboard", handler);
    return () => {
      window.removeEventListener("dc:reload-page", handler);
      window.removeEventListener("dc:reload-dashboard", handler);
    };
  }, []);

  // 旧版 index.html 的静态初值是“未选择”；JS 启动后才写入真实路径。
  const [pathText, setPathText] = useState("未选择");
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);

  useEffect(() => {
    setPathText(projectRoot || "未选择");
  }, [projectRoot]);

  useEffect(() => {
    if (summary) setHasLoadedOnce(true);
  }, [summary]);

  let diffText: string;
  if (!projectRoot) {
    diffText = active || hasLoadedOnce ? "-" : "未知";
  } else if (checking || (!summary && !failed)) {
    diffText = "Checking...";
  } else if (failed) {
    diffText = "Error checking diff";
  } else if (summary) {
    if (summary.diff_status?.error) {
      diffText = `Error: ${summary.diff_status.error}`;
    } else if (summary.diff_status?.has_working_changes || summary.diff_status?.has_staged_changes) {
      diffText = `Has Changes (${summary.diff_status.detected_mode || "unknown"})`;
    } else {
      diffText = "Clean (no changes)";
    }
  } else {
    diffText = "未知";
  }

  const detectedLanguages = getDetectedLanguages(summary);

  return (
    <div id="page-dashboard" className="page-view" style={{ display: active ? "block" : "none" }}>
      <div className="page-header" style={{ justifyContent: "space-between" }}>
        <div
          id="dashboard-header-container"
          style={{ display: "flex", alignItems: "center", padding: "0.5rem", borderRadius: "8px" }}
        >
          <h2>仪表盘</h2>
          <span id="dashboard-health-label" className="health-indicator" style={{ display: "none" }}>
            HEALTHY
          </span>
        </div>
      </div>

      <div className="dashboard-grid">
        <ProjectCard
          pathText={pathText}
          diffText={diffText}
          projectRoot={projectRoot}
          onSwitch={() => setFolderPickerOpen(true)}
        />
        <SessionStatsCard stats={summary?.session_stats} />
        <ProviderCard providers={summary?.providers} onConfigure={() => setModelManagementOpen(true)} />
        <ScannerCard scanners={summary?.scanners} detectedLanguages={detectedLanguages} />
      </div>

      <div
        className="intent-core-view"
        style={{ marginTop: "1.5rem", display: "flex", flexDirection: "column", minHeight: "500px" }}
      >
        <IntentPanel projectRoot={projectRoot} />
      </div>
    </div>
  );
}
