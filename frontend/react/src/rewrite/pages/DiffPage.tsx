import { useEffect, useRef } from "react";
import type { MouseEvent } from "react";

import { Icon } from "../components/Icon";
import {
  disposeDiffPage,
  initDiffPage,
  refreshDiffAnalysis,
  selectDiffMode,
} from "../features/diff/DiffController";

/**
 * 代码变更页（旧版 index.html:527-649 + modules/diff.js）。
 *
 * 静态骨架完全按旧版 DOM 复刻；动态区域（文件列表、Diff 内容、commit 菜单）
 * 由 DiffController 以与旧版相同的 innerHTML 方式写入，class/id/文本/内联样式
 * 保持逐字一致。
 */
export function DiffPage({ active }: { active: boolean }) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    initDiffPage();
    return () => {
      disposeDiffPage();
    };
  }, []);

  // 旧版 switchPage('diff') 进入页面时调用 refreshDiffAnalysis()
  useEffect(() => {
    if (active) void refreshDiffAnalysis();
  }, [active]);

  function handleModeTriggerClick(event: MouseEvent<HTMLDivElement>) {
    event.stopPropagation();
    document.getElementById("diffModeDropdown")?.classList.toggle("open");
  }

  function handleModeMenuClick(event: MouseEvent<HTMLDivElement>) {
    const target = event.target instanceof Element ? event.target : null;
    const item = target ? target.closest<HTMLElement>(".dropdown-item") : null;
    if (!item) return;
    const mode = item.getAttribute("data-mode");
    if (!mode) return;
    selectDiffMode(mode);
    document.getElementById("diffModeDropdown")?.classList.remove("open");
  }

  return (
    <div id="page-diff" ref={rootRef} className="page-view" style={{ display: active ? "block" : "none" }}>
      <div className="page-header">
        <h2>代码变更</h2>
        <div className="header-actions" style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {/* Review Status Hint Box */}
          <div
            id="diff-status-hint"
            className="status-hint-box"
            style={{
              display: "none",
              alignItems: "center",
              gap: "0.5rem",
              background: "rgba(59, 130, 246, 0.1)",
              padding: "0.4rem 0.8rem",
              border: "1px solid rgba(59, 130, 246, 0.2)",
              borderRadius: "6px",
              marginRight: "0.5rem",
            }}
          >
            <Icon name="info" plain style={{ width: "14px", height: "14px", color: "var(--primary)" }} />
            <span
              id="diff-status-text"
              style={{ fontSize: "0.85rem", color: "var(--text-main)", fontWeight: 500 }}
            >
              审查就绪
            </span>
          </div>
          {/* Diff模式选择器 */}
          <div className="custom-dropdown" id="diffModeDropdown" style={{ width: "160px" }}>
            <div className="dropdown-trigger" id="diffModeDropdownTrigger" onClick={handleModeTriggerClick}>
              <span id="selectedDiffModeText">自动检测</span>
              <Icon name="chevron-down" plain className="chevron" />
            </div>
            <div className="dropdown-menu" id="diffModeDropdownMenu" onClick={handleModeMenuClick}>
              <div className="dropdown-item" data-mode="auto">
                <span className="dropdown-item-label">自动检测</span>
              </div>
              <div className="dropdown-item" data-mode="working">
                <span className="dropdown-item-label">工作区</span>
              </div>
              <div className="dropdown-item" data-mode="staged">
                <span className="dropdown-item-label">暂存区</span>
              </div>
              <div className="dropdown-item" data-mode="pr">
                <span className="dropdown-item-label">PR模式</span>
              </div>
              <div className="dropdown-item" data-mode="commit">
                <span className="dropdown-item-label">历史提交</span>
              </div>
            </div>
          </div>
          <button className="btn-primary">刷新分析</button>
        </div>
      </div>

      {/* Commit选择器面板 (仅在commit模式下显示) */}
      <div id="commitSelectorPanel" className="commit-selector-panel" style={{ display: "none" }}>
        <div className="commit-range-card" id="commitRangeCard">
          <div className="commit-range-header">
            <Icon name="git-commit" plain style={{ width: "16px", height: "16px" }} />
            <span>选择提交范围</span>
          </div>
          {/* 折叠时显示的摘要 */}
          <div className="commit-range-summary" id="commitRangeSummary">
            <span className="summary-label">提交范围:</span>
            <span className="range-text">
              <span id="summaryFromHash">---</span>
              <span className="range-arrow">→</span>
              <span id="summaryToHash">HEAD</span>
            </span>
            <button className="change-btn">
              <Icon name="edit" plain style={{ width: "12px", height: "12px" }} />
              修改
            </button>
          </div>
          <div className="commit-range-content">
            <div className="commit-range-item">
              <div className="commit-range-label">起始</div>
              <div className="custom-dropdown commit-dropdown" id="commitFromDropdown">
                <div className="dropdown-trigger" id="commitFromTrigger">
                  <span id="commitFromText" className="commit-text">
                    选择起始提交...
                  </span>
                  <Icon name="chevron-down" plain className="chevron" />
                </div>
                <div className="dropdown-menu align-left" id="commitFromMenu"></div>
              </div>
            </div>
            <div className="commit-range-arrow">
              <Icon name="arrow-right" plain style={{ width: "18px", height: "18px", color: "#94a3b8" }} />
            </div>
            <div className="commit-range-item">
              <div className="commit-range-label">结束</div>
              <div className="custom-dropdown commit-dropdown" id="commitToDropdown">
                <div className="dropdown-trigger" id="commitToTrigger">
                  <span id="commitToText" className="commit-text">
                    HEAD (最新)
                  </span>
                  <Icon name="chevron-down" plain className="chevron" />
                </div>
                <div className="dropdown-menu align-left" id="commitToMenu"></div>
              </div>
            </div>
            <button className="btn-primary btn-small commit-view-btn">
              <Icon name="eye" plain style={{ width: "14px", height: "14px" }} />
              查看变更
            </button>
          </div>
        </div>
      </div>

      <div className="diff-layout">
        <div className="diff-sidebar">
          <div id="diff-file-list" className="file-list">
            {/* File list injected here */}
          </div>
        </div>
        <div className="diff-main">
          <div id="diff-content-area" className="code-view">
            <div className="empty-state">请选择文件查看 Diff</div>
          </div>
        </div>
      </div>
    </div>
  );
}
