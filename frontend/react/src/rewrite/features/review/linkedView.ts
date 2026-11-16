import { getCommitRange, getDiffFiles, getFileDiff, getSessionDiffSnapshot } from "../../lib/api";
import { escapeHtml } from "../../lib/html";

import { useAppStore } from "../../state/appStore";

const SEPARATOR_REGEX = /^[-*_]{3,}$/;
const PUNCTUATION_ONLY_REGEX = /^[-*_=~#:.。,，;；!！?？\s]+$/;
const INVALID_PLACEHOLDERS = ["(无)", "无", "none", "N/A", "n/a", "-", "–", "—", "...", "…"];

type SeverityCounts = { error: number; warning: number; info: number };

function normalizeReportPath(value: unknown): string {
  let text = String(value || "").trim();
  if (!text) return "";
  text = text.replace(/\\/g, "/");
  if (text.startsWith("a/")) text = text.slice(2);
  else if (text.startsWith("b/")) text = text.slice(2);
  if (text.startsWith("./")) text = text.slice(2);
  if (text.startsWith("/")) text = text.slice(1);
  return text;
}

function normalizeSeverityValue(value: unknown): keyof SeverityCounts {
  const severity = String(value || "").toLowerCase();
  if (severity === "error" || severity === "fatal") return "error";
  if (severity === "warning" || severity === "warn") return "warning";
  return "info";
}

function isInvalidMessageContent(message: unknown): boolean {
  if (!message) return true;
  const text = String(message).trim();
  if (!text) return true;
  if (INVALID_PLACEHOLDERS.includes(text)) return true;
  if (SEPARATOR_REGEX.test(text)) return true;
  const cleaned = text.replace(/^(?:建议|问题)\s*[:：]\s*/, "").trim();
  if (SEPARATOR_REGEX.test(cleaned) || INVALID_PLACEHOLDERS.includes(cleaned)) return true;
  return PUNCTUATION_ONLY_REGEX.test(text);
}

function summarizeIssues(issues: unknown): SeverityCounts {
  const counts: SeverityCounts = { error: 0, warning: 0, info: 0 };
  if (!Array.isArray(issues)) return counts;
  for (const item of issues as Array<Record<string, unknown>>) {
    if (isInvalidMessageContent(item?.message)) continue;
    counts[normalizeSeverityValue(item?.severity)] += 1;
  }
  return counts;
}

function issueSummaryClass(counts: SeverityCounts | null): string {
  if (!counts) return "";
  if (counts.error > 0) return "has-error";
  if (counts.warning > 0) return "has-warning";
  if (counts.info > 0) return "has-info";
  return "clean";
}

function renderDiffLines(diffText: unknown): string {
  const lines = String(diffText || "")
    .replace(/\r\n/g, "\n")
    .split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  return lines
    .map((line) => {
      const first = line ? line[0] : "";
      let cls = "diff-line";
      if (first === "+") cls += " diff-add";
      else if (first === "-") cls += " diff-del";
      else cls += " diff-ctx";
      return `<span class="${cls}">${escapeHtml(line)}</span>`;
    })
    .join("");
}

function renderSeverityBadges(counts: SeverityCounts, emptyText = ""): string {
  const badges: string[] = [];
  if (counts.error) badges.push(`<span class="severity-badge error">ERROR ${counts.error}</span>`);
  if (counts.warning) badges.push(`<span class="severity-badge warning">WARN ${counts.warning}</span>`);
  if (counts.info) badges.push(`<span class="severity-badge info">INFO ${counts.info}</span>`);
  if (!badges.length && emptyText) badges.push(`<span class="diff-unit-status clean">${escapeHtml(emptyText)}</span>`);
  return badges.join("");
}

export class LinkedView {
  private readonly root: HTMLElement;
  private linked: Record<string, unknown> | null = null;
  private units: Array<Record<string, unknown>> | null = null;
  private files: Array<Record<string, unknown>> | null = null;
  private selectedFile: string | null = null;
  private mode = "working";
  private projectRoot: string | null = null;
  private contextKey: string | null = null;
  private loadedKey: string | null = null;
  private loadedAt = 0;
  private pendingKey: string | null = null;
  private pendingLoad: Promise<void> | null = null;
  private loadAbort: AbortController | null = null;
  private loadSeq = 0;
  private disposed = false;

  constructor(root: HTMLElement) {
    this.root = root;
    this.root.querySelector("#reportDiffFileList")?.addEventListener("click", (event) => {
      if ((event.target as HTMLElement).closest("[data-retry-diff]")) {
        void this.loadReportDiffFiles(true);
        return;
      }
      const item = (event.target as HTMLElement).closest<HTMLElement>(".file-list-item[data-path]");
      if (!item?.dataset.path) return;
      void this.loadReportFileDiff(item.dataset.path);
    });
  }

  dispose(): void {
    this.disposed = true;
    this.loadSeq += 1;
    this.loadAbort?.abort();
  }

  switchReportView(mode: "report" | "diff"): void {
    const reportContainer = this.root.querySelector<HTMLElement>("#reportContainer");
    const diffViewContainer = this.root.querySelector<HTMLElement>("#diffViewContainer");
    const toggleReport = this.root.querySelector("#viewToggleReport");
    const toggleDiff = this.root.querySelector("#viewToggleDiff");
    const rightPanel = this.root.querySelector<HTMLElement>("#rightPanel");
    const reportPanel = this.root.querySelector<HTMLElement>("#reportPanel");
    if (!reportContainer || !diffViewContainer) return;

    useAppStore.getState().setReportViewMode(mode);

    if (mode === "report") {
      toggleReport?.classList.add("active");
      toggleDiff?.classList.remove("active");
      if (diffViewContainer.style.display !== "none") {
        diffViewContainer.classList.add("exiting");
        window.setTimeout(() => {
          diffViewContainer.classList.remove("exiting");
          reportContainer.style.display = "";
          diffViewContainer.style.display = "none";
        }, 280);
      } else {
        reportContainer.style.display = "";
        diffViewContainer.style.display = "none";
      }
      if (rightPanel) {
        rightPanel.style.overflow = "hidden";
        rightPanel.style.width = "";
        window.setTimeout(() => {
          rightPanel.style.opacity = "";
          rightPanel.style.overflow = "";
        }, 300);
      }
      if (reportPanel) reportPanel.style.width = "";
      return;
    }

    reportContainer.style.display = "none";
    diffViewContainer.style.display = "";
    diffViewContainer.classList.add("entering");
    window.setTimeout(() => diffViewContainer.classList.remove("entering"), 350);
    toggleReport?.classList.remove("active");
    toggleDiff?.classList.add("active");
    if (rightPanel) {
      rightPanel.style.opacity = "0";
      rightPanel.style.overflow = "hidden";
      window.setTimeout(() => {
        rightPanel.style.width = "0";
      }, 200);
    }
    if (reportPanel) reportPanel.style.width = "100%";
    void this.loadReportDiffFiles();
  }

  async refresh(): Promise<void> {
    await this.loadReportDiffFiles(true);
  }

  private getContextKey(): string {
    const state = useAppStore.getState();
    return JSON.stringify([state.projectRoot, state.sessionId, state.runId, state.diffMode, state.commitFrom, state.commitTo]);
  }

  loadReportDiffFiles(force = false): Promise<void> {
    if (this.disposed) return Promise.resolve();
    const key = this.getContextKey();
    const fileListEl = this.root.querySelector<HTMLElement>("#reportDiffFileList");
    if (!fileListEl) return Promise.resolve();

    if (this.contextKey !== key) {
      this.contextKey = key;
      this.loadedKey = null;
      this.files = null;
      this.units = null;
      this.linked = null;
      this.selectedFile = null;
      this.projectRoot = null;
      this.mode = "working";
      const contentEl = this.root.querySelector<HTMLElement>("#reportDiffContent");
      if (contentEl) contentEl.innerHTML = '<div class="empty-state">请选择文件查看变更</div>';
    }
    if (!force && this.pendingKey === key && this.pendingLoad) return this.pendingLoad;
    if (!force && this.loadedKey === key && Date.now() - this.loadedAt < 60_000) return Promise.resolve();
    if (this.loadedKey !== key) fileListEl.innerHTML = '<div class="empty-state">加载中...</div>';

    const seq = ++this.loadSeq;
    this.loadAbort?.abort();
    const controller = new AbortController();
    this.loadAbort = controller;
    const timeout = globalThis.setTimeout(() => controller.abort(), 15_000);
    const isCurrent = () => !this.disposed && seq === this.loadSeq && key === this.getContextKey();
    this.pendingKey = key;
    const pending = this.fetchReportDiffFiles(isCurrent, controller.signal).then(() => {
      if (!isCurrent()) return;
      this.loadedKey = key;
      this.loadedAt = Date.now();
      if (this.selectedFile && useAppStore.getState().reportViewMode === "diff") {
        if (this.files?.some((file) => file.path === this.selectedFile)) {
          void this.loadReportFileDiff(this.selectedFile);
        } else {
          this.selectedFile = null;
          const contentEl = this.root.querySelector<HTMLElement>("#reportDiffContent");
          if (contentEl) contentEl.innerHTML = '<div class="empty-state">请选择文件查看变更</div>';
        }
      }
    }).catch((error: unknown) => {
      if (!isCurrent() || this.loadedKey === key) return;
      const message = controller.signal.aborted ? "请求超时，请检查本地服务后重试" : error instanceof Error ? error.message : String(error);
      fileListEl.innerHTML = `<div class="empty-state">加载失败: ${escapeHtml(message)}<br><button type="button" class="btn-secondary" data-retry-diff>重试</button></div>`;
    }).finally(() => {
      globalThis.clearTimeout(timeout);
      if (this.pendingLoad === pending) {
        this.loadAbort = null;
        this.pendingLoad = null;
        this.pendingKey = null;
      }
    });
    this.pendingLoad = pending;
    return pending;
  }

  private async fetchReportDiffFiles(isCurrent: () => boolean, signal: AbortSignal): Promise<void> {
    const state = useAppStore.getState();
    let projectRoot = state.projectRoot;
    if (state.sessionId) {
      const session = await getSessionDiffSnapshot(state.sessionId, signal);
      if (!isCurrent()) return;
      projectRoot = session.metadata.project_root ?? projectRoot;
      // 已有审查快照时只展示该轮数据，不能回退到当前工作区的变更。
      if (session.latest_run_id) {
        const linked = (session.static_scan_linked || null) as Record<string, unknown> | null;
        this.linked = linked && Object.keys(linked).length ? linked : null;
        this.units = (this.linked?.diff_units ?? session.diff_units ?? []) as Array<Record<string, unknown>>;
        this.files = (session.diff_files ?? []) as Array<Record<string, unknown>>;
        this.mode = "snapshot";
        this.projectRoot = projectRoot;
        this.renderReportDiffFileList(this.files);
        return;
      }
    }

    const fileListEl = this.root.querySelector<HTMLElement>("#reportDiffFileList");
    if (!projectRoot) {
      if (fileListEl && isCurrent()) fileListEl.innerHTML = '<div class="empty-state">请先选择项目</div>';
      return;
    }
    const analyzed = state.diffMode === "commit" && state.commitFrom
      ? await getCommitRange(projectRoot, state.commitFrom, state.commitTo, signal)
      : await getDiffFiles(projectRoot, state.diffMode === "commit" ? "auto" : state.diffMode, signal);
    if (!isCurrent()) return;
    if (analyzed.error && !String(analyzed.error).includes("No changes detected")) {
      throw new Error(String(analyzed.error).includes("not a git repository") ? "此目录不是 Git 仓库" : String(analyzed.error));
    }
    this.mode = analyzed.detected_mode ?? (state.diffMode === "auto" ? "working" : state.diffMode);
    this.projectRoot = projectRoot;
    this.files = (analyzed.files ?? []) as Array<Record<string, unknown>>;
    this.renderReportDiffFileList(this.files);
  }

  private getFileIssueSummary(filePath: string): { scanner: SeverityCounts; llm: SeverityCounts; total: SeverityCounts } {
    const scanner: SeverityCounts = { error: 0, warning: 0, info: 0 };
    const llm: SeverityCounts = { error: 0, warning: 0, info: 0 };
    const total: SeverityCounts = { error: 0, warning: 0, info: 0 };
    const linked = this.linked || {};
    const unitIssues = (linked.unit_issues ?? null) as Record<string, unknown> | null;
    const unitLlm = (linked.unit_llm_suggestions ?? null) as Record<string, unknown> | null;
    const units = this.units ?? [];
    if ((!unitIssues && !unitLlm) || !units.length) return { scanner, llm, total };
    const target = normalizeReportPath(filePath);
    for (const unit of units) {
      if (normalizeReportPath(unit.file_path) !== target) continue;
      const unitId = String(unit.unit_id ?? unit.id ?? "");
      if (!unitId) continue;
      const c1 = summarizeIssues(unitIssues?.[unitId]);
      const c2 = summarizeIssues(unitLlm?.[unitId]);
      scanner.error += c1.error;
      scanner.warning += c1.warning;
      scanner.info += c1.info;
      llm.error += c2.error;
      llm.warning += c2.warning;
      llm.info += c2.info;
    }
    total.error = scanner.error + llm.error;
    total.warning = scanner.warning + llm.warning;
    total.info = scanner.info + llm.info;
    return { scanner, llm, total };
  }

  private renderReportDiffFileList(files: Array<Record<string, unknown>>): void {
    const fileListEl = this.root.querySelector<HTMLElement>("#reportDiffFileList");
    if (!fileListEl) return;
    if (!files || files.length === 0) {
      fileListEl.innerHTML = '<div class="empty-state">无文件变更</div>';
      return;
    }
    fileListEl.innerHTML = "";

    const linked = (this.linked || {}) as Record<string, unknown>;
    if (typeof linked.llm_unmapped_count !== "undefined") {
      const total = Number(linked.llm_suggestions_total || 0);
      const mapped = Number(linked.llm_mapped_count || 0);
      const unmapped = Number(linked.llm_unmapped_count || 0);
      const unmappedList = Array.isArray(linked.llm_unmapped_suggestions)
        ? (linked.llm_unmapped_suggestions as Array<Record<string, unknown>>)
        : [];
      if (total || unmapped) {
        const banner = document.createElement("div");
        banner.className = "diff-linked-banner" + (unmapped > 0 ? " has-unmapped" : "");
        const parts: string[] = [];
        if (total) parts.push(`总计 ${total}`);
        parts.push(`已映射 ${mapped}`);
        if (unmapped) parts.push(`未映射 ${unmapped}`);

        let unmappedDetailsHtml = "";
        if (unmapped > 0) {
          const valid = unmappedList.filter((item) => !isInvalidMessageContent(item?.message));
          if (valid.length > 0) {
            const items = valid
              .slice(0, 20)
              .map((item) => {
                const file = String(item.file || item.attempted_file || "(无文件)");
                const line = item.line || item.start_line || "-";
                const message = String(item.message || "(无消息)");
                const reason = String(item.unmapped_reason || "unknown");
                const reasonText =
                  ({ no_file_path: "无文件路径", no_file_match: "文件不匹配", no_unit_match: "行号不匹配", exception: "处理异常" } as Record<string, string>)[reason] || reason;
                return `<div class="unmapped-item">
                  <div class="unmapped-item-header">
                    <span class="unmapped-file" title="${escapeHtml(file)}">${escapeHtml(file.split("/").pop() || file)}</span>
                    <span class="unmapped-line">L${escapeHtml(String(line))}</span>
                    <span class="unmapped-reason">${escapeHtml(reasonText)}</span>
                  </div>
                  <div class="unmapped-message">${escapeHtml(message)}</div>
                </div>`;
              })
              .join("");
            unmappedDetailsHtml = `<div class="unmapped-details" style="display:none">${items}${valid.length > 20 ? `<div class="unmapped-more">... 还有 ${valid.length - 20} 条</div>` : ""}</div>`;
          } else {
            unmappedDetailsHtml =
              '<div class="unmapped-details" style="display:none"><div class="unmapped-placeholder">未映射内容均为无效消息（已过滤）</div></div>';
          }
        }

        banner.innerHTML = `
          <div class="diff-linked-banner-header"${unmapped > 0 ? ' style="cursor:pointer"' : ""}>
            <div class="diff-linked-banner-row">
              <div class="diff-linked-banner-title">LLM建议映射</div>
              ${unmapped > 0 ? '<span class="toggle-indicator"><span class="toggle-arrow"></span></span>' : ""}
            </div>
            <div class="diff-linked-banner-meta">${escapeHtml(parts.join(" | "))}</div>
          </div>
          ${unmappedDetailsHtml}
        `;
        banner.title = `LLM建议总数 ${total}，已映射 ${mapped}，未映射 ${unmapped}`;
        if (unmapped > 0) {
          banner.querySelector(".diff-linked-banner-header")?.addEventListener("click", () => {
            const details = banner.querySelector<HTMLElement>(".unmapped-details");
            const indicator = banner.querySelector(".toggle-indicator");
            if (!details) return;
            const expanded = details.style.display !== "none";
            details.style.display = expanded ? "none" : "block";
            indicator?.classList.toggle("expanded", !expanded);
          });
        }
        fileListEl.appendChild(banner);
      }
    }

    files.forEach((file, index) => {
      const requestPath = String(file.path || "Unknown File");
      const displayPath = String(file.display_path || requestPath);
      const changeType = String(file.change_type || "modify");
      const linked = (this.linked || {}) as Record<string, unknown>;
      const hasMapping = Boolean(linked.unit_issues || linked.unit_llm_suggestions);
      const counts = this.getFileIssueSummary(requestPath);
      const llmTotal = counts.llm.error + counts.llm.warning + counts.llm.info;
      const focusCounts = llmTotal > 0 ? counts.llm : counts.scanner;
      const fileClass = hasMapping ? issueSummaryClass(focusCounts) : "";
      const item = document.createElement("div");
      item.className = "file-list-item";
      if (fileClass && fileClass !== "clean") item.classList.add(fileClass);
      item.dataset.path = requestPath;
      item.style.animationDelay = `${index * 40}ms`;

      let iconName = "file";
      let statusClass = "status-modify";
      if (changeType === "add") {
        iconName = "plus";
        statusClass = "status-add";
      } else if (changeType === "delete") {
        iconName = "trash";
        statusClass = "status-delete";
      }
      const splitIndex = displayPath.lastIndexOf("/");
      const fileName = splitIndex >= 0 ? displayPath.slice(splitIndex + 1) : displayPath;
      const dirPath = splitIndex >= 0 ? displayPath.slice(0, splitIndex) : "";

      let badges = "";
      if (hasMapping) {
        const compact: string[] = [];
        const scanTitle = `静态扫描: ${counts.scanner.error} 错误, ${counts.scanner.warning} 警告, ${counts.scanner.info} 提示`;
        if (llmTotal) {
          const llmDetails: string[] = [];
          if (counts.llm.error) llmDetails.push(`${counts.llm.error} 错误`);
          if (counts.llm.warning) llmDetails.push(`${counts.llm.warning} 警告`);
          if (counts.llm.info) llmDetails.push(`${counts.llm.info} 建议`);
          const llmTitle = `AI 审查建议: ${llmDetails.join(", ") || `${llmTotal} 条`}`;
          const scanTotal = counts.scanner.error + counts.scanner.warning + counts.scanner.info;
          compact.push(
            `<span class="severity-badge llm" title="${escapeHtml(llmTitle + (scanTotal > 0 ? `\n${scanTitle}` : ""))}">✦ ${escapeHtml(String(llmTotal))}</span>`
          );
        } else {
          if (counts.scanner.error) compact.push(`<span class="severity-badge error">E${counts.scanner.error}</span>`);
          if (counts.scanner.warning) compact.push(`<span class="severity-badge warning">W${counts.scanner.warning}</span>`);
          if (counts.scanner.info) compact.push(`<span class="severity-badge info">I${counts.scanner.info}</span>`);
        }
        badges = compact.join("");
      }

      item.innerHTML = `
        <div class="file-item-row">
          <span class="file-icon ${statusClass}"><svg class="icon icon-${iconName}"><use href="#icon-${iconName}"></use></svg></span>
          <div class="file-info">
            <div class="file-name" title="${escapeHtml(displayPath)}">${escapeHtml(fileName)}</div>
            <div class="file-path" title="${escapeHtml(dirPath)}">${escapeHtml(dirPath)}</div>
          </div>
          <div class="file-issue-badges">${badges}</div>
        </div>
      `;
      fileListEl.appendChild(item);
    });
  }

  private async loadReportFileDiff(filePath: string): Promise<void> {
    const contentEl = this.root.querySelector<HTMLElement>("#reportDiffContent");
    if (!contentEl) return;
    const key = this.getContextKey();
    const seq = this.loadSeq;
    const isCurrent = () => !this.disposed && key === this.getContextKey() && seq === this.loadSeq && this.selectedFile === filePath;
    this.selectedFile = filePath;
    this.root.querySelectorAll<HTMLElement>("#reportDiffFileList .file-list-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.path === filePath);
    });
    contentEl.innerHTML = '<div class="empty-state">加载中...</div>';

    const projectRoot = this.projectRoot || useAppStore.getState().projectRoot;
    if (!projectRoot) {
      contentEl.innerHTML = '<div style="padding:1rem;color:red;">请先选择项目</div>';
      return;
    }

    const units = (this.units ?? []).filter((unit) => normalizeReportPath(unit.file_path) === normalizeReportPath(filePath));
    if (units.length > 0) {
      units.sort((a, b) => {
        const ah = (a.hunk_range ?? {}) as Record<string, unknown>;
        const bh = (b.hunk_range ?? {}) as Record<string, unknown>;
        return Number(ah.new_start || 0) - Number(bh.new_start || 0);
      });
      this.renderUnits(contentEl, filePath, units);
      return;
    }

    if (this.mode === "snapshot") {
      contentEl.innerHTML = '<div class="empty-state">该文件未保存变更快照</div>';
      return;
    }

    try {
      const state = useAppStore.getState();
      const data = await getFileDiff({ filePath, projectRoot, mode: this.mode, commitFrom: state.commitFrom, commitTo: state.commitTo });
      if (!isCurrent()) return;
      if (data.error) {
        contentEl.innerHTML = `<div style="padding:1rem;color:red;">${escapeHtml(data.error)}</div>`;
        return;
      }
      const diffText = data.diff_text || data.diff_content || "";
      if (window.Diff2HtmlUI && diffText.trim()) {
        contentEl.innerHTML = `
          <div class="diff-header" style="padding: 1rem; border-bottom: 1px solid var(--border);">
            <h3 title="${escapeHtml(filePath)}" style="margin: 0; font-size: 0.95rem;">${escapeHtml(filePath)}</h3>
          </div>
          <div id="report-diff-ui-container" style="padding: 0;"></div>
        `;
        const target = contentEl.querySelector<HTMLElement>("#report-diff-ui-container");
        if (target) {
          const diff2htmlUi = new window.Diff2HtmlUI(target, diffText, {
            drawFileList: false,
            fileListToggle: false,
            fileContentToggle: false,
            matching: "lines",
            outputFormat: "side-by-side",
            synchronisedScroll: true,
            highlight: true,
            renderNothingWhenEmpty: false,
          });
          diff2htmlUi.draw();
          diff2htmlUi.highlightCode();
        }
      } else {
        const formattedDiff = diffText ? diffText.replace(/\r\n/g, "\n") : "No content";
        contentEl.innerHTML = `
          <div style="padding:1rem;">
            <h3 style="margin: 0 0 1rem 0;">${escapeHtml(filePath)}</h3>
            <pre style="background:var(--bg-secondary, #f4f4f5);padding:1rem;overflow:auto;border-radius:8px;"><code>${escapeHtml(formattedDiff)}</code></pre>
          </div>
        `;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (isCurrent()) contentEl.innerHTML = `<div style="padding:1rem;color:red;">Error: ${escapeHtml(message)}</div>`;
    }
  }

  private renderUnits(container: HTMLElement, filePath: string, units: Array<Record<string, unknown>>): void {
    const linked = (this.linked || {}) as Record<string, unknown>;
    const unitIssues = (linked.unit_issues ?? {}) as Record<string, unknown>;
    const unitLlm = (linked.unit_llm_suggestions ?? {}) as Record<string, unknown>;
    const hasStaticScan = typeof linked.unit_issues !== "undefined";

    container.innerHTML = `<div class="diff-header" style="padding:1rem;border-bottom:1px solid var(--border);"><h3 title="${escapeHtml(filePath)}" style="margin:0;font-size:0.95rem;">${escapeHtml(filePath)}</h3></div><div class="diff-units-container"></div>`;
    const unitsContainer = container.querySelector<HTMLElement>(".diff-units-container");
    if (!unitsContainer) return;

    for (const unit of units) {
      const unitId = String(unit.unit_id ?? unit.id ?? "");
      const hunk = (unit.hunk_range ?? {}) as Record<string, unknown>;
      const start = Number(hunk.new_start || 0);
      const lines = Number(hunk.new_lines || 1);
      const end = start === 0 ? 0 : start + Math.max(lines, 1) - 1;
      const issues = summarizeIssues(unitIssues[unitId]);
      const llm = summarizeIssues(unitLlm[unitId]);
      const llmTotal = llm.error + llm.warning + llm.info;
      const scanTotal = issues.error + issues.warning + issues.info;
      const hasLlm = llmTotal > 0;
      const focusCounts = hasLlm ? llm : issues;
      const unitClass = hasLlm || hasStaticScan ? issueSummaryClass(focusCounts) : "waiting";

      let badges = "";
      if (hasLlm) {
        badges += '<span class="diff-unit-status llm">LLM</span>';
        badges += renderSeverityBadges(llm);
        if (hasStaticScan && scanTotal) {
          badges += `<span class="diff-unit-status scan" title="SCAN E${issues.error} W${issues.warning} I${issues.info}">SCAN ${scanTotal}</span>`;
        }
      }
      if (hasStaticScan) {
        if (!hasLlm) {
          badges += '<span class="diff-unit-status scan">SCAN</span>';
          badges += renderSeverityBadges(issues, "CLEAN");
        }
      } else {
        badges += '<span class="diff-unit-status waiting">SCANNING</span>';
      }

      const unitEl = document.createElement("div");
      unitEl.className = `diff-unit ${unitClass}`;
      unitEl.dataset.unitId = unitId;
      unitEl.innerHTML = `
        <div class="diff-unit-meta">
          <span class="diff-unit-range">L${start}-${end}</span>
          <div class="diff-unit-badges">${badges}</div>
        </div>
        <pre class="diff-unit-code"><code>${renderDiffLines(unit.unified_diff_with_lines || unit.unified_diff || "")}</code></pre>
        <div class="diff-unit-issues">
          ${this.renderLlmBlock(unitId, unitLlm[unitId])}
          ${this.renderScanBlock(unitId, unitIssues[unitId], hasStaticScan)}
        </div>
      `;
      unitsContainer.appendChild(unitEl);
    }
  }

  private renderLlmBlock(unitId: string, raw: unknown): string {
    if (!Array.isArray(raw) || raw.length === 0) return "";
    const groups = new Map<string, { severity: string; start: number; end: number; originStart: number; originEnd: number; items: Array<Record<string, unknown>> }>();
    for (const issue of raw as Array<Record<string, unknown>>) {
      if (isInvalidMessageContent(issue.message)) continue;
      const severity = normalizeSeverityValue(issue.severity);
      const start = Number(issue.start_line ?? issue.line ?? 0);
      const end = Number(issue.end_line ?? start);
      const originStart = Number(issue.origin_start_line ?? start);
      const originEnd = Number(issue.origin_end_line ?? end);
      const key = `${severity}|${start}|${end}|${originStart}|${originEnd}`;
      const group = groups.get(key) ?? { severity, start, end, originStart, originEnd, items: [] };
      group.items.push(issue);
      groups.set(key, group);
    }
    if (groups.size === 0) return "";
    const cards = Array.from(groups.values())
      .map((group) => {
        const messages = group.items
          .slice(0, 50)
          .map((issue) => `<div class="issue-message-item">${escapeHtml(String(issue.message ?? ""))}</div>`)
          .join("");
        const via = escapeHtml(String(group.items[0]?.scanner || group.items[0]?.source || "LLM"));
        const lineRange =
          group.start && group.end && String(group.end) !== String(group.start)
            ? `${group.start}-${group.end}`
            : String(group.start || "-");
        const originRange =
          group.originStart && group.originEnd && String(group.originEnd) !== String(group.originStart)
            ? `${group.originStart}-${group.originEnd}`
            : group.originStart
              ? String(group.originStart)
              : "";
        const title = originRange && originRange !== lineRange ? ` title="原始: ${escapeHtml(originRange)}"` : "";
        const countBadge =
          group.items.length > 1
            ? `<span class="issue-rule" title="聚合 ${group.items.length} 条">×${group.items.length}</span>`
            : "";
        return `<div class="issue-card severity-${group.severity}">
          <div class="issue-header">
            <span class="severity-badge ${group.severity}">${group.severity}</span>
            <span class="issue-location"${title}>行 ${escapeHtml(lineRange)}</span>
            ${countBadge}
          </div>
          <div class="issue-message">${messages}</div>
          ${via ? `<div class="issue-scanner">via ${via}</div>` : ""}
        </div>`;
      })
      .join("");
    return `<div class="diff-unit-issues-section llm"><div class="diff-unit-issues-title">LLM关注</div><div class="diff-unit-issues-body">${cards}</div></div>`;
  }

  private renderScanBlock(_unitId: string, raw: unknown, hasStaticScan: boolean): string {
    const items = Array.isArray(raw) ? (raw as Array<Record<string, unknown>>) : [];
    const valid = items.filter((item) => !isInvalidMessageContent(item.message));
    const scanTotal = summarizeIssues(items);
    const total = scanTotal.error + scanTotal.warning + scanTotal.info;

    let body: string;
    if (!hasStaticScan) {
      body = '<div class="diff-unit-issues-empty">静态分析：等待扫描完成</div>';
    } else if (valid.length) {
      body = valid
        .slice(0, 50)
        .map((issue) => {
          const severity = normalizeSeverityValue(issue.severity);
          const line = Number(issue.start_line ?? issue.line ?? 0);
          const column = issue.column;
          const ruleId = String(issue.rule_id ?? issue.rule ?? "");
          const scanner = String(issue.scanner ?? "");
          const source = String(issue.source ?? "");
          const via = scanner || (source ? (source.toLowerCase() === "llm" ? "LLM" : source) : "");
          const location = column !== undefined && column !== null && String(column) !== "-" ? `行 ${line}:${column}` : `行 ${line}`;
          return `<div class="issue-card severity-${severity}">
            <div class="issue-header">
              <span class="severity-badge ${severity}">${severity}</span>
              <span class="issue-location">${escapeHtml(location)}</span>
              ${ruleId ? `<span class="issue-rule" title="${escapeHtml(ruleId)}">${escapeHtml(ruleId)}</span>` : ""}
            </div>
            <div class="issue-message">${escapeHtml(String(issue.message ?? "No description"))}</div>
            ${via ? `<div class="issue-scanner">via ${escapeHtml(via)}</div>` : ""}
          </div>`;
        })
        .join("");
    } else {
      body = '<div class="diff-unit-issues-empty">静态分析：未发现命中问题</div>';
    }

    return `<details class="diff-unit-issues-section scan"><summary><span class="diff-unit-issues-title">规则扫描</span><span class="diff-unit-issues-meta">${total}</span></summary><div class="diff-unit-issues-body">${body}</div></details>`;
  }
}
