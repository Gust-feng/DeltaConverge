import { Fragment, useEffect } from "react";
import type { ReactElement } from "react";

import { HistoryDrawer } from "./components/HistoryDrawer";
import { FolderPickerModal } from "./components/FolderPickerModal";
import { ModelManagementModal } from "./components/ModelManagementModal";
import { Icon } from "./components/Icon";
import { getToolsRaw } from "./lib/api";
import { refreshSavedModels } from "./state/modelOptions";
import { closeHelpDialog, closeConfirmDialog } from "./lib/dialogs";
import { ConfigPage } from "./pages/ConfigPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DiffPage } from "./pages/DiffPage";
import { ReviewPage } from "./pages/ReviewPage";
import { RuleGrowthPage } from "./pages/RuleGrowthPage";
import type { ActivePage } from "./types";
import { useAppStore } from "./state/appStore";

const PAGE_TITLES: Record<ActivePage, string> = {
  dashboard: "仪表盘 - DeltaConverge",
  review: "代码审查 - DeltaConverge",
  diff: "代码变更 - DeltaConverge",
  config: "设置 - DeltaConverge",
  "rule-growth": "规则优化 - DeltaConverge",
};

export default function App() {
  const activePage = useAppStore((s) => s.activePage);
  const layoutState = useAppStore((s) => s.layoutState);
  const setActivePage = useAppStore((s) => s.setActivePage);
  const toggleHistoryDrawer = useAppStore((s) => s.toggleHistoryDrawer);
  const setHistoryDrawerOpen = useAppStore((s) => s.setHistoryDrawerOpen);
  const setModelManagementOpen = useAppStore((s) => s.setModelManagementOpen);
  const setFolderPickerOpen = useAppStore((s) => s.setFolderPickerOpen);

  // 旧版 switchPage 每次点击导航都会重新执行页面 loader（含重复点击当前页）。
  const navigate = (page: ActivePage) => {
    const current = useAppStore.getState().activePage;
    setActivePage(page);
    if (current !== page) return;
    if (page === "review" || page === "diff") {
      window.dispatchEvent(new CustomEvent("dc:refresh-diff-analysis"));
      return;
    }
    window.dispatchEvent(new CustomEvent("dc:reload-page", { detail: page }));
  };

  useEffect(() => {
    document.title = PAGE_TITLES[activePage] ?? "DeltaConverge";
  }, [activePage]);

  useEffect(() => {
    let cancelled = false;

    const loadOptions = async (attempt: number): Promise<void> => {
      const store = useAppStore.getState();
      if (attempt === 0) store.setOptionsState(true, false);
      try {
        const [modelResult, toolResult] = await Promise.allSettled([refreshSavedModels(), getToolsRaw()]);
        if (cancelled) return;
        if (toolResult.status === "fulfilled") {
          const tools = toolResult.value.map((tool) => ({
            name: tool.name, description: tool.description, default: Boolean(tool.is_default),
          }));
          store.setTools(tools);
          store.setSelectedTools(
            tools.filter((tool) => tool.default && tool.name !== "get_scanner_results").map((tool) => tool.name)
          );
        }
        if (modelResult.status === "rejected") throw modelResult.reason;
        if (toolResult.status === "rejected") throw toolResult.reason;
        store.setOptionsState(false, false);
      } catch {
        if (cancelled) return;
        // 与旧版一致：最多再重试 2 次（共 3 次尝试），最终失败由工具区展示错误与重试入口。
        if (attempt < 2) {
          await new Promise((resolve) => window.setTimeout(resolve, 800 * (attempt + 1)));
          if (cancelled) return;
          await loadOptions(attempt + 1);
          return;
        }
        store.setOptionsState(false, true);
      }
    };

    void loadOptions(0);
    const retry = () => void loadOptions(0);
    window.addEventListener("dc:retry-options", retry);
    return () => {
      cancelled = true;
      window.removeEventListener("dc:retry-options", retry);
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        document.querySelectorAll<HTMLElement>(".modal").forEach((modal) => {
          if (modal.style.display !== "none") modal.style.display = "none";
        });
        closeConfirmDialog();
        closeHelpDialog();
        setHistoryDrawerOpen(false);
        setModelManagementOpen(false);
        setFolderPickerOpen(false);
      }
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        const target = document.activeElement as HTMLElement | null;
        if (target?.id === "prompt") {
          event.preventDefault();
          window.dispatchEvent(new CustomEvent("dc:send-message"));
        }
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [setFolderPickerOpen, setHistoryDrawerOpen, setModelManagementOpen]);

  const pages: Array<{ key: ActivePage; node: (active: boolean) => ReactElement }> = [
    { key: "dashboard", node: (active) => <DashboardPage active={active} /> },
    { key: "diff", node: (active) => <DiffPage active={active} /> },
    { key: "config", node: (active) => <ConfigPage active={active} /> },
    { key: "rule-growth", node: (active) => <RuleGrowthPage active={active} /> },
    { key: "review", node: (active) => <ReviewPage active={active} /> },
  ];

  return (
    <div className="app-container" data-layout-state={layoutState}>
      <nav className="sidebar-nav">
        <div className="nav-top">
          <button
            id="nav-dashboard"
            type="button"
            className={`nav-btn ${activePage === "dashboard" ? "active" : ""}`}
            title="仪表盘"
            onClick={() => navigate("dashboard")}
          >
            <Icon name="maximize" plain />
          </button>
          <button
            id="nav-review"
            type="button"
            className={`nav-btn ${activePage === "review" ? "active" : ""}`}
            title="代码审查"
            onClick={() => navigate("review")}
          >
            <Icon name="send" plain />
          </button>
          <button
            id="nav-diff"
            type="button"
            className={`nav-btn ${activePage === "diff" ? "active" : ""}`}
            title="代码变更"
            onClick={() => navigate("diff")}
          >
            <Icon name="folder" plain />
          </button>
          <button id="historyToggleBtn" type="button" className="nav-btn" title="历史记录" onClick={toggleHistoryDrawer}>
            <Icon name="clock" plain />
          </button>
        </div>
        <div className="nav-bottom">
          <button
            id="nav-rule-growth"
            type="button"
            className={`nav-btn ${activePage === "rule-growth" ? "active" : ""}`}
            title="规则优化"
            onClick={() => navigate("rule-growth")}
          >
            <Icon name="trending-up" plain />
          </button>
          <button
            id="nav-config"
            type="button"
            className={`nav-btn ${activePage === "config" ? "active" : ""}`}
            title="设置"
            onClick={() => navigate("config")}
          >
            <Icon name="settings" plain />
          </button>
        </div>
      </nav>

      <HistoryDrawer />

      <div className="main-content">
        {pages.map(({ key, node }) => (
          <Fragment key={key}>{node(activePage === key)}</Fragment>
        ))}
      </div>

      <ModelManagementModal />
      <FolderPickerModal />
    </div>
  );
}
