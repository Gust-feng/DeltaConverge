import { getScanIssues } from "../../lib/api";
import { escapeHtml } from "../../lib/html";
import type { ScanIssue, ScanIssuesPage } from "../../types";

/**
 * 1:1 移植 legacy/ui_v1/static/modules/scanner-ui.js。
 *
 * 旧版关键“缺陷”被有意保留：
 * - 总览 tab 时 `.scanner-cards` 永远 display:none；
 * - 页面不存在 `.scanner-progress-header`，因此 progress 相关逻辑（徽章/计时元素）
 *   全部在 updateProgressIndicator 早退；
 * - warning/info 首次不拉明细，必须点“加载警告/加载信息”。
 */

type SeverityKey = "error" | "warning" | "info";
type ScannerStatus = "pending" | "running" | "completed" | "error";

export type ScannerRuntimeState = {
  name: string;
  status: ScannerStatus;
  file?: string;
  startTime?: number;
  duration_ms?: number;
  issue_count?: number;
  error_count?: number;
  error?: string;
  collapsed: boolean;
  currentFile?: string;
  currentLanguage?: string | null;
  filesProgress?: unknown[];
  filesCompleted?: number;
  totalIssues?: number;
  totalDuration?: number;
  languages?: Set<string>;
};

type SeverityCounts = { error: number; warning: number; info: number };

type ScannerSummaryState = {
  total_issues: number;
  by_severity: SeverityCounts;
  scanners_executed: number;
  scanners_failed: number;
  critical_issues: ScanIssue[];
  files_scanned?: number;
  files_total?: number;
  duration_ms?: number;
};

type PagingState = { offset: number; has_more: boolean; loading: boolean };

type ScannerUiState = {
  scanners: Map<string, ScannerRuntimeState>;
  isScanning: boolean;
  summary: ScannerSummaryState | null;
  issues: ScanIssue[];
  issuesBySeverity: {
    error: ScanIssue[];
    warning: ScanIssue[] | null;
    info: ScanIssue[] | null;
  };
  issuesPaging: Record<SeverityKey, PagingState>;
  currentSeverityFilter: string;
  collapsedFileGroups: Set<string>;
  scannedFiles: Map<
    string,
    { file: string; issues_count: number; language?: string; duration_ms?: number }
  >;
  scannersUsed: Set<string>;
  overviewCollapsed: {
    scanners: boolean;
    files: boolean;
    used_scanners: boolean;
  };
};

export type FileProgressInfo = {
  file?: string;
  language?: string;
  duration_ms?: number;
  issues_count?: number;
  progress?: number;
};

function createPaging(): PagingState {
  return { offset: 0, has_more: false, loading: false };
}

function createInitialState(): ScannerUiState {
  return {
    scanners: new Map(),
    isScanning: false,
    summary: null,
    issues: [],
    issuesBySeverity: { error: [], warning: null, info: null },
    issuesPaging: { error: createPaging(), warning: createPaging(), info: createPaging() },
    currentSeverityFilter: "all",
    collapsedFileGroups: new Set(),
    scannedFiles: new Map(),
    scannersUsed: new Set(),
    overviewCollapsed: { scanners: false, files: false, used_scanners: true },
  };
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function toIssues(value: unknown): ScanIssue[] {
  return Array.isArray(value) ? (value as ScanIssue[]) : [];
}

function toFiniteNumber(value: unknown): number | null {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

/** 汇总计数缺失（undefined/null/空串）时回退到数组长度。 */
function countValue(value: unknown, fallback: number): number {
  if (value === undefined || value === null || value === "") return fallback;
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function countSeverity(issues: ScanIssue[], severity: SeverityKey): number {
  let count = 0;
  for (const issue of issues) {
    if (String(issue.severity ?? "") === severity) count += 1;
  }
  return count;
}

export class ScannerController {
  private readonly state: ScannerUiState = createInitialState();

  // --- DOM References ---
  private containerEl: HTMLElement | null = null;
  private cardsContainerEl: HTMLElement | null = null;
  private summaryContainerEl: HTMLElement | null = null;
  private progressIndicatorEl: HTMLElement | null = null;
  private timerEl: HTMLElement | null = null;
  private stageMetaEl: HTMLElement | null = null;
  private scanStartTime: number | null = null;
  private scanTimerInterval: number | null = null;
  private preparingEl: HTMLElement | null = null;
  private issuesListEl: HTMLElement | null = null;
  private tabsContainerEl: HTMLElement | null = null;
  private issuesListClickBound = false;

  /** v2 分页接口需要 run_id；由审查页在拿到 run id 后调用 setRunId。 */
  private runId: string | null = null;

  // --- Initialization ---

  init(section: HTMLElement): void {
    this.containerEl = section;

    if (section) {
      this.cardsContainerEl = section.querySelector<HTMLElement>(".scanner-cards");
      this.summaryContainerEl = section.querySelector<HTMLElement>(".scanner-summary");
      // 旧版页面没有 .scanner-progress-header；这里保持同样的查询结果（null）。
      this.progressIndicatorEl = section.querySelector<HTMLElement>(".scanner-progress-header");
      this.timerEl = this.progressIndicatorEl
        ? this.progressIndicatorEl.querySelector<HTMLElement>(".scanner-timer")
        : null;
      this.stageMetaEl =
        section.querySelector<HTMLElement>("#scannerStageMeta") ||
        document.getElementById("scannerStageMeta");
      this.issuesListEl = section.querySelector<HTMLElement>(".scanner-issues-list");
      this.tabsContainerEl = section.querySelector<HTMLElement>(".scanner-tabs");

      if (this.issuesListEl && !this.issuesListClickBound) {
        this.issuesListEl.addEventListener("click", (e) => {
          const target = e.target as HTMLElement | null;
          const header = target?.closest<HTMLElement>(".file-group-header");
          if (!header) return;
          const group = header.closest<HTMLElement>(".scanner-file-group");
          if (!group) return;
          group.classList.toggle("collapsed");
          const fileKey = header.dataset.file;
          if (fileKey) {
            if (group.classList.contains("collapsed")) {
              this.state.collapsedFileGroups.add(fileKey);
            } else {
              this.state.collapsedFileGroups.delete(fileKey);
            }
          }
        });
        this.issuesListClickBound = true;
      }

      // Setup tab click handlers
      if (this.tabsContainerEl) {
        this.tabsContainerEl.addEventListener("click", (e) => {
          const target = e.target as HTMLElement | null;
          const tab = target?.closest<HTMLElement>(".scanner-tab");
          if (tab) {
            const severity = tab.dataset.severity ?? "";
            this.switchSeverityTab(severity);
          }
        });
      }
    }

    // Reset state on init
    this.reset();

    if (this.tabsContainerEl && this.issuesListEl) {
      this.switchSeverityTab(this.state.currentSeverityFilter || "all");
      this.renderStageMeta();
    }

    // 旧版是 window.ScannerUI 全局对象，模板中的 inline onclick 依赖它。
    if (typeof window !== "undefined") {
      (window as unknown as { ScannerUI?: ScannerController }).ScannerUI = this;
    }

    console.log("[ScannerUI] Initialized");
  }

  /** Reset the scanner UI state and clear displays. */
  reset(): void {
    this.state.scanners.clear();
    this.state.isScanning = false;
    this.state.summary = null;
    this.state.issues = [];
    this.state.issuesBySeverity = { error: [], warning: null, info: null };
    this.state.issuesPaging = { error: createPaging(), warning: createPaging(), info: createPaging() };
    this.state.currentSeverityFilter = "all";
    this.state.collapsedFileGroups.clear();
    this.state.scannedFiles.clear();
    this.state.scannersUsed.clear();
    this.state.overviewCollapsed.scanners = false;
    this.state.overviewCollapsed.files = false;
    this.state.overviewCollapsed.used_scanners = true;
    this.runId = null;

    this.stopScanTimer();
    this.scanStartTime = null;
    const metaEl = this.stageMetaEl || (typeof document !== "undefined" ? document.getElementById("scannerStageMeta") : null);
    if (metaEl) metaEl.textContent = "";

    // Clear DOM
    if (this.cardsContainerEl) {
      this.cardsContainerEl.innerHTML = "";
    }
    if (this.summaryContainerEl) {
      this.summaryContainerEl.style.display = "none";
      this.summaryContainerEl.innerHTML = "";
    }
    if (this.issuesListEl) {
      this.issuesListEl.innerHTML = "";
    }
    if (this.progressIndicatorEl) {
      this.updateProgressIndicator(false);
    }
    if (this.preparingEl) {
      try {
        this.preparingEl.remove();
      } catch {
        /* ignore */
      }
      this.preparingEl = null;
    }

    // 上一轮的统计数字不能带到新一轮扫描里。
    this.updateTabCounts({ error: 0, warning: 0, info: 0 });

    console.log("[ScannerUI] Reset");
  }

  /** 供回放等调用方获取扫描器 section。 */
  getSectionElement(): HTMLElement | null {
    return this.containerEl;
  }

  /** v2 issues 接口所需的 run id。null 表示尚未拿到 run id。 */
  setRunId(runId: string | null): void {
    this.runId = runId;
  }

  // --- Event Handlers ---

  handleScannerProgress(evt: Record<string, unknown>): void {
    if (!evt || !evt.scanner) {
      console.warn("[ScannerUI] Invalid scanner progress event:", evt);
      return;
    }

    const scannerName = String(evt.scanner);
    const status = String(evt.status ?? "");

    switch (status) {
      case "start":
        this.handleScannerStart(scannerName, evt);
        break;
      case "complete":
        this.handleScannerComplete(scannerName, evt);
        break;
      case "error":
        this.handleScannerError(scannerName, evt);
        break;
      default:
        console.warn("[ScannerUI] Unknown scanner status:", status);
    }
  }

  private handleScannerStart(scannerName: string, evt: Record<string, unknown>): void {
    const scannerState: ScannerRuntimeState = {
      name: scannerName,
      status: "running",
      file: typeof evt.file === "string" ? evt.file : evt.file ? String(evt.file) : "",
      startTime: toFiniteNumber(evt.timestamp) || Date.now(),
      collapsed: true,
    };

    this.state.scanners.set(scannerName, scannerState);
    this.state.isScanning = true;

    this.renderScannerCard(scannerState);
    this.updateProgressIndicator(true);
    this.startScanTimer();

    this.renderStageMeta();

    if (this.state.currentSeverityFilter === "all") {
      this.renderOverview();
    }

    console.log(`[ScannerUI] Scanner started: ${scannerName}`);
  }

  private handleScannerComplete(scannerName: string, evt: Record<string, unknown>): void {
    const scannerState: ScannerRuntimeState = this.state.scanners.get(scannerName) || {
      name: scannerName,
      status: "pending",
      collapsed: false,
    };

    scannerState.status = "completed";
    scannerState.duration_ms = toFiniteNumber(evt.duration_ms) ?? 0;
    scannerState.issue_count = toFiniteNumber(evt.issue_count) ?? 0;
    scannerState.error_count = toFiniteNumber(evt.error_count) ?? 0;

    this.state.scanners.set(scannerName, scannerState);

    this.checkAllScannersCompleted();
    this.updateScannerStatus(scannerName, "completed");

    if (this.state.currentSeverityFilter === "all") {
      this.renderOverview();
    }

    console.log(`[ScannerUI] Scanner completed: ${scannerName}, issues: ${scannerState.issue_count}`);
  }

  private handleScannerError(scannerName: string, evt: Record<string, unknown>): void {
    const scannerState: ScannerRuntimeState = this.state.scanners.get(scannerName) || {
      name: scannerName,
      status: "pending",
      collapsed: false,
    };

    scannerState.status = "error";
    scannerState.error = evt.error ? String(evt.error) : "Unknown error";

    this.state.scanners.set(scannerName, scannerState);

    this.checkAllScannersCompleted();
    this.updateScannerStatus(scannerName, "error");

    if (this.state.currentSeverityFilter === "all") {
      this.renderOverview();
    }

    console.log(`[ScannerUI] Scanner error: ${scannerName}, error: ${scannerState.error}`);
  }

  updateScanningFile(scannerName: string, file: string, language?: string | null): void {
    const scannerState = this.state.scanners.get(scannerName);
    if (!scannerState) return;

    scannerState.currentFile = file;
    scannerState.currentLanguage = language;

    if (!scannerState.filesProgress) {
      scannerState.filesProgress = [];
    }

    const cardEl = this.cardsContainerEl?.querySelector<HTMLElement>(`[data-scanner="${scannerName}"]`);
    if (cardEl) {
      const fileEl = cardEl.querySelector<HTMLElement>(".scanner-current-file");
      if (fileEl) {
        const shortFile = file.split(/[/\\]/).pop() ?? "";
        fileEl.textContent = shortFile;
        fileEl.title = file;
      }
    }
  }

  updateFileProgress(scannerName: string, fileInfo: FileProgressInfo): void {
    const scannerState = this.state.scanners.get(scannerName);
    if (!scannerState) return;

    const info = fileInfo || {};

    if (info.file) {
      const fp = String(info.file);
      this.state.scannedFiles.set(fp, {
        file: fp,
        issues_count: Number(info.issues_count || 0),
        language: info.language,
        duration_ms: info.duration_ms,
      });
    }

    if (!scannerState.filesCompleted) scannerState.filesCompleted = 0;
    if (!scannerState.totalIssues) scannerState.totalIssues = 0;
    if (!scannerState.totalDuration) scannerState.totalDuration = 0;
    if (!scannerState.languages) scannerState.languages = new Set();

    scannerState.filesCompleted += 1;
    scannerState.totalIssues += info.issues_count || 0;
    scannerState.totalDuration += info.duration_ms || 0;
    if (info.language) scannerState.languages.add(info.language);

    const cardEl = this.cardsContainerEl?.querySelector<HTMLElement>(`[data-scanner="${scannerName}"]`);
    if (cardEl) {
      const progressEl = cardEl.querySelector<HTMLElement>(".scanner-files-progress");
      if (progressEl && info.progress !== undefined) {
        progressEl.textContent = `${Math.round(info.progress * 100)}%`;
      }
    }

    if (this.state.currentSeverityFilter === "all") {
      this.renderOverview();
    }

    this.renderStageMeta();
  }

  toggleSection(): void {
    const section = document.getElementById("scannerWorkflowSection");
    if (section) {
      section.classList.toggle("collapsed");
    }
  }

  handleScannerSummary(evt: Record<string, unknown>): void {
    if (!evt) {
      console.warn("[ScannerUI] Invalid scanner summary event");
      return;
    }

    // setRunId 由审查页在收到 run id 后调用；若事件自带 run id 则顺手补齐。
    const eventRunId = evt.run_id ?? evt.runId;
    if (typeof eventRunId === "string" && eventRunId) {
      this.setRunId(eventRunId);
    }

    // 旧版固定读取 critical_issues（默认只下发 error 级）；缺失时兼容 issues 字段。
    const criticalIssues = toIssues(evt.critical_issues !== undefined ? evt.critical_issues : evt.issues);
    const providedBy = asRecord(evt.by_severity);
    // 扫描汇总计数缺失时按数组长度计算（旧版是 || 0）。
    const bySeverity: SeverityCounts = {
      error: countValue(providedBy?.error, countSeverity(criticalIssues, "error")),
      warning: countValue(providedBy?.warning, countSeverity(criticalIssues, "warning")),
      info: countValue(providedBy?.info, countSeverity(criticalIssues, "info")),
    };
    const totalIssues = countValue(
      evt.total_issues,
      bySeverity.error + bySeverity.warning + bySeverity.info
    );

    // Store summary data
    this.state.summary = {
      total_issues: totalIssues,
      by_severity: bySeverity,
      scanners_executed: this.state.scanners.size,
      scanners_failed: this.countFailedScanners(),
      critical_issues: criticalIssues,
    };

    if (Array.isArray(evt.scanners_used)) {
      for (const scanner of evt.scanners_used) {
        if (scanner) this.state.scannersUsed.add(String(scanner));
      }
    }
    const filesScanned = toFiniteNumber(evt.files_scanned);
    if (filesScanned !== null) this.state.summary.files_scanned = filesScanned;
    const filesTotal = toFiniteNumber(evt.files_total);
    if (filesTotal !== null) this.state.summary.files_total = filesTotal;
    const durationMs = toFiniteNumber(evt.duration_ms);
    if (durationMs !== null) this.state.summary.duration_ms = durationMs;

    // Store issues for filtering
    this.state.issues = criticalIssues;
    this.state.issuesBySeverity.error = this.state.issues;
    this.state.issuesPaging.error.offset = this.state.issues.length;
    const totalErrorCount = Number(this.state.summary.by_severity.error || 0);
    this.state.issuesPaging.error.has_more = Number.isFinite(totalErrorCount) && totalErrorCount > this.state.issues.length;
    this.state.issuesPaging.error.loading = false;
    this.state.issuesBySeverity.warning = null;
    this.state.issuesBySeverity.info = null;
    this.state.issuesPaging.warning = createPaging();
    this.state.issuesPaging.info = createPaging();

    // Update UI
    this.state.isScanning = false;
    this.updateProgressIndicator(false);
    this.stopScanTimer();
    this.renderSummaryCard(this.state.summary);

    this.updateTabCounts(this.state.summary.by_severity);
    this.switchSeverityTab(this.state.currentSeverityFilter || "all");

    console.log("[ScannerUI] Summary received:", this.state.summary);
  }

  private async fetchIssuesPage(severity: string, offset: number, limit: number): Promise<ScanIssuesPage> {
    if (!this.runId) throw new Error("missing_run_id");
    return getScanIssues(this.runId, severity, offset, limit);
  }

  private renderIssuesFetchPlaceholder(severity: string, loading: boolean, message?: string): void {
    if (!this.issuesListEl) return;
    const sevLabel = this.getSeverityLabel(severity);
    const btnText = loading ? "加载中..." : `加载${sevLabel}`;
    const disabled = loading ? "disabled" : "";
    this.issuesListEl.innerHTML = `
            <div class="scanner-issues-empty">
                <svg class="icon"><use href="#icon-info"></use></svg>
                <span>${escapeHtml(message || "该级别默认不下发明细")}</span>
                <button class="btn-primary scanner-load-btn" ${disabled} onclick="ScannerUI.loadIssuesForSeverity('${severity}')">${btnText}</button>
            </div>
        `;
  }

  private renderLoadMoreButton(severity: string, hasMore: boolean, loading: boolean): string {
    if (!hasMore) return "";
    const disabled = loading ? "disabled" : "";
    const text = loading ? "加载中..." : "加载更多";
    return `<div class="scanner-issues-loadmore"><button class="btn-primary" ${disabled} onclick="ScannerUI.loadMoreIssues('${severity}')">${text}</button></div>`;
  }

  async loadIssuesForSeverity(severity: string): Promise<void> {
    const sev = String(severity || "error") as SeverityKey;
    const paging = this.state.issuesPaging[sev];
    if (!paging) return;
    if (paging.loading) return;
    paging.loading = true;
    try {
      this.renderIssuesFetchPlaceholder(sev, true, "该级别默认不下发明细");
      const data = await this.fetchIssuesPage(sev, 0, 50);
      const list = Array.isArray(data.issues) ? data.issues : [];
      this.state.issuesBySeverity[sev] = list;
      this.state.issuesPaging[sev].offset = (data.offset || 0) + list.length;
      this.state.issuesPaging[sev].has_more = Boolean(data.has_more);
    } catch {
      this.state.issuesBySeverity[sev] = [];
      this.state.issuesPaging[sev].offset = 0;
      this.state.issuesPaging[sev].has_more = false;
      this.renderIssuesFetchPlaceholder(sev, false, "加载失败");
      return;
    } finally {
      this.state.issuesPaging[sev].loading = false;
    }

    if (this.state.currentSeverityFilter === sev) {
      const issues = this.state.issuesBySeverity[sev] || [];
      this.renderIssuesList(issues);
      if (this.issuesListEl) {
        const extra = this.renderLoadMoreButton(
          sev,
          this.state.issuesPaging[sev].has_more,
          this.state.issuesPaging[sev].loading
        );
        if (extra) this.issuesListEl.insertAdjacentHTML("beforeend", extra);
      }
    }
  }

  async loadMoreIssues(severity: string): Promise<void> {
    const sev = String(severity || "error") as SeverityKey;
    const paging = this.state.issuesPaging[sev];
    if (!paging || paging.loading || !paging.has_more) return;
    paging.loading = true;

    // 记录加载前的文件集合，用于判断哪些是新加载的
    const existingIssues = Array.isArray(this.state.issuesBySeverity[sev])
      ? (this.state.issuesBySeverity[sev] as ScanIssue[])
      : [];
    const existingFiles = new Set<string>();
    existingIssues.forEach((issue) => {
      const file = issue.file || (issue as { file_path?: string }).file_path || "Unknown";
      existingFiles.add(encodeURIComponent(String(file)));
    });

    try {
      // 一次加载2页（100条）
      const data = await this.fetchIssuesPage(sev, paging.offset || 0, 100);
      const list = Array.isArray(data.issues) ? data.issues : [];
      this.state.issuesBySeverity[sev] = existingIssues.concat(list);
      paging.offset = (data.offset || paging.offset || 0) + list.length;
      paging.has_more = Boolean(data.has_more);

      // 将新加载的文件默认设为折叠状态
      list.forEach((issue) => {
        const file = issue.file || (issue as { file_path?: string }).file_path || "Unknown";
        const fileKey = encodeURIComponent(String(file));
        if (!existingFiles.has(fileKey)) {
          this.state.collapsedFileGroups.add(fileKey);
        }
      });
    } catch {
      paging.has_more = false;
    } finally {
      paging.loading = false;
    }

    if (this.state.currentSeverityFilter === sev) {
      const issues = this.state.issuesBySeverity[sev] || [];
      this.renderIssuesList(issues);
      if (this.issuesListEl) {
        const extra = this.renderLoadMoreButton(
          sev,
          this.state.issuesPaging[sev].has_more,
          this.state.issuesPaging[sev].loading
        );
        if (extra) this.issuesListEl.insertAdjacentHTML("beforeend", extra);
      }
    }
  }

  // --- Rendering Methods ---

  renderScannerCard(scanner: ScannerRuntimeState): HTMLElement | null {
    if (!this.cardsContainerEl) return null;

    let cardEl = this.cardsContainerEl.querySelector<HTMLElement>(`[data-scanner="${scanner.name}"]`);

    if (!cardEl) {
      cardEl = document.createElement("div");
      cardEl.className = "scanner-card";
      cardEl.dataset.scanner = scanner.name;
      this.cardsContainerEl.appendChild(cardEl);
    }

    const statusClass = this.getStatusClass(scanner.status);
    const statusText = this.getStatusText(scanner.status);
    const collapsedClass = scanner.collapsed ? "collapsed" : "";

    const filesDisplay =
      scanner.filesCompleted !== undefined && scanner.file
        ? `${scanner.filesCompleted}/${scanner.file.replace(" files", "")} 文件`
        : scanner.file || "";

    const languagesDisplay =
      scanner.languages && scanner.languages.size > 0 ? Array.from(scanner.languages).join(", ") : "";

    const currentFileDisplay = scanner.currentFile ? scanner.currentFile.split(/[/\\]/).pop() ?? "" : "";

    cardEl.className = `scanner-card ${statusClass} ${collapsedClass}`;
    cardEl.innerHTML = `
            <div class="scanner-card-header" onclick="ScannerUI.toggleScannerDetails('${scanner.name}')">
                <span class="scanner-name">${escapeHtml(scanner.name === "static_scan" ? "静态分析" : scanner.name)}</span>
                <span class="scanner-status ${statusClass}">${statusText}</span>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="scanner-card-body">
                ${
                  filesDisplay
                    ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">扫描文件</span>
                    <span class="scanner-value">${escapeHtml(filesDisplay)}</span>
                </div>`
                    : ""
                }
                
                ${
                  currentFileDisplay && scanner.status === "running"
                    ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">当前文件</span>
                    <span class="scanner-value font-mono scanner-current-file" title="${escapeHtml(scanner.currentFile || "")}">${escapeHtml(currentFileDisplay)}</span>
                </div>`
                    : ""
                }
                
                ${
                  languagesDisplay
                    ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">语言</span>
                    <span class="scanner-value">${escapeHtml(languagesDisplay)}</span>
                </div>`
                    : ""
                }
                
                ${
                  scanner.duration_ms !== undefined
                    ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">耗时</span>
                    <span class="scanner-value">${this.formatDuration(scanner.duration_ms)}</span>
                </div>`
                    : ""
                }
                
                ${
                  scanner.issue_count !== undefined
                    ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">发现问题</span>
                    <span class="scanner-value badge ${scanner.issue_count > 0 ? (Number(scanner.error_count) > 0 ? "high" : "medium") : "low"}">${scanner.issue_count}</span>
                </div>`
                    : ""
                }
                
                ${
                  scanner.error_count !== undefined && scanner.error_count > 0
                    ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">严重错误</span>
                    <span class="scanner-value badge high">${scanner.error_count}</span>
                </div>`
                    : ""
                }
                
                ${scanner.error ? `<div class="scanner-error">${escapeHtml(scanner.error)}</div>` : ""}
            </div>
        `;

    return cardEl;
  }

  updateScannerStatus(scannerName: string, _status: string): void {
    const scanner = this.state.scanners.get(scannerName);
    if (scanner) {
      this.renderScannerCard(scanner);
    }
  }

  renderSummaryCard(summary: ScannerSummaryState): HTMLElement | null {
    if (!this.summaryContainerEl) return null;

    const noIssues = summary.total_issues === 0;

    // 如果有扫描器卡片，只显示简洁的状态提示
    if (this.state.scanners.size > 0) {
      if (noIssues) {
        this.summaryContainerEl.innerHTML = `
                    <div class="summary-inline success">✓ 未发现问题</div>
                `;
      } else {
        // 有问题时不显示汇总卡片，问题会显示在 issues-list 中
        this.summaryContainerEl.innerHTML = "";
        this.summaryContainerEl.style.display = "none";
        return this.summaryContainerEl;
      }
    } else {
      // 如果没有扫描器卡片（fallback 情况），显示完整汇总
      const hasErrors = summary.by_severity.error > 0;
      if (noIssues) {
        this.summaryContainerEl.innerHTML = `
                    <div class="summary-header success">✓ 扫描完成</div>
                    <div class="summary-message">未发现代码问题</div>
                `;
      } else {
        this.summaryContainerEl.innerHTML = `
                    <div class="summary-header ${hasErrors ? "has-errors" : ""}">扫描完成</div>
                    <div class="summary-stats">
                        <span class="stat error ${hasErrors ? "highlight" : ""}">${summary.by_severity.error} 错误</span>
                        <span class="stat warning">${summary.by_severity.warning} 警告</span>
                        <span class="stat info">${summary.by_severity.info} 提示</span>
                    </div>
                    <div class="summary-total">共 ${summary.total_issues} 个问题</div>
                `;
      }
    }

    this.summaryContainerEl.style.display = "block";

    return this.summaryContainerEl;
  }

  toggleScannerDetails(scannerName: string): void {
    const scanner = this.state.scanners.get(scannerName);
    if (!scanner) return;

    scanner.collapsed = !scanner.collapsed;
    this.state.scanners.set(scannerName, scanner);

    const cardEl = this.cardsContainerEl?.querySelector<HTMLElement>(`[data-scanner="${scannerName}"]`);
    if (cardEl) {
      cardEl.classList.toggle("collapsed", scanner.collapsed);
    }
  }

  // --- Helper Methods ---

  private updateProgressIndicator(isActive: boolean): void {
    if (!this.progressIndicatorEl) return;

    const statusBadge = this.progressIndicatorEl.querySelector<HTMLElement>(".scanner-status-badge");
    if (statusBadge) {
      statusBadge.textContent = isActive ? "进行中" : "已完成";
      statusBadge.className = `scanner-status-badge ${isActive ? "running" : "completed"}`;
    }
    // Ensure timer element exists
    if (this.progressIndicatorEl) {
      if (!this.timerEl) {
        this.timerEl = document.createElement("span");
        this.timerEl.className = "scanner-timer";
        this.timerEl.textContent = "00:00";
        this.progressIndicatorEl.appendChild(this.timerEl);
      }
      this.timerEl.style.display = isActive ? "inline" : "inline";
    }

    // Show the section when there are scanners or actively scanning
    // But do NOT hide it - let external code control hiding
    if (this.containerEl && (this.state.scanners.size > 0 || isActive)) {
      this.containerEl.style.display = "block";
    }
  }

  private renderStageMeta(): void {
    try {
      const metaEl = this.stageMetaEl || (typeof document !== "undefined" ? document.getElementById("scannerStageMeta") : null);
      if (!metaEl) return;

      const parts: string[] = [];

      const durationMs =
        this.state.summary && Number.isFinite(Number(this.state.summary.duration_ms))
          ? Number(this.state.summary.duration_ms)
          : this.scanStartTime
            ? Date.now() - this.scanStartTime
            : null;
      if (durationMs !== null && Number.isFinite(Number(durationMs))) {
        parts.push(`耗时 ${this.formatDuration(Number(durationMs))}`);
      }

      let filesScanned: number | null = null;
      let filesTotal: number | null = null;

      if (this.state.summary && Number.isFinite(Number(this.state.summary.files_scanned))) {
        filesScanned = Number(this.state.summary.files_scanned);
      }
      if (this.state.summary && Number.isFinite(Number(this.state.summary.files_total))) {
        filesTotal = Number(this.state.summary.files_total);
      }

      if (filesScanned === null && this.state.scannedFiles && this.state.scannedFiles.size) {
        filesScanned = this.state.scannedFiles.size;
      }

      if (filesTotal === null) {
        const staticScanner = this.state.scanners.get("static_scan");
        if (staticScanner && staticScanner.file) {
          const m = String(staticScanner.file).match(/^(\d+)\s+files\b/i);
          if (m) filesTotal = Number(m[1]);
        }
      }

      if (filesScanned !== null && Number.isFinite(Number(filesScanned))) {
        const tail = filesTotal !== null && Number.isFinite(Number(filesTotal)) ? `/${Number(filesTotal)}` : "";
        parts.push(`文件 ${Number(filesScanned)}${tail}`);
      } else if (filesTotal !== null && Number.isFinite(Number(filesTotal))) {
        parts.push(`文件 0/${Number(filesTotal)}`);
      }

      metaEl.textContent = parts.join(" · ");
    } catch {
      /* ignore */
    }
  }

  // Timer helpers (module scope)
  private startScanTimer(): void {
    try {
      if (this.scanTimerInterval) clearInterval(this.scanTimerInterval);
      this.scanStartTime = Date.now();
      if (!this.timerEl && this.progressIndicatorEl) {
        this.timerEl = document.createElement("span");
        this.timerEl.className = "scanner-timer";
        this.progressIndicatorEl.appendChild(this.timerEl);
      }
      if (this.timerEl) this.timerEl.textContent = "00:00";
      this.scanTimerInterval = window.setInterval(() => {
        const elapsed = Date.now() - (this.scanStartTime || Date.now());
        const sec = Math.floor(elapsed / 1000);
        const m = Math.floor(sec / 60)
          .toString()
          .padStart(2, "0");
        const s = (sec % 60).toString().padStart(2, "0");
        if (this.timerEl) this.timerEl.textContent = `${m}:${s}`;
        this.renderStageMeta();
      }, 1000);

      this.renderStageMeta();
    } catch {
      /* ignore */
    }
  }

  private stopScanTimer(): void {
    try {
      if (this.scanTimerInterval) {
        clearInterval(this.scanTimerInterval);
        this.scanTimerInterval = null;
      }
    } catch {
      /* ignore */
    }
  }

  private checkAllScannersCompleted(): void {
    let allCompleted = true;

    for (const scanner of this.state.scanners.values()) {
      if (scanner.status === "running" || scanner.status === "pending") {
        allCompleted = false;
        break;
      }
    }

    if (allCompleted && this.state.scanners.size > 0) {
      this.state.isScanning = false;
      this.updateProgressIndicator(false);
      this.stopScanTimer();
    }
  }

  private countFailedScanners(): number {
    let count = 0;
    for (const scanner of this.state.scanners.values()) {
      if (scanner.status === "error") {
        count++;
      }
    }
    return count;
  }

  private getStatusClass(status: string): string {
    switch (status) {
      case "running":
        return "running";
      case "completed":
        return "completed";
      case "error":
        return "error";
      default:
        return "pending";
    }
  }

  private getStatusText(status: string): string {
    switch (status) {
      case "running":
        return "扫描中...";
      case "completed":
        return "完成";
      case "error":
        return "错误";
      default:
        return "等待中";
    }
  }

  private formatDuration(ms: number): string {
    if (ms < 1000) {
      return `${ms}ms`;
    }
    return `${(ms / 1000).toFixed(1)}s`;
  }

  // --- Edge Case Handling ---

  handleScannerTimeout(scannerName: string, timeoutMs = 60000): void {
    const scanner = this.state.scanners.get(scannerName);
    if (!scanner || scanner.status !== "running") return;

    const elapsed = Date.now() - (scanner.startTime || Date.now());
    if (elapsed > timeoutMs) {
      scanner.status = "error";
      scanner.error = `扫描超时 (>${Math.round(timeoutMs / 1000)}s)`;
      this.state.scanners.set(scannerName, scanner);
      this.updateScannerStatus(scannerName, "error");
      this.checkAllScannersCompleted();
      console.warn(`[ScannerUI] Scanner ${scannerName} timed out after ${elapsed}ms`);
    }
  }

  checkAllTimeouts(timeoutMs = 60000): void {
    for (const [name, scanner] of this.state.scanners) {
      if (scanner.status === "running") {
        this.handleScannerTimeout(name, timeoutMs);
      }
    }
  }

  handleDisconnection(): void {
    if (this.state.isScanning) {
      for (const [name, scanner] of this.state.scanners) {
        if (scanner.status === "running") {
          const cardEl = this.cardsContainerEl?.querySelector<HTMLElement>(`[data-scanner="${name}"]`);
          if (cardEl) {
            cardEl.classList.add("disconnected");
          }
        }
      }
      console.warn("[ScannerUI] Network disconnection detected during scanning");
    }
  }

  handleReconnection(): void {
    const cards = this.cardsContainerEl?.querySelectorAll<HTMLElement>(".scanner-card.disconnected");
    if (cards) {
      cards.forEach((card) => card.classList.remove("disconnected"));
    }
    console.log("[ScannerUI] Network reconnected");
  }

  // --- Public API ---

  /** Get the current state (for testing purposes). */
  getState(): {
    scanners: Map<string, ScannerRuntimeState>;
    isScanning: boolean;
    summary: ScannerSummaryState | null;
  } {
    return {
      scanners: new Map(this.state.scanners),
      isScanning: this.state.isScanning,
      summary: this.state.summary ? { ...this.state.summary } : null,
    };
  }

  beginScanning(): void {
    if (this.progressIndicatorEl) {
      // Show preparing state first (no events yet)
      const statusBadge = this.progressIndicatorEl.querySelector<HTMLElement>(".scanner-status-badge");
      if (statusBadge) {
        statusBadge.textContent = "准备中";
        statusBadge.className = "scanner-status-badge preparing";
      }
      // Ensure section visible but collapsed by default
      if (this.containerEl) {
        this.containerEl.style.display = "block";
        this.containerEl.classList.add("collapsed");
      }
    }
    // Add preparing placeholder card
    if (this.cardsContainerEl && !this.preparingEl) {
      this.preparingEl = document.createElement("div");
      this.preparingEl.className = "scanner-preparing";
      this.preparingEl.innerHTML = `
                <div class="preparing-head">
                    <div class="spinner-small"></div>
                    <span class="preparing-title">正在准备扫描环境...</span>
                </div>
                <div class="preparing-body">预计需要几十秒，请稍候</div>
            `;
      this.cardsContainerEl.innerHTML = ""; // clear any residual
      this.cardsContainerEl.appendChild(this.preparingEl);
    }
    this.startScanTimer();
    this.renderStageMeta();
  }

  endScanning(): void {
    this.stopScanTimer();
    this.updateProgressIndicator(false);
  }

  /** Get all scanner names currently tracked. */
  getScannerNames(): string[] {
    return Array.from(this.state.scanners.keys());
  }

  // --- Tab and Issues List Functions ---

  private updateTabCounts(bySeverity: SeverityCounts): void {
    if (!this.tabsContainerEl) return;

    const computedTotal = (bySeverity.error || 0) + (bySeverity.warning || 0) + (bySeverity.info || 0);
    const total =
      this.state.summary && Number.isFinite(Number(this.state.summary.total_issues))
        ? Number(this.state.summary.total_issues)
        : computedTotal;

    const allTab = this.tabsContainerEl.querySelector<HTMLElement>('[data-severity="all"] .tab-count');
    const errorTab = this.tabsContainerEl.querySelector<HTMLElement>('[data-severity="error"] .tab-count');
    const warningTab = this.tabsContainerEl.querySelector<HTMLElement>('[data-severity="warning"] .tab-count');
    const infoTab = this.tabsContainerEl.querySelector<HTMLElement>('[data-severity="info"] .tab-count');

    if (allTab) allTab.textContent = String(total);
    if (errorTab) errorTab.textContent = String(bySeverity.error || 0);
    if (warningTab) warningTab.textContent = String(bySeverity.warning || 0);
    if (infoTab) infoTab.textContent = String(bySeverity.info || 0);
  }

  private renderOverview(): void {
    if (!this.issuesListEl) return;

    this.renderStageMeta();
    const scanners = Array.from(this.state.scanners.values());
    scanners.sort((a, b) => {
      const sa = String(a.name || "");
      const sb = String(b.name || "");
      return sa.localeCompare(sb);
    });

    const files = Array.from(this.state.scannedFiles.values());
    files.sort((a, b) => {
      const ia = Number(a.issues_count || 0);
      const ib = Number(b.issues_count || 0);
      if (ib !== ia) return ib - ia;
      return String(a.file || "").localeCompare(String(b.file || ""));
    });

    const usedScannerNames = this.state.scannersUsed.size
      ? Array.from(this.state.scannersUsed)
      : scanners.map((s) => s.name).filter(Boolean);

    const usedScanners = usedScannerNames.filter((n) => n && n !== "static_scan");

    const scannersCollapsed = Boolean(this.state.overviewCollapsed.scanners);
    const filesCollapsed = Boolean(this.state.overviewCollapsed.files);
    const usedScannersCollapsed = Boolean(this.state.overviewCollapsed.used_scanners);

    const scannersHeaderRight = `
            <span class="issue-count">${scanners.length || 0}</span>
        `;

    const filesHeaderRight = `
            <span class="issue-count">${files.length}</span>
        `;

    let scannersBody = "";
    if (!scanners.length && usedScannerNames.length) {
      scannersBody = `
                <div class="scanner-overview-list">
                    ${usedScannerNames
                      .map(
                        (n) => `
                        <div class="scanner-overview-row">
                            <div class="scanner-overview-main">
                                <span class="scanner-overview-name">${escapeHtml(n === "static_scan" ? "静态分析" : n)}</span>
                            </div>
                            <div class="scanner-overview-right">
                                <span class="scanner-status pending">等待中</span>
                            </div>
                        </div>
                    `
                      )
                      .join("")}
                </div>
            `;
    } else if (scanners.length) {
      scannersBody = `
                <div class="scanner-overview-list">
                    ${scanners
                      .map((s) => {
                        const statusClass = this.getStatusClass(s.status);
                        const statusText = this.getStatusText(s.status);
                        const details: string[] = [];
                        const currentFile = s.currentFile ? String(s.currentFile).split(/[/\\]/).pop() : "";
                        if (currentFile && s.status === "running") details.push(`当前 ${currentFile}`);
                        if (s.languages && s.languages.size > 0)
                          details.push(`语言 ${Array.from(s.languages).join(", ")}`);
                        if (Number.isFinite(Number(s.duration_ms)))
                          details.push(`耗时 ${this.formatDuration(Number(s.duration_ms))}`);
                        if (Number.isFinite(Number(s.issue_count))) details.push(`问题 ${Number(s.issue_count)}`);
                        if (Number.isFinite(Number(s.error_count)) && Number(s.error_count) > 0)
                          details.push(`错误 ${Number(s.error_count)}`);

                        return `
                            <div class="scanner-overview-row">
                                <div class="scanner-overview-main">
                                    <span class="scanner-overview-name">${escapeHtml(s.name === "static_scan" ? "静态分析" : s.name)}</span>
                                    ${details.length ? `<span class="scanner-overview-sub">${escapeHtml(details.join(" · "))}</span>` : ""}
                                </div>
                                <div class="scanner-overview-right">
                                    <span class="scanner-status ${statusClass}">${escapeHtml(statusText)}</span>
                                </div>
                            </div>
                        `;
                      })
                      .join("")}
                </div>
            `;
    } else {
      scannersBody = `
                <div class="scanner-overview-empty">暂无扫描器数据</div>
            `;
    }

    const usedScannersBlock = usedScanners.length
      ? `
            <div class="scanner-overview-block nested ${usedScannersCollapsed ? "collapsed" : ""}" data-overview-block="used_scanners">
                <div class="scanner-overview-block-header" data-overview-toggle="used_scanners">
                    <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                    <span class="block-title">扫描器</span>
                    <span class="block-right"><span class="issue-count">${usedScanners.length}</span></span>
                </div>
                <div class="scanner-overview-block-body">
                    <div class="scanner-overview-list">
                        ${usedScanners
                          .map(
                            (n) => `
                            <div class="scanner-overview-row">
                                <div class="scanner-overview-main">
                                    <span class="scanner-overview-name">${escapeHtml(n)}</span>
                                </div>
                            </div>
                        `
                          )
                          .join("")}
                    </div>
                </div>
            </div>
        `
      : "";

    let filesBody = "";
    if (!files.length) {
      filesBody = `
                <div class="scanner-overview-empty">暂无文件数据</div>
            `;
    } else {
      const errorFiles = new Set<string>();
      try {
        const errors = Array.isArray(this.state.issuesBySeverity && this.state.issuesBySeverity.error)
          ? this.state.issuesBySeverity.error
          : [];
        for (const it of errors) {
          const f = it && (it.file || (it as { file_path?: string }).file_path);
          if (f) errorFiles.add(String(f));
        }
      } catch {
        /* ignore */
      }

      filesBody = `
                <div class="scanner-files-list">
                    ${files
                      .map((f) => {
                        const fp = String(f.file || "");
                        const base = fp.split(/[/\\]/).pop() || fp;
                        const issues = Number(f.issues_count || 0);
                        const duration = Number(f.duration_ms);
                        const durationText = Number.isFinite(duration) ? this.formatDuration(duration) : "-";

                        const isErrorFile = errorFiles.has(fp);
                        const issueTone = isErrorFile ? "is-error" : issues > 0 ? "is-has" : "is-zero";
                        return `
                            <div class="scanner-file-row" title="${escapeHtml(fp)}">
                                <span class="file-name">${escapeHtml(base)}</span>
                                <span class="file-metrics">
                                    <span class="file-duration">
                                        <svg class="icon clock"><use href="#icon-clock"></use></svg>
                                        <span>${escapeHtml(durationText)}</span>
                                    </span>
                                    <span class="issue-count ${issueTone}">${issues}</span>
                                </span>
                            </div>
                        `;
                      })
                      .join("")}
                </div>
            `;
    }

    this.issuesListEl.innerHTML = `
            <div class="scanner-overview">
                <div class="scanner-overview-section">
                    <div class="scanner-overview-block ${scannersCollapsed ? "collapsed" : ""}" data-overview-block="scanners">
                        <div class="scanner-overview-block-header" data-overview-toggle="scanners">
                            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                            <span class="block-title">扫描情况</span>
                            <span class="block-right">${scannersHeaderRight}</span>
                        </div>
                        <div class="scanner-overview-block-body">
                            ${usedScannersBlock}
                            ${scannersBody}
                        </div>
                    </div>

                    <div class="scanner-overview-block ${filesCollapsed ? "collapsed" : ""}" data-overview-block="files">
                        <div class="scanner-overview-block-header" data-overview-toggle="files">
                            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                            <span class="block-title">扫描文件列表</span>
                            <span class="block-right">${filesHeaderRight}</span>
                        </div>
                        <div class="scanner-overview-block-body">
                            ${filesBody}
                        </div>
                    </div>
                </div>
            </div>
        `;

    const toggles = this.issuesListEl.querySelectorAll<HTMLElement>("[data-overview-toggle]");
    toggles.forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-overview-toggle");
        if (key === "scanners") this.state.overviewCollapsed.scanners = !this.state.overviewCollapsed.scanners;
        if (key === "files") this.state.overviewCollapsed.files = !this.state.overviewCollapsed.files;
        if (key === "used_scanners")
          this.state.overviewCollapsed.used_scanners = !this.state.overviewCollapsed.used_scanners;
        this.renderOverview();
      });
    });
  }

  switchSeverityTab(severity: string): void {
    if (!this.tabsContainerEl) return;

    this.state.currentSeverityFilter = severity;

    const tabs = this.tabsContainerEl.querySelectorAll<HTMLElement>(".scanner-tab");
    tabs.forEach((tab) => {
      if (tab.dataset.severity === severity) {
        tab.classList.add("active");
      } else {
        tab.classList.remove("active");
      }
    });

    let visibleCount = 0;
    if (severity === "all") {
      if (this.cardsContainerEl) this.cardsContainerEl.style.display = "none";
      this.renderOverview();
      visibleCount =
        this.state.summary && Number.isFinite(Number(this.state.summary.total_issues))
          ? Number(this.state.summary.total_issues)
          : this.state.issues
            ? this.state.issues.length
            : 0;
    } else {
      if (this.cardsContainerEl) this.cardsContainerEl.style.display = "none";
      if (severity === "error") {
        const filteredIssues = this.state.issuesBySeverity.error || [];
        visibleCount = filteredIssues.length;
        this.renderIssuesList(filteredIssues);
        const extra = this.renderLoadMoreButton(
          "error",
          this.state.issuesPaging.error.has_more,
          this.state.issuesPaging.error.loading
        );
        if (this.issuesListEl && extra) this.issuesListEl.insertAdjacentHTML("beforeend", extra);
      } else {
        const sev = severity as SeverityKey;
        const loaded = this.state.issuesBySeverity[sev];
        if (loaded === null) {
          const by = this.state.summary && this.state.summary.by_severity ? this.state.summary.by_severity : null;
          const rawCount = by ? by[sev] : 0;
          const cnt = Number(rawCount || 0);
          visibleCount = cnt;
          if (cnt > 0) {
            this.renderIssuesFetchPlaceholder(severity, false, "该级别默认不下发明细");
          } else {
            this.renderIssuesList([]);
          }
        } else {
          const list = Array.isArray(loaded) ? loaded : [];
          visibleCount = list.length;
          this.renderIssuesList(list);
          const paging = this.state.issuesPaging[sev];
          const extra = paging ? this.renderLoadMoreButton(severity, paging.has_more, paging.loading) : "";
          if (this.issuesListEl && extra) this.issuesListEl.insertAdjacentHTML("beforeend", extra);
        }
      }
    }

    console.log(`[ScannerUI] Switched to ${severity} tab, showing ${visibleCount} issues`);
  }

  private renderIssuesList(issues: ScanIssue[]): void {
    if (!this.issuesListEl) return;

    if (!issues || issues.length === 0) {
      // 没有问题时保持空白，避免与summary区域重复
      this.issuesListEl.innerHTML = "";
      return;
    }

    const issuesByFile = new Map<string, ScanIssue[]>();
    issues.forEach((issue) => {
      const file = issue.file || (issue as { file_path?: string }).file_path || "Unknown";
      const list = issuesByFile.get(String(file)) || [];
      list.push(issue);
      issuesByFile.set(String(file), list);
    });

    const severityRank = (sev: string): number => {
      if (sev === "error") return 0;
      if (sev === "warning") return 1;
      if (sev === "info") return 2;
      return 3;
    };

    const toInt = (v: unknown): number => {
      const n = Number(v);
      return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
    };

    const fileEntries = Array.from(issuesByFile.entries()).map(([file, fileIssues]) => {
      let errorCount = 0;
      let warningCount = 0;
      let infoCount = 0;
      for (const it of fileIssues) {
        const s = it.severity || "info";
        if (s === "error") errorCount++;
        else if (s === "warning") warningCount++;
        else infoCount++;
      }
      return { file, fileIssues, errorCount, warningCount, infoCount, total: fileIssues.length };
    });

    fileEntries.sort((a, b) => {
      if (b.errorCount !== a.errorCount) return b.errorCount - a.errorCount;
      if (b.warningCount !== a.warningCount) return b.warningCount - a.warningCount;
      if (b.total !== a.total) return b.total - a.total;
      return String(a.file).localeCompare(String(b.file));
    });

    let html = "";
    for (const entry of fileEntries) {
      const file = entry.file;
      const fileIssues = entry.fileIssues;
      const fileName = file.split(/[/\\]/).pop() || file;
      const fileKey = encodeURIComponent(file);
      const collapsed = this.state.collapsedFileGroups.has(fileKey);

      const sortedIssues = [...fileIssues].sort((x, y) => {
        const sx = x.severity || "info";
        const sy = y.severity || "info";
        const sr = severityRank(sx) - severityRank(sy);
        if (sr !== 0) return sr;
        const lx = toInt(x.line || x.start_line);
        const ly = toInt(y.line || y.start_line);
        if (lx !== ly) return lx - ly;
        const cx = toInt(x.column);
        const cy = toInt(y.column);
        if (cx !== cy) return cx - cy;
        return String(x.rule_id || (x as { rule?: string }).rule || "").localeCompare(
          String(y.rule_id || (y as { rule?: string }).rule || "")
        );
      });

      html += `
                <div class="scanner-file-group ${collapsed ? "collapsed" : ""}" data-file="${fileKey}">
                    <div class="file-group-header" data-file="${fileKey}">
                        <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                        <span class="file-name" title="${escapeHtml(file)}">${escapeHtml(fileName)}</span>
                        <span class="issue-counts">
                            ${entry.errorCount ? `<span class="count error">${entry.errorCount}</span>` : ""}
                            ${entry.warningCount ? `<span class="count warning">${entry.warningCount}</span>` : ""}
                            ${entry.infoCount ? `<span class="count info">${entry.infoCount}</span>` : ""}
                        </span>
                        <span class="issue-count">${entry.total}</span>
                    </div>
                    <div class="file-issues">
                        ${sortedIssues.map((issue) => this.renderIssueCard(issue)).join("")}
                    </div>
                </div>
            `;
    }

    this.issuesListEl.innerHTML = html;
  }

  private renderIssueCard(issue: ScanIssue): string {
    const severity = issue.severity || "info";
    const line = issue.line || issue.start_line || "-";
    const column = issue.column || "-";
    const message = issue.message || "No description";
    const ruleId = issue.rule_id || (issue as { rule?: string }).rule || "";
    const scanner = issue.scanner || "";

    return `
            <div class="issue-card severity-${severity}">
                <div class="issue-header">
                    <span class="severity-badge ${severity}">${this.getSeverityLabel(severity)}</span>
                    <span class="issue-location">行 ${line}${column !== "-" ? `:${column}` : ""}</span>
                    ${ruleId ? `<span class="issue-rule" title="${escapeHtml(ruleId)}">${escapeHtml(ruleId)}</span>` : ""}
                </div>
                <div class="issue-message">${escapeHtml(message)}</div>
                ${scanner ? `<div class="issue-scanner">via ${escapeHtml(scanner)}</div>` : ""}
            </div>
        `;
  }

  private getSeverityLabel(severity: string): string {
    switch (severity) {
      case "error":
        return "错误";
      case "warning":
        return "警告";
      case "info":
        return "信息";
      default:
        return severity;
    }
  }
}
