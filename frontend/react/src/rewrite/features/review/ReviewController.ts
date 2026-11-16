import { createReview, getMessages, streamReview } from "../../lib/api";
import type { FlatEvent } from "../../lib/events";
import { escapeHtml, getIcon } from "../../lib/html";
import { renderMarkdown } from "../../lib/markdown";
import { showToast } from "../../lib/toast";
import { availableModel, modelCapabilityLabel } from "../../lib/modelSelection";
import { useAppStore } from "../../state/appStore";
import { replayScannerEvents, replayWorkflowEvents } from "../replay/replay";
import { LinkedView } from "./linkedView";
import {
  markAllStepsCompleted,
  renderReportPlaceholder,
  resetProgress,
  setProgressStep,
  startReviewTimer,
  stopReviewTimer,
  toggleMonitorPanel,
} from "./progress";
import { LiveWorkflowRenderer } from "./workflowLive";

type ScannerLike = {
  init(section: HTMLElement): void;
  reset(): void;
  beginScanning(): void;
  endScanning(): void;
  toggleSection(): void;
  setRunId(runId: string | null): void;
  handleScannerProgress(event: Record<string, unknown>): void;
  handleScannerSummary(event: Record<string, unknown>): void;
  updateScanningFile(name: string, file: string, language?: string): void;
  updateFileProgress(name: string, info: Record<string, unknown>): void;
};

const LAST_SESSION_KEY = "lastSessionId";

function normalizeUsage(usage: Record<string, unknown>): Record<string, unknown> {
  const inTokens = usage.in ?? usage.input_tokens ?? usage.prompt_tokens;
  const outTokens = usage.out ?? usage.output_tokens ?? usage.completion_tokens;
  const totalTokens =
    usage.total ??
    usage.total_tokens ??
    (inTokens !== undefined || outTokens !== undefined
      ? Number(inTokens ?? 0) + Number(outTokens ?? 0)
      : undefined);
  const result: Record<string, unknown> = {};
  if (inTokens !== undefined) result.in = inTokens;
  if (outTokens !== undefined) result.out = outTokens;
  if (totalTokens !== undefined) result.total = totalTokens;
  return result;
}

function accumulateUsage(
  previous: Record<string, unknown> | null,
  current: Record<string, unknown>
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const key of ["in", "out", "total"]) {
    const prev = previous?.[key];
    const now = current[key];
    if (prev !== undefined || now !== undefined) {
      result[key] = Number(prev ?? 0) + Number(now ?? 0);
    }
  }
  return result;
}

function generateSessionId(): string {
  return `sess_${Date.now()}`;
}

function setLastSessionId(id: string): void {
  try {
    localStorage.setItem(LAST_SESSION_KEY, id);
  } catch {
    // 旧版同样忽略
  }
}

export class ReviewController {
  private readonly root: HTMLElement;
  private workflow: LiveWorkflowRenderer;
  private linked: LinkedView;
  private scanner: ScannerLike | null = null;
  private scannerSection: HTMLElement | null;
  private unsubscribeStore: (() => void) | null = null;
  private disposed = false;
  private streamAbort: AbortController | null = null;
  private diffPreloadTimer: number | null = null;

  private finalReportContent = "";
  private pendingChunkContent = "";
  private reportRenderFrame: number | null = null;
  private reportFinalized = false;
  private errorSeen = false;
  private lastSessionUsage: Record<string, unknown> | null = null;
  private running = false;

  /** 每次启动审查自增，用于丢弃上一轮（已取消/被替换）流的迟到回调。 */
  private runSeq = 0;
  /** 本轮审查所属会话；用户切走后迟到的日志/usage 不应写进当前会话。 */
  private activeSessionId: string | null = null;

  private readonly handleModelOutsideClick = (event: MouseEvent) => {
    const dropdown = this.root.querySelector("#modelDropdown");
    if (dropdown && !dropdown.contains(event.target as Node)) dropdown.classList.remove("open");
    const modeDropdown = this.root.querySelector("#headerModeDropdown");
    if (modeDropdown && !modeDropdown.contains(event.target as Node)) modeDropdown.classList.remove("open");
  };

  constructor(root: HTMLElement) {
    this.root = root;
    this.scannerSection = root.querySelector<HTMLElement>("#scannerWorkflowSection");
    this.workflow = new LiveWorkflowRenderer(root, {
      onReviewChunk: (text) => {
        this.ensureReviewingLayout();
        this.pendingChunkContent += text;
        this.scheduleReportRender();
      },
      consumePendingReviewChunk: () => {
        const text = this.pendingChunkContent;
        this.pendingChunkContent = "";
        return text;
      },
    });
    this.linked = new LinkedView(root);
  }

  setScanner(scanner: ScannerLike): void {
    this.scanner = scanner;
    if (this.scannerSection) {
      scanner.init(this.scannerSection);
      scanner.setRunId(useAppStore.getState().runId);
    }
  }

  init(): void {
    this.workflow.init();
    this.bindEvents();
    this.renderModelMenu();
    this.syncProjectPath();
    this.updateBackgroundTaskButton();
    this.renderHistoryMode();
    this.scheduleDiffPreload();
    this.unsubscribeStore = useAppStore.subscribe((state, previous) => {
      if (state.projectRoot !== previous.projectRoot) this.syncProjectPath();
      if (state.projectRoot !== previous.projectRoot || state.sessionId !== previous.sessionId ||
          state.runId !== previous.runId || state.diffMode !== previous.diffMode ||
          state.commitFrom !== previous.commitFrom || state.commitTo !== previous.commitTo) {
        this.scheduleDiffPreload();
      }
      if (state.availableGroups !== previous.availableGroups) this.renderModelMenu();
      if (state.model !== previous.model) this.syncModelLabel();
      if (state.runId !== previous.runId) this.scanner?.setRunId(state.runId);
      if (state.runningSessionId !== previous.runningSessionId) this.updateBackgroundTaskButton();
      if (state.viewingHistory !== previous.viewingHistory) this.renderHistoryMode();
      if (state.reportViewMode !== previous.reportViewMode) {
        // 视图切换由 LinkedView 内部处理按钮 class，这里只同步 store 驱动的模式
      }
    });
  }

  dispose(): void {
    this.disposed = true;
    this.cancelReportRender();
    this.runSeq += 1;
    this.running = false;
    this.activeSessionId = null;
    this.streamAbort?.abort();
    if (this.diffPreloadTimer !== null) window.clearTimeout(this.diffPreloadTimer);
    this.unsubscribeStore?.();
    this.workflow.dispose();
    this.linked.dispose();
    document.removeEventListener("click", this.handleModelOutsideClick);
    window.removeEventListener("dc:refresh-diff-analysis", this.onRefreshDiffAnalysis);
    window.removeEventListener("dc:send-message", this.onSendMessage);
    window.removeEventListener("dc:start-review", this.onStartReview);
    window.removeEventListener("dc:replay-events", this.onReplayEvents);
    window.removeEventListener("dc:cancel-review", this.onCancelReview);
    stopReviewTimer(this.root);
  }

  // ── 绑定事件 ───────────────────────────────────────────────

  private bindEvents(): void {
    document.addEventListener("click", this.handleModelOutsideClick);

    this.root.querySelector("#startReviewBtn")?.addEventListener("click", () => void this.startReview());
    this.root.querySelector("#monitorPanel .panel-header")?.addEventListener("click", () => toggleMonitorPanel(this.root));
    this.root.querySelector("#scannerWorkflowSection .stage-header")?.addEventListener("click", () => {
      this.scanner?.toggleSection();
    });
    this.root.querySelector("#pickFolderBtn")?.addEventListener("click", () => {
      useAppStore.getState().setFolderPickerOpen(true);
    });
    this.root.querySelector("#copyReportBtn")?.addEventListener("click", () => this.copyReportContent());
    this.root.querySelector("#reportFullscreenBtn")?.addEventListener("click", () => {
      this.root.querySelector("#reportPanel")?.classList.toggle("fullscreen");
    });
    this.root.querySelector("#reportBackBtn")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.reportGoBack();
    });
    this.root.querySelector("#historyBackBtn")?.addEventListener("click", () => {
      window.dispatchEvent(new CustomEvent("dc:return-new-workspace"));
    });
    this.root.querySelector("#backgroundTaskBtn")?.addEventListener("click", () => {
      const runningId = useAppStore.getState().runningSessionId;
      if (runningId) window.dispatchEvent(new CustomEvent("dc:load-session", { detail: runningId }));
      else showToast("没有正在运行的任务", "info");
    });
    this.root.querySelector("#viewToggleReport")?.addEventListener("click", () => this.linked.switchReportView("report"));
    this.root.querySelector("#viewToggleDiff")?.addEventListener("click", () => this.linked.switchReportView("diff"));

    this.root.querySelector("#modelDropdownTrigger")?.addEventListener("click", (event) => {
      event.stopPropagation();
      this.root.querySelector("#modelDropdown")?.classList.toggle("open");
    });
    this.root.querySelector("#headerModeTrigger")?.addEventListener("click", (event) => {
      event.stopPropagation();
      this.root.querySelector("#headerModeDropdown")?.classList.toggle("open");
    });
    this.root.querySelector("#headerModeMenu")?.addEventListener("click", (event) => {
      const item = (event.target as HTMLElement).closest<HTMLElement>(".dropdown-item");
      if (!item) return;
      const mode = item.dataset.mode ?? "auto";
      useAppStore.getState().setDiffMode(mode as never);
      this.root.querySelector("#headerModeDropdown")?.classList.remove("open");
      if (mode === "commit") useAppStore.getState().setActivePage("diff");
      window.dispatchEvent(new CustomEvent("dc:refresh-diff-analysis"));
    });

    this.root.querySelector("#modelDropdownMenu")?.addEventListener("click", (event) => {
      const item = (event.target as HTMLElement).closest<HTMLElement>(".dropdown-item");
      if (!item) return;
      const value = item.dataset.value;
      if (!value) return;
      if (item.dataset.available === "false") return;
      this.selectModel(value, item.dataset.label ?? value);
    });

    window.addEventListener("dc:refresh-diff-analysis", this.onRefreshDiffAnalysis);
    window.addEventListener("dc:send-message", this.onSendMessage);
    window.addEventListener("dc:start-review", this.onStartReview);
    window.addEventListener("dc:replay-events", this.onReplayEvents);
    window.addEventListener("dc:cancel-review", this.onCancelReview);
  }

private readonly onReplayEvents = (event: Event) => {
    const events = (event as CustomEvent).detail as Array<Record<string, unknown>>;
    this.onReplay(events);
  };

  private onReplay(events: Array<Record<string, unknown>>): void {
    this.cancelReportRender();
    if (!events.length) return;
    const workflowEntries = this.root.querySelector<HTMLElement>("#workflowEntries");
    if (workflowEntries) replayWorkflowEvents(workflowEntries, events);
    if (this.scanner) {
      replayScannerEvents(events, this.scanner as unknown as Parameters<typeof replayScannerEvents>[1]);
    }
  }

  private readonly onCancelReview = () => {
    if (!this.running) return;
    this.runSeq += 1;
    this.streamAbort?.abort();
    this.streamAbort = null;
    this.cancelReportRender();
    this.finishRunning();
  };

  private scheduleDiffPreload(): void {
    if (this.diffPreloadTimer !== null) window.clearTimeout(this.diffPreloadTimer);
    this.diffPreloadTimer = window.setTimeout(() => {
      this.diffPreloadTimer = null;
      if (!this.disposed) void this.linked.loadReportDiffFiles();
    }, 150);
  }

  private readonly onRefreshDiffAnalysis = () => {
    this.renderHistoryMode();
    this.scheduleDiffPreload();
  };

  private readonly onSendMessage = () => {
    void this.sendMessage();
  };

  private readonly onStartReview = () => {
    void this.startReview();
  };

  // ── 模型 ─────────────────────────────────────────────

  private renderModelMenu(): void {
    const menu = this.root.querySelector<HTMLElement>("#modelDropdownMenu");
    if (!menu) return;
    const { availableGroups, model } = useAppStore.getState();
    if (!availableGroups.length) {
      menu.innerHTML = '<div class="dropdown-item" style="opacity:.5;cursor:not-allowed">请先在设置中获取并保存模型</div>';
      this.syncModelLabel();
      return;
    }
    const html = availableGroups
      .map((group) => {
        const options = group.models
          .map((item) => {
            const unavailable = !item.available;
            const selected = item.name === model;
            const capability = modelCapabilityLabel(item.capabilities);
            return `<div class="dropdown-item ${selected ? "selected" : ""}" data-value="${escapeHtml(item.name)}" data-label="${escapeHtml(item.label)}" data-available="${item.available}" ${unavailable ? `style="opacity:.5;cursor:not-allowed" title="${escapeHtml(item.reason ?? "服务未就绪")}"` : ""}>
              <span>${escapeHtml(item.label)}${capability ? ` · ${capability}` : ""}</span>
            </div>`;
          })
          .join("");
        if (!options) return "";
        return `<div class="dropdown-group-container expanded">
          <div class="dropdown-group-header"><span>${escapeHtml(group.label)}</span><svg class="icon chevron-dropdown"><use href="#icon-chevron-down"></use></svg></div>
          <div class="dropdown-group-models">${options}</div>
        </div>`;
      })
      .join("");
    menu.innerHTML = html || '<div class="dropdown-item" style="opacity:.5;cursor:not-allowed">无可用模型</div>';
    this.syncModelLabel();
  }

  private syncModelLabel(): void {
    const { model } = useAppStore.getState();
    const labelEl = this.root.querySelector("#selectedModelText");
    if (!labelEl) return;
    if (!model) {
      labelEl.textContent = "请选择模型";
      return;
    }
    this.root.querySelectorAll<HTMLElement>("#modelDropdownMenu .dropdown-item").forEach((item) => {
      item.classList.toggle("selected", item.dataset.value === model);
    });
    const selected = this.root.querySelector<HTMLElement>(`#modelDropdownMenu .dropdown-item[data-value="${CSS.escape(model)}"]`);
    labelEl.textContent = selected?.dataset.label ?? selected?.textContent?.trim() ?? model;
  }

  private selectModel(value: string, label: string): void {
    if (!availableModel(useAppStore.getState().availableGroups, value)) return;
    useAppStore.getState().setModel(value);
    const labelEl = this.root.querySelector("#selectedModelText");
    if (labelEl) labelEl.textContent = label;
    this.root.querySelector("#modelDropdown")?.classList.remove("open");
    this.root.querySelectorAll<HTMLElement>("#modelDropdownMenu .dropdown-item").forEach((item) => {
      item.classList.toggle("selected", item.dataset.value === value);
    });

  }

  // ── 路径 / 布局 / 后台任务 ──────────────────────────────────

  private syncProjectPath(): void {
    const { projectRoot } = useAppStore.getState();
    const path = projectRoot || "";
    const label = this.root.querySelector("#currentPathLabel");
    if (label) label.textContent = path || "请选择文件夹...";
    const hidden = this.root.querySelector<HTMLInputElement>("#projectRoot");
    if (hidden) hidden.value = path;
    const dash = this.root.querySelector("#reviewProjectPath");
    if (dash) {
      dash.textContent = path || "--";
      (dash as HTMLElement).title = path;
    }
  }

  private ensureReviewingLayout(): void {
    const store = useAppStore.getState();
    if (store.layoutState !== "completed") store.setLayoutState("completed");
    setProgressStep(this.root, "analysis", "completed");
    setProgressStep(this.root, "planning", "completed");
    setProgressStep(this.root, "reviewing", "active");
  }

  private updateBackgroundTaskButton(): void {
    const button = this.root.querySelector<HTMLElement>("#backgroundTaskBtn");
    if (!button) return;
    const { runningSessionId, sessionId, viewingHistory } = useAppStore.getState();
    const visible = Boolean(runningSessionId) && !viewingHistory && sessionId !== runningSessionId;
    button.style.display = visible ? "flex" : "none";
  }

  private renderHistoryMode(): void {
    const badge = this.root.querySelector<HTMLElement>("#historyModeLabel");
    if (!badge) return;
    const { viewingHistory, runningSessionId, sessionId } = useAppStore.getState();
    badge.style.display = viewingHistory && runningSessionId !== sessionId ? "inline-flex" : "none";
    const back = this.root.querySelector<HTMLElement>("#historyBackBtn");
    if (back) back.style.display = viewingHistory ? "flex" : "none";
  }

  // ── 启动审查 ───────────────────────────────────────────────

  async startReview(): Promise<void> {
    const store = useAppStore.getState();
    const projectRoot = store.projectRoot;
    if (!projectRoot) {
      showToast("请先选择项目文件夹！", "error");
      return;
    }
    if (!availableModel(store.availableGroups, store.model)) {
      showToast("请先在设置中获取并保存模型，然后选择可用模型。", "error", { floating: true });
      return;
    }
    store.setActivePage("review");

    // 上一轮审查可能仍在跑（用户切回工作区后重新发起）：先作废并中止旧流，
    // 避免旧流的日志/usage 事件写进新一轮的面板。
    this.runSeq += 1;
    const runSeq = this.runSeq;
    this.streamAbort?.abort();
    this.streamAbort = null;
    this.cancelReportRender();

    const startReviewBtn = this.root.querySelector<HTMLButtonElement>("#startReviewBtn");
    if (startReviewBtn) {
      startReviewBtn.disabled = true;
      startReviewBtn.innerHTML = '<span class="spinner"></span>';
    }

    const reviewProjectPath = this.root.querySelector("#reviewProjectPath");
    if (reviewProjectPath) {
      reviewProjectPath.textContent = projectRoot;
      (reviewProjectPath as HTMLElement).title = projectRoot;
    }

    store.setLayoutState("completed");
    renderReportPlaceholder(this.root.querySelector("#reportContainer"));
    this.workflow.reset();
    resetProgress(this.root);
    // resetProgress 会清空 workflowEntries，因此等待提示必须在其后插入。
    // 点击后立刻可见，不等模型首 token / diff 准备完成。
    this.workflow.showWaiting("init", "正在准备审查环境…");
    setProgressStep(this.root, "init", "completed");
    setProgressStep(this.root, "analysis", "active");
    startReviewTimer(this.root);

    if (!store.sessionId) {
      const newId = generateSessionId();
      store.setSessionId(newId);
      setLastSessionId(newId);
    }
    const sessionId = useAppStore.getState().sessionId as string;
    this.activeSessionId = sessionId;
    this.startReviewTask(sessionId);

    const { selectedTools, autoApprove, enableStaticScan } = useAppStore.getState();
    const tools = selectedTools.filter((name) => name !== "get_scanner_results");
    if (enableStaticScan && store.tools.some((tool) => tool.name === "get_scanner_results")) {
      tools.push("get_scanner_results");
    }

    this.scanner?.reset();

    if (enableStaticScan) {
      if (this.scannerSection) {
        this.scannerSection.style.display = "block";
        this.scannerSection.classList.add("collapsed");
      }
      this.scanner?.beginScanning();
    }

    const diffState = useAppStore.getState();
    const diffMode = diffState.diffMode === "auto" ? "auto" : diffState.diffMode;
    const commitFrom = diffMode === "commit" ? diffState.commitFrom : null;
    const commitTo = diffMode === "commit" ? diffState.commitTo : null;

    this.finalReportContent = "";
    this.pendingChunkContent = "";
    this.reportFinalized = false;
    this.errorSeen = false;
    this.lastSessionUsage = null;
    this.running = true;

    try {
      useAppStore.getState().setRunId(null);
      this.scanner?.setRunId(null);
      const created = await createReview({
        project_root: projectRoot,
        model: diffState.model,
        tools,
        agents: [],
        auto_approve: autoApprove,
        session_id: sessionId,
        enable_static_scan: enableStaticScan,
        diff_mode: diffMode,
        commit_from: commitFrom,
        commit_to: commitTo,
      });
      if (runSeq !== this.runSeq) return;
      const runId = String((created.run as Record<string, unknown>)?.id ?? "");
      useAppStore.getState().setRunId(runId || null);
      this.scanner?.setRunId(runId);
      this.streamAbort = new AbortController();
      await streamReview(
        runId,
        {
          onEvent: (event) => {
            if (runSeq !== this.runSeq) return;
            this.processEvent(event);
          },
          onTerminal: (event) => {
            if (runSeq !== this.runSeq) return;
            void this.handleTerminal(event);
          },
          onError: (error) => {
            if (runSeq !== this.runSeq) return;
            this.handleStreamError(error);
          },
        },
        this.streamAbort.signal
      );
      if (runSeq !== this.runSeq) return;
      this.handleStreamClosed();
    } catch (error) {
      if (runSeq !== this.runSeq) return;
      console.error("Start review error:", error);
      const message = error instanceof Error ? error.message : String(error);
      this.appendSystemMessage("启动审查失败: " + escapeHtml(message));
      useAppStore.getState().setLayoutState("initial");
      this.finishRunning();
    }
  }

  private startReviewTask(sessionId: string): void {
    const store = useAppStore.getState();
    store.setRunningSessionId(sessionId);
    store.setViewingHistory(false);
    this.updateBackgroundTaskButton();
    window.dispatchEvent(new CustomEvent("dc:load-sessions"));
  }

  private finishRunning(): void {
    if (this.isActiveSession()) this.workflow.finalize();
    this.running = false;
    useAppStore.getState().setRunningSessionId(null);
    this.updateBackgroundTaskButton();
    const button = this.root.querySelector<HTMLButtonElement>("#startReviewBtn");
    if (button) {
      button.disabled = false;
      button.innerHTML = getIcon("send");
    }
  }

  private appendSystemMessage(content: string): void {
    const container = this.root.querySelector("#messageContainer");
    if (!container) return;
    const div = document.createElement("div");
    div.className = "message system-message instant";
    div.innerHTML = `
      <div class="avatar">${getIcon("bot")}</div>
      <div class="message-body"><div class="content"><p>${content}</p></div></div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  private async sendMessage(): Promise<void> {
    const promptInput = this.root.querySelector<HTMLTextAreaElement>("#prompt");
    if (!promptInput) return;
    const text = promptInput.value.trim();
    if (!text) return;
    promptInput.value = "";
    this.appendSystemMessage(escapeHtml(text));
    showToast("聊天输入在旧版中不可用", "warning");
  }

  // ── SSE 事件处理 ────────────────────────────────────────────

  private isActiveSession(): boolean {
    if (!this.activeSessionId) return true;
    return useAppStore.getState().sessionId === this.activeSessionId;
  }

  private processEvent(evt: FlatEvent): void {
    if (!this.isActiveSession()) return;
    try {
      const stage = String(evt.stage || "review");

      if (evt.type === "thought" || evt.type === "tool_start" || evt.type === "chunk") {
        if (stage === "intent") {
          setProgressStep(this.root, "analysis", "active");
        } else if (stage === "review") {
          setProgressStep(this.root, "analysis", "completed");
          setProgressStep(this.root, "planning", "completed");
          setProgressStep(this.root, "reviewing", "active");
          if (useAppStore.getState().layoutState !== "completed") {
            useAppStore.getState().setLayoutState("completed");
          }
        } else if (stage === "planner") {
          setProgressStep(this.root, "analysis", "completed");
          setProgressStep(this.root, "planning", "active");
        }
      }

      if (evt.type === "pipeline_stage_start") {
        const pipelineStage = String(evt.stage ?? "");
        if (pipelineStage === "intent_analysis") {
          setProgressStep(this.root, "analysis", "active");
          this.workflow.showWaiting("intent", "正在分析项目意图…");
        } else if (pipelineStage === "planner") {
          setProgressStep(this.root, "analysis", "completed");
          setProgressStep(this.root, "planning", "active");
          this.workflow.showWaiting("planner", "正在生成审查计划…");
        } else if (["fusion", "context_provider", "reviewer", "review"].includes(pipelineStage)) {
          setProgressStep(this.root, "analysis", "completed");
          setProgressStep(this.root, "planning", "completed");
          setProgressStep(this.root, "reviewing", "active");
          if (pipelineStage === "reviewer" || pipelineStage === "review") {
            this.workflow.showWaiting("review", "正在执行代码审查…");
          }
          if (useAppStore.getState().layoutState !== "completed") {
            useAppStore.getState().setLayoutState("completed");
          }
        }
        return;
      }

      if (evt.type === "pipeline_stage_end") {
        const pipelineStage = String(evt.stage ?? "");
        if (pipelineStage === "intent_analysis") {
          setProgressStep(this.root, "analysis", "completed");
          this.workflow.clearWaiting("intent");
        } else if (pipelineStage === "planner") {
          setProgressStep(this.root, "planning", "completed");
          this.workflow.clearWaiting("planner");
        } else if (pipelineStage === "reviewer" || pipelineStage === "review") {
          setProgressStep(this.root, "reviewing", "completed");
          setProgressStep(this.root, "reporting", "active");
          this.workflow.clearWaiting("review");
        }
        return;
      }

      if (evt.type === "bundle_item") return;

      if (evt.type === "scanner_progress") {
        this.scanner?.handleScannerProgress(evt);
        this.scannerSection?.classList.add("active");
        if (evt.status === "start") setProgressStep(this.root, "analysis", "active");
        return;
      }

      if (evt.type === "scanner_issues_summary") {
        this.scanner?.handleScannerSummary(evt);
        return;
      }

      if (evt.type === "static_scan_start") {
        if (this.scannerSection) {
          this.scannerSection.style.display = "block";
          this.scannerSection.classList.remove("collapsed");
        }
        this.scanner?.handleScannerProgress({
          status: "start",
          scanner: "static_scan",
          file: `${evt.files_total || 0} files`,
          timestamp: evt.timestamp,
        });
        return;
      }

      if (evt.type === "static_scan_file_start") {
        this.scanner?.updateScanningFile("static_scan", String(evt.file ?? ""), String(evt.language ?? ""));
        return;
      }

      if (evt.type === "static_scan_file_done") {
        this.scanner?.updateFileProgress("static_scan", {
          file: evt.file,
          language: evt.language,
          duration_ms: evt.duration_ms,
          issues_count: evt.issues_count || 0,
          progress: evt.progress,
        });
        return;
      }

      if (evt.type === "static_scan_complete") {
        this.scanner?.handleScannerProgress({
          status: "complete",
          scanner: "static_scan",
          duration_ms: evt.duration_ms || 0,
          issue_count: evt.total_issues || 0,
          error_count: evt.error_count || 0,
          files_scanned: evt.files_scanned,
          files_total: evt.files_total,
        });
        this.scanner?.handleScannerSummary({
          total_issues: evt.total_issues || 0,
          by_severity: {
            error: evt.error_count || 0,
            warning: evt.warning_count || 0,
            info: evt.info_count || 0,
          },
          critical_issues: evt.issues || [],
          files_scanned: evt.files_scanned,
          files_total: evt.files_total,
          files_skipped_doc: evt.files_skipped_doc,
          duration_ms: evt.duration_ms,
          scanners_used: evt.scanners_used || [],
        });
        this.scanner?.endScanning();
        window.setTimeout(() => {
          if (this.scannerSection && !this.scannerSection.classList.contains("collapsed")) {
            this.scannerSection.classList.add("collapsed");
          }
        }, 500);
        void this.linked.refresh();
        return;
      }

      if (
        evt.type === "thought" ||
        evt.type === "tool_start" ||
        evt.type === "tool_result" ||
        evt.type === "tool_call_end" ||
        evt.type === "chunk" ||
        evt.type === "workflow_chunk" ||
        evt.type === "tool_call_start"
      ) {
        this.workflow.append(evt);
        return;
      }

      if (evt.type === "session_title" && evt.title) {
        // v2 编排器已经更新会话标题；旧 UI 的二次 rename 按缺口报告不再执行
        window.dispatchEvent(new CustomEvent("dc:load-sessions"));
        return;
      }

      if (evt.type === "warning" && evt.stage === "planner") {
        this.appendPlannerWarning(String(evt.message || "重试中..."));
        return;
      }

      if (evt.type === "usage_summary") {
        this.appendUsageSummary(evt);
        return;
      }

      if (evt.type === "error") {
        this.errorSeen = true;
        this.renderError(String(evt.message || "未知错误"));
        stopReviewTimer(this.root);
        this.finishRunning();
        return;
      }

      if (evt.type === "done") {
        this.handleDone();
      }
    } catch (error) {
      console.error("[SSE] processEvent error", error, evt);
    }
  }

  private async handleTerminal(event: { type: string; payload?: Record<string, unknown> }): Promise<void> {
    if (!this.isActiveSession()) return;
    if (event.type === "review.failed") {
      // flattenEvent 会把 review.failed 同时转成一个 error 事件；
      // 这里只负责收尾，避免错误卡片渲染两遍。
      if (!this.errorSeen) {
        this.errorSeen = true;
        this.renderError(String(event.payload?.error ?? "审查失败"));
      }
      this.workflow.clearWaiting();
      stopReviewTimer(this.root);
      this.finishRunning();
      return;
    }

    // review.completed：v2 不再发 final，从已保存消息中取最终报告
    this.reportFinalized = true;
    this.cancelReportRender();
    this.workflow.finalize();
    setProgressStep(this.root, "reviewing", "completed");
    setProgressStep(this.root, "reporting", "active");

    try {
      const sessionId = this.activeSessionId ?? useAppStore.getState().sessionId;
      if (sessionId) {
        const messages = await getMessages(sessionId);
        const report = [...messages]
          .reverse()
          .find(
            (message) =>
              message.role === "assistant" &&
              (message.metadata?.kind === "final_report" || message.metadata?.kind === "final-report")
          );
        const content = report?.content ?? "";
        if (content && this.isActiveSession()) {
          this.finalReportContent = content;
          this.renderFinalReport(content);
        }
      }
    } catch (error) {
      console.warn("[Review] 读取最终报告失败", error);
    }

    // 报告读取期间用户可能已切到别的会话：不要再把本轮收尾写到当前面板。
    if (!this.isActiveSession()) return;

    const monitorPanel = this.root.querySelector("#monitorPanel");
    if (monitorPanel && !this.errorSeen) {
      // 本轮成功时清掉上一轮可能残留的 error，避免标题与底色错位。
      monitorPanel.classList.remove("error");
      monitorPanel.classList.add("ok");
      const titleEl = monitorPanel.querySelector(".panel-title");
      if (titleEl) titleEl.textContent = "日志 · 运行正常";
    }
    this.appendUsageTotal();
    this.workflow.clearWaiting();
    stopReviewTimer(this.root);
    markAllStepsCompleted(this.root);
    this.finishRunning();
    void this.linked.refresh();
    window.dispatchEvent(new CustomEvent("dc:load-sessions"));
  }

  private handleStreamClosed(): void {
    if (!this.running) return;
    if (!this.reportFinalized && this.isActiveSession()) {
      // 流结束但没有终态事件：按旧版 done 收尾
      this.handleDone();
      return;
    }
    // 已切到其它会话：只结束后台任务状态，不再改写当前面板。
    this.finishRunning();
    window.dispatchEvent(new CustomEvent("dc:load-sessions"));
  }

  private handleDone(): void {
    this.workflow.clearWaiting();
    stopReviewTimer(this.root);
    setProgressStep(this.root, "reporting", "completed");
    markAllStepsCompleted(this.root);
    this.scanner?.endScanning();
    this.finishRunning();
    window.dispatchEvent(new CustomEvent("dc:load-sessions"));
  }

  private handleStreamError(error: unknown): void {
    if (!this.isActiveSession()) return;
    const message = error instanceof Error ? error.message : String(error);
    this.workflow.clearWaiting();
    this.appendConnectionError(message);
    const monitorPanel = this.root.querySelector("#monitorPanel");
    if (monitorPanel) {
      monitorPanel.classList.remove("ok");
      monitorPanel.classList.add("error");
      const titleEl = monitorPanel.querySelector(".panel-title");
      if (titleEl) titleEl.textContent = "日志 · 连接异常";
      monitorPanel.classList.remove("collapsed");
    }
    useAppStore.getState().setLayoutState("initial");
    stopReviewTimer(this.root);
    this.finishRunning();
  }

  // ── 报告渲染 ───────────────────────────────────────────────

  private cancelReportRender(): void {
    if (this.reportRenderFrame === null) return;
    cancelAnimationFrame(this.reportRenderFrame);
    this.reportRenderFrame = null;
  }

  private scheduleReportRender(): void {
    // 同一帧的增量只渲染一次；final 之后由 renderFinalReport 接管。
    if (this.reportFinalized || this.disposed || this.reportRenderFrame !== null) return;
    const runSeq = this.runSeq;
    this.reportRenderFrame = requestAnimationFrame(() => {
      this.reportRenderFrame = null;
      if (this.reportFinalized || this.disposed || runSeq !== this.runSeq || !this.isActiveSession()) return;
      const content = this.finalReportContent + this.pendingChunkContent;
      if (!content.trim()) return;
      const container = this.root.querySelector<HTMLElement>("#reportContainer");
      if (!container) return;
      delete container.dataset.reportPlaceholder;
      container.dataset.rawMarkdown = content;
      container.innerHTML = renderMarkdown(content);
      container.scrollTop = container.scrollHeight;
    });
  }

  private renderFinalReport(content: string): void {
    this.cancelReportRender();
    const container = this.root.querySelector<HTMLElement>("#reportContainer");
    if (!container) return;
    delete container.dataset.reportPlaceholder;
    container.dataset.rawMarkdown = content;
    container.innerHTML = renderMarkdown(content);
    requestAnimationFrame(() => {
      container.scrollTo({ top: 0, behavior: "smooth" });
      // 兜底：若仍被迟到的流式渲染打断，下一帧直接回到顶部。
      window.setTimeout(() => {
        if (container.scrollTop > 0) container.scrollTop = 0;
      }, 400);
    });
  }

  private appendPlannerWarning(message: string): void {
    const workflowEntries = this.root.querySelector("#workflowEntries");
    if (!workflowEntries) return;
    let stageContent = workflowEntries.querySelector(".workflow-stage-section:last-child .stage-content");
    if (!stageContent) {
      const header = document.createElement("div");
      header.className = "workflow-stage-section";
      header.innerHTML = `
        <div class="stage-header collapsible">
          <div class="stage-indicator" style="--stage-color: #8b5cf6">
            ${getIcon("plan")}
            <span>审查规划</span>
          </div>
          <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
        </div>
        <div class="stage-content"></div>
      `;
      workflowEntries.appendChild(header);
      stageContent = header.querySelector(".stage-content");
    }
    const warningEl = document.createElement("div");
    warningEl.className = "workflow-warning";
    warningEl.innerHTML = `
      <div class="warning-icon">${getIcon("alert-triangle")}</div>
      <span class="warning-text">${escapeHtml(message)}</span>
    `;
    stageContent?.appendChild(warningEl);
  }

  private appendUsageSummary(evt: FlatEvent): void {
    const monitorEntries = this.root.querySelector("#monitorContent");
    if (!monitorEntries) return;
    const callUsage = normalizeUsage((evt.call_usage ?? evt.usage ?? {}) as Record<string, unknown>);
    const sessionUsage = (evt.session_usage ?? null) as Record<string, unknown> | null;
    if (sessionUsage) {
      this.lastSessionUsage = normalizeUsage(sessionUsage);
    } else {
      this.lastSessionUsage = accumulateUsage(this.lastSessionUsage, callUsage);
    }
    const callIndex = evt.call_index;
    const usageStage = evt.usage_stage || "review";
    const item = document.createElement("div");
    item.className = "process-item api-call-card";
    const indexText = callIndex !== undefined && callIndex !== null ? `#${String(callIndex)}` : "";
    const stageBadge = usageStage ? `<span class="stage-badge">${escapeHtml(String(usageStage))}</span>` : "";
    item.innerHTML = `
      <div class="api-call-header">
        <div class="api-title-group">
          <svg class="icon api-icon"><use href="#icon-zap"></use></svg>
          <span class="api-title">API调用 ${indexText}</span>
          ${stageBadge}
        </div>
      </div>
      <div class="api-stats-grid">
        <div class="stat-row">
          <span class="stat-label">消耗</span>
          <span class="stat-value">${callUsage.total ?? "-"}</span>
          <span class="stat-detail"><span class="stat-in">↑${callUsage.in ?? "-"}</span> <span class="stat-out">↓${callUsage.out ?? "-"}</span></span>
        </div>
      </div>
    `;
    monitorEntries.appendChild(item);
  }

  private appendUsageTotal(): void {
    const totals = this.lastSessionUsage;
    if (!totals) return;
    const monitorEntries = this.root.querySelector("#monitorContent");
    if (!monitorEntries) return;
    const item = document.createElement("div");
    item.className = "process-item api-summary-card";
    item.innerHTML = `
      <div class="api-call-header">
        <div class="api-title-group">
          <svg class="icon api-icon"><use href="#icon-trending-up"></use></svg>
          <span class="api-title">Token 消耗总计</span>
        </div>
      </div>
      <div class="api-stats-grid">
        <div class="stat-row">
          <span class="stat-label">总计</span>
          <span class="stat-value">${totals.total ?? "-"}</span>
        </div>
      </div>
    `;
    monitorEntries.appendChild(item);
    this.lastSessionUsage = null;
  }

  private renderError(message: string): void {
    const monitorPanel = this.root.querySelector("#monitorPanel");
    if (monitorPanel) {
      monitorPanel.classList.remove("ok");
      monitorPanel.classList.add("error");
      const titleEl = monitorPanel.querySelector(".panel-title");
      if (titleEl) titleEl.textContent = "日志 · 运行异常";
      monitorPanel.classList.remove("collapsed");
    }
    const workflowEntries = this.root.querySelector("#workflowEntries");
    if (workflowEntries) {
      const errorEl = document.createElement("div");
      errorEl.className = "workflow-error";
      errorEl.innerHTML = `
        <div class="error-icon">${getIcon("x")}</div>
        <div class="error-content">
          <strong>发生错误</strong>
          <p>${escapeHtml(message)}</p>
        </div>
      `;
      workflowEntries.appendChild(errorEl);
    }
  }

  private appendConnectionError(message: string): void {
    const workflowEntries = this.root.querySelector("#workflowEntries");
    if (!workflowEntries) return;
    const errorEl = document.createElement("div");
    errorEl.className = "workflow-error";
    errorEl.innerHTML = `
      <div class="error-icon">${getIcon("x")}</div>
      <div class="error-content">
        <strong>连接中断</strong>
        <p>${escapeHtml(message)}</p>
        <button class="retry-btn" type="button">重试</button>
      </div>
    `;
    errorEl.querySelector(".retry-btn")?.addEventListener("click", () => void this.startReview());
    workflowEntries.appendChild(errorEl);
  }

  // ── 报告操作 ───────────────────────────────────────────────

  private copyReportContent(): void {
    const reportContainer = this.root.querySelector<HTMLElement>("#reportContainer");
    if (!reportContainer) return;
    const rawMarkdown = reportContainer.dataset.rawMarkdown;
    const contentToCopy = rawMarkdown || reportContainer.textContent || "";
    if (contentToCopy.trim()) {
      navigator.clipboard
        .writeText(contentToCopy)
        .then(() => showToast(rawMarkdown ? "已复制 Markdown 格式报告" : "报告内容已复制", "success"))
        .catch(() => showToast("复制失败", "error"));
    }
  }

  private reportGoBack(): void {
    const panel = this.root.querySelector("#reportPanel");
    if (panel?.classList.contains("fullscreen")) {
      panel.classList.remove("fullscreen");
      return;
    }
    if (useAppStore.getState().reportViewMode === "diff") {
      this.linked.switchReportView("report");
    }
    window.dispatchEvent(new CustomEvent("dc:return-new-workspace"));
  }
}
