import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";

import { Icon } from "../components/Icon";
import { ReviewController } from "../features/review/ReviewController";
import { ScannerController } from "../features/scanner/ScannerController";
import { useAppStore } from "../state/appStore";

export function ReviewPage({ active }: { active: boolean }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const controllerRef = useRef<ReviewController | null>(null);
  const layoutState = useAppStore((s) => s.layoutState);
  const autoApprove = useAppStore((s) => s.autoApprove);
  const enableStaticScan = useAppStore((s) => s.enableStaticScan);
  const setAutoApprove = useAppStore((s) => s.setAutoApprove);
  const setEnableStaticScan = useAppStore((s) => s.setEnableStaticScan);

  useEffect(() => {
    if (!rootRef.current) return;
    const controller = new ReviewController(rootRef.current);
    controllerRef.current = controller;
    controller.setScanner(new ScannerController());
    controller.init();
    return () => {
      controller.dispose();
      controllerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (active) {
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent("dc:refresh-diff-analysis"));
      }, 50);
      const workbench = rootRef.current;
      if (workbench && !workbench.classList.contains("text-animated")) {
        window.setTimeout(() => workbench.classList.add("text-animated"), 2500);
      }
    }
  }, [active]);

  return (
    <div
      id="page-review"
      ref={rootRef}
      className="workbench"
      data-layout-state={layoutState}
      style={{ display: active ? "flex" : "none" }}
    >
      <section id="reportPanel" className="report-panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <Icon name="bot" plain />
            <span className="panel-title">DeltaConverge</span>
          </div>
          <div className="view-toggle-group">
            <button id="viewToggleReport" type="button" className="view-toggle-btn active" data-report-view="report">
              <Icon name="report" plain />
              <span>审查报告</span>
            </button>
            <button id="viewToggleDiff" type="button" className="view-toggle-btn" data-report-view="diff">
              <Icon name="folder" plain />
              <span>详细信息</span>
            </button>
          </div>
          <div className="actions">
            <button id="reportBackBtn" type="button" className="icon-btn" title="返回工作区">
              <Icon name="return" plain />
            </button>
            <button id="copyReportBtn" type="button" className="icon-btn" title="复制">
              <Icon name="copy" plain />
            </button>
            <button id="reportFullscreenBtn" type="button" className="icon-btn" title="全屏">
              <Icon name="maximize" plain />
            </button>
          </div>
        </div>

        <div id="reportContainer" className="report-content markdown-body">
          <div className="empty-state">
            <div className="hero-animation" style={{ display: "flex" }}>
              <svg className="hero-icon" viewBox="0 0 100 100" aria-hidden="true">
                <path className="hero-path p1" d="M50 15 L85 35 L85 75 L50 95 L15 75 L15 35 Z" fill="none" stroke="currentColor" strokeWidth="0.8" />
                <path className="hero-path p2" d="M50 25 L75 40 L75 70 L50 85 L25 70 L25 40 Z" fill="none" stroke="currentColor" strokeWidth="1.2" />
                <circle className="hero-path c1" cx="50" cy="55" r="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <line className="hero-path l1" x1="50" y1="15" x2="50" y2="47" stroke="currentColor" strokeWidth="1" />
                <line className="hero-path l2" x1="50" y1="63" x2="50" y2="95" stroke="currentColor" strokeWidth="1" />
              </svg>
              <div className="hero-project-name" data-text="DeltaConverge">
                DeltaConverge
              </div>
            </div>
          </div>
        </div>

        <div id="diffViewContainer" className="diff-view-container" style={{ display: "none" }}>
          <div className="diff-view-layout">
            <div className="diff-view-sidebar">
              <div id="reportDiffFileList" className="file-list">
                <div className="empty-state">加载中...</div>
              </div>
            </div>
            <div className="diff-view-main">
              <div id="reportDiffContent" className="code-view">
                <div className="empty-state">请选择文件查看变更</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <main className="chat-area">
        <header className="chat-header">
          <div className="header-left">
            <button id="historyBackBtn" type="button" className="icon-btn-medium history-back-btn" title="返回新审查" style={{ display: "none" }}>
              <Icon name="return" plain />
            </button>
            <button id="backgroundTaskBtn" type="button" className="icon-btn-medium background-task-btn" title="查看后台运行的任务" style={{ display: "none" }}>
              <Icon name="clock" plain />
              <span className="pulse-dot" />
            </button>
            <button id="pickFolderBtn" type="button" className="icon-btn-medium" title="选择项目文件夹">
              <Icon name="folder" plain />
            </button>
            <div className="path-display">
              <span id="currentPathLabel" className="path-value">
                请选择文件夹...
              </span>
              <input type="hidden" id="projectRoot" />
            </div>
            <div id="headerModeDropdown" className="custom-dropdown" style={{ display: "none" }}>
              <div id="headerModeTrigger" className="dropdown-trigger mode-badge" style={{ border: "none", height: "auto", minWidth: "auto" }}>
                <span id="headerModeText">自动检测</span>
                <Icon name="chevron-down" className="chevron" style={{ width: 12, height: 12, marginLeft: 4, opacity: 0.6 }} />
              </div>
              <div id="headerModeMenu" className="dropdown-menu">
                <div className="dropdown-item" data-mode="auto">
                  <span>自动检测</span>
                </div>
                <div className="dropdown-item" data-mode="working">
                  <span>工作区模式</span>
                </div>
                <div className="dropdown-item" data-mode="staged">
                  <span>暂存区模式</span>
                </div>
                <div className="dropdown-item" data-mode="pr">
                  <span>PR 模式</span>
                </div>
                <div className="dropdown-item" data-mode="commit">
                  <span>历史提交模式</span>
                </div>
              </div>
            </div>
            <span id="historyModeLabel" className="history-mode-badge" style={{ display: "none" }}>
              只读
            </span>
          </div>

          <div className="header-controls">
            <div id="modelDropdown" className="custom-dropdown">
              <div id="modelDropdownTrigger" className="dropdown-trigger">
                <span id="selectedModelText">请选择模型</span>
                <Icon name="chevron-down" plain />
              </div>
              <div id="modelDropdownMenu" className="dropdown-menu" />
            </div>
          </div>
        </header>

        <div id="heroAnimation" className="hero-animation">
          <svg className="hero-icon" viewBox="0 0 100 100" aria-hidden="true">
            <path className="hero-path p1" d="M50 15 L85 35 L85 75 L50 95 L15 75 L15 35 Z" fill="none" stroke="currentColor" strokeWidth="0.8" />
            <path className="hero-path p2" d="M50 25 L75 40 L75 70 L50 85 L25 70 L25 40 Z" fill="none" stroke="currentColor" strokeWidth="1.2" />
            <circle className="hero-path c1" cx="50" cy="55" r="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <line className="hero-path l1" x1="50" y1="15" x2="50" y2="47" stroke="currentColor" strokeWidth="1" />
            <line className="hero-path l2" x1="50" y1="63" x2="50" y2="95" stroke="currentColor" strokeWidth="1" />
          </svg>
          <div className="hero-project-name" data-text="DeltaConverge">
            DeltaConverge
          </div>
        </div>

        <div id="messageContainer" className="message-container">
          <div className="message system-message">
            <div className="avatar">
              <Icon name="bot" plain />
            </div>
            <div className="content">
              <p>准备好审查您的代码，请选择一个项目文件夹开始。</p>
            </div>
          </div>
        </div>

        <footer className="input-area collapsed">
          <div className="tools-controls-row">
            <label className="toggle-label align-left" title="允许工具自动运行无需确认">
              <input type="checkbox" id="autoApprove" checked={autoApprove} onChange={(event) => setAutoApprove(event.target.checked)} />
              <span>自动运行（实验）</span>
            </label>
            <label className="toggle-label align-right" title="静态分析（旁路，不阻塞主链路）">
              <input type="checkbox" id="enableStaticScan" checked={enableStaticScan} onChange={(event) => setEnableStaticScan(event.target.checked)} />
              <span>静态分析</span>
            </label>
          </div>

          <div className="action-wrapper">
            <textarea id="prompt" rows={1} style={{ display: "none" }} placeholder="输入消息..." />
            <button id="startReviewBtn" type="button" className="review-btn-large">
              <Icon name="send" plain />
            </button>
            <button id="sendBtn" type="button" className="send-btn" style={{ display: "none" }}>
              <Icon name="send" plain />
            </button>
          </div>
        </footer>
      </main>

      <aside id="rightPanel" className="right-panel">
        <section id="progressPanel" className="progress-panel">
          <div className="progress-content">
            <ul className="progress-steps">
              <li className="step-item" data-step="init">
                <div className="step-icon">
                  <Icon name="init" plain />
                </div>
                <div className="step-info">
                  <div className="step-title">初始化</div>
                  <div className="step-desc">准备审查环境...</div>
                  <div className="step-data" />
                </div>
              </li>
              <li className="step-item" data-step="analysis">
                <div className="step-icon">
                  <Icon name="scan" plain />
                </div>
                <div className="step-info">
                  <div className="step-title">项目分析</div>
                  <div className="step-desc">扫描变更与意图...</div>
                  <div className="step-data" />
                </div>
              </li>
              <li className="step-item" data-step="planning">
                <div className="step-icon">
                  <Icon name="plan" plain />
                </div>
                <div className="step-info">
                  <div className="step-title">策略规划</div>
                  <div className="step-desc">制定审查计划...</div>
                  <div className="step-data" />
                </div>
              </li>
              <li className="step-item" data-step="reviewing">
                <div className="step-icon">
                  <Icon name="review" plain />
                </div>
                <div className="step-info">
                  <div className="step-title">智能审查</div>
                  <div className="step-desc">AI 深度分析代码...</div>
                  <div className="step-data" />
                </div>
              </li>
              <li className="step-item" data-step="reporting">
                <div className="step-icon">
                  <Icon name="report" plain />
                </div>
                <div className="step-info">
                  <div className="step-title">生成报告</div>
                  <div className="step-desc">汇总审查结果...</div>
                  <div className="step-data" />
                </div>
              </li>
            </ul>
            <div className="progress-right-info">
              <Icon name="folder" plain />
              <span id="reviewProjectPath" className="path-value">
                --
              </span>
            </div>
          </div>
        </section>

        <div id="rightPanelScrollArea">
          <div id="scannerContainer" className="workflow-entries">
            <div id="scannerWorkflowSection" className="workflow-stage-section" style={{ display: "none" }}>
              <div className="stage-header collapsible">
                <div className="stage-indicator" style={{ "--stage-color": "#0ea5e9" } as CSSProperties}>
                  <Icon name="scan" plain />
                  <span>静态扫描</span>
                </div>
                <div className="scanner-header-right">
                  <span id="scannerStageMeta" className="scanner-overview-meta scanner-stage-meta" />
                  <Icon name="chevron-down" className="chevron" />
                </div>
              </div>
              <div className="stage-content scanner-stage-content">
                <div className="scanner-tabs">
                  <button type="button" className="scanner-tab active" data-severity="all">
                    总览 <span className="tab-count">0</span>
                  </button>
                  <button type="button" className="scanner-tab" data-severity="error">
                    错误 <span className="tab-count error">0</span>
                  </button>
                  <button type="button" className="scanner-tab" data-severity="warning">
                    警告 <span className="tab-count warning">0</span>
                  </button>
                  <button type="button" className="scanner-tab" data-severity="info">
                    信息 <span className="tab-count info">0</span>
                  </button>
                </div>
                <div className="scanner-content">
                  <div className="scanner-cards" />
                  <div className="scanner-issues-list" />
                  <div className="scanner-summary" style={{ display: "none" }} />
                </div>
              </div>
            </div>
          </div>

          <div className="workflow-entries" id="workflowEntries" />
        </div>

        <section id="monitorPanel" className="monitor-panel collapsed">
          <div className="panel-header collapsible">
            <span className="panel-title">日志</span>
            <span
              id="reviewTimer"
              className="time-display"
              style={{ marginLeft: "auto", marginRight: 10, fontVariantNumeric: "tabular-nums", fontSize: "0.85rem", color: "var(--text-secondary)" }}
            />
            <Icon name="chevron-down" className="chevron" />
          </div>
          <div className="workflow-content">
            <div className="workflow-entries" id="monitorContent" />
          </div>
        </section>
      </aside>

    </div>
  );
}
