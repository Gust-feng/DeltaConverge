import { escapeHtml, formatFileSizeGlobal, getIcon, truncateTextGlobal } from "../../lib/html";
import { renderMarkdown } from "../../lib/markdown";
import type { ScannerController } from "../scanner/ScannerController";

/**
 * 1:1 移植 legacy/ui_v1/static/modules/workflow-replay.js。
 *
 * 回放是同步一次性渲染：没有 500ms Markdown debounce、没有 rAF、没有自动滚动。
 * thought 默认折叠；工具参数是原始 JSON 代码块（截 500），而非实时 SSE 的 pill。
 */

type ReplayEvent = Record<string, unknown>;

type StageInfo = { title: string; icon: string; color: string };

type ToolEntry = {
  key: string;
  card: HTMLElement;
  statusEl: HTMLElement | null;
  argsEl: HTMLElement | null;
  outputEl: HTMLElement | null;
  metaEl: HTMLElement | null;
  name: string;
};

// 无内容的技术stage列表（完全隐藏，不创建UI块）
const HIDDEN_STAGES = [
  // 文件处理阶段（pipeline控制）
  "diff_parse", // 文件差异解析
  "review_units", // 审查单元分析
  "rule_layer", // 规则匹配
  "review_index", // 索引构建

  // 意图分析阶段的pipeline控制层（实际内容在intent stage）
  "intent_analysis", // 意图分析阶段标记（无内容，内容在intent中）

  // 规划阶段的子步骤（pipeline控制）
  "fusion", // 融合（planner子步骤）
  "context_provider", // 上下文提供（planner子步骤）
  "context_bundle", // 上下文打包（planner子步骤）
  "final_context_plan", // 最终计划（planner子步骤）
];

// Stage normalization helpers
const STAGE_ALIAS_MAP: Record<string, string> = {
  reviewer: "review",
  intent_analysis: "intent",
  // planner sub-stages (pipeline/internal steps) should be grouped under planner in replay
  fusion: "planner",
  context_provider: "planner",
  context_bundle: "planner",
  final_context_plan: "planner",
};
const VISIBLE_STAGES = ["intent", "planner", "review"];

function shouldShowStage(stage: string): boolean {
  const normalized = normalizeStage(stage);
  if (!VISIBLE_STAGES.includes(normalized)) return false;
  return !HIDDEN_STAGES.includes(normalized);
}

function normalizeStage(stage: unknown): string {
  if (!stage) return "review";
  const key = String(stage);
  return STAGE_ALIAS_MAP[key] || key;
}

// 阶段信息映射（为每个后端stage提供唯一标题）
function getStageInfo(stage: string): StageInfo {
  const stageMap: Record<string, StageInfo> = {
    // 意图分析相关
    intent_analysis: { title: "意图分析", icon: "bot", color: "#6366f1" },
    intent: { title: "意图分析", icon: "bot", color: "#6366f1" },

    // 规划相关
    planner: { title: "审查规划", icon: "plan", color: "#8b5cf6" },

    // 审查相关
    review: { title: "代码审查", icon: "review", color: "#10b981" },
    reviewer: { title: "代码审查", icon: "review", color: "#10b981" },

    // 默认
    default: { title: "处理中", icon: "settings", color: "#64748b" },
  };
  return stageMap[stage] || stageMap.default;
}

function formatToolArgsGlobal(_toolName: string, rawArgs: unknown): string {
  if (rawArgs === undefined || rawArgs === null || rawArgs === "") {
    return '<span class="tool-args-empty">无参数</span>';
  }

  let text = "";
  if (typeof rawArgs === "string") {
    text = rawArgs;
  } else {
    try {
      text = JSON.stringify(rawArgs, null, 2) ?? String(rawArgs);
    } catch {
      text = String(rawArgs);
    }
  }

  // Truncate if too long
  if (text.length > 500) {
    text = text.slice(0, 500) + "...";
  }

  return `<pre class="tool-args-code"><code>${escapeHtml(text)}</code></pre>`;
}

function renderToolContentGlobal(toolName: string, rawContent: unknown): string {
  if (rawContent === undefined || rawContent === null || rawContent === "") {
    return '<span class="tool-empty">无返回内容</span>';
  }

  let data: unknown = rawContent;
  if (typeof rawContent === "string") {
    try {
      data = JSON.parse(rawContent);
    } catch {
      // keep raw
    }
  }

  const obj = data && typeof data === "object" ? (data as Record<string, unknown>) : null;

  // Error handling
  if (obj && obj.error) {
    return `<div class="tool-result error">${escapeHtml(String(obj.error))}</div>`;
  }

  const name = (toolName || "").toLowerCase();

  // read_file_hunk: Code snippet display
  if (name.includes("read_file_hunk") || (name.includes("read_file") && obj && obj.snippet_with_line_numbers)) {
    const filePath = String(obj?.path || "");
    const ctxStart = obj?.context_start || obj?.start_line || 1;
    const ctxEnd = obj?.context_end || obj?.end_line || ctxStart;
    const totalLines = obj?.total_lines || "?";
    const snippet = String(obj?.snippet_with_line_numbers || obj?.snippet || "");

    return `
            <div class="tool-code-block">
                <div class="code-header">
                    <span class="code-path" title="${escapeHtml(filePath)}">${getIcon("folder")} ${escapeHtml(filePath.split(/[/\\]/).pop() || filePath)}</span>
                    <span class="code-range">行 ${ctxStart}-${ctxEnd} / 共 ${totalLines} 行</span>
                </div>
                <pre class="code-content"><code>${escapeHtml(snippet)}</code></pre>
            </div>
        `;
  }

  // read_file_info: File info card
  if (name.includes("read_file_info") || (obj && obj.line_count !== undefined && obj.language !== undefined)) {
    const filePath = String(obj?.path || "");
    const size = obj?.size_bytes != null ? formatFileSizeGlobal(Number(obj.size_bytes)) : "?";
    const lang = String(obj?.language || "unknown");
    const lines = obj?.line_count || 0;

    return `
            <div class="tool-file-info">
                <div class="file-info-header">
                    ${getIcon("folder")}
                    <span class="file-name">${escapeHtml(filePath.split(/[/\\]/).pop() || filePath)}</span>
                </div>
                <div class="file-info-grid">
                    <div class="info-item"><span class="label">路径</span><span class="value">${escapeHtml(truncateTextGlobal(filePath, 60))}</span></div>
                    <div class="info-item"><span class="label">大小</span><span class="value">${escapeHtml(size)}</span></div>
                    <div class="info-item"><span class="label">语言</span><span class="value">${escapeHtml(lang)}</span></div>
                    <div class="info-item"><span class="label">行数</span><span class="value">${lines}</span></div>
                </div>
            </div>
        `;
  }

  // search: Search results
  if (name.includes("search") && obj && Array.isArray(obj.matches)) {
    const query = String(obj.query || "");
    const matches = obj.matches as Array<Record<string, unknown>>;
    if (matches.length === 0) {
      return `<div class="tool-search-empty">${getIcon("search")} 未找到匹配: <code>${escapeHtml(query)}</code></div>`;
    }
    const items = matches
      .slice(0, 20)
      .map((m) => {
        const fileName = String(m.path || "").split(/[/\\]/).pop() || String(m.path || "");
        return `
                <div class="search-match">
                    <span class="match-file">${escapeHtml(fileName)}</span>
                    <span class="match-line">:${m.line || 0}</span>
                    <code class="match-snippet">${escapeHtml(truncateTextGlobal(m.snippet || "", 120))}</code>
                </div>
            `;
      })
      .join("");
    return `
            <div class="tool-search-results">
                <div class="search-header">${getIcon("search")} 搜索 <code>${escapeHtml(query)}</code> — ${matches.length} 条匹配</div>
                <div class="search-list">${items}</div>
            </div>
        `;
  }

  // list_directory: Directory listing
  if (
    name.includes("list_dir") ||
    name.includes("directory") ||
    (obj && obj.directories !== undefined && obj.files !== undefined)
  ) {
    const dirPath = String(obj?.path || "");
    const dirs = Array.isArray(obj?.directories) ? (obj?.directories as unknown[]) : [];
    const files = Array.isArray(obj?.files) ? (obj?.files as unknown[]) : [];
    const dirItems = dirs
      .slice(0, 30)
      .map((d) => `<span class="dir-item">${getIcon("folder")} ${escapeHtml(d)}</span>`)
      .join("");
    const fileItems = files.slice(0, 50).map((f) => `<span class="file-item">${escapeHtml(f)}</span>`).join("");
    return `
            <div class="tool-directory">
                <div class="dir-header">${getIcon("folder")} ${escapeHtml(dirPath || "/")}</div>
                <div class="dir-content">${dirItems}${fileItems}</div>
            </div>
        `;
  }

  // Default: JSON or text display
  if (typeof data === "object") {
    const jsonStr = JSON.stringify(data, null, 2) ?? "";
    return `<pre class="tool-json"><code>${escapeHtml(truncateTextGlobal(jsonStr, 3000))}</code></pre>`;
  }

  return `<pre class="tool-text"><code>${escapeHtml(truncateTextGlobal(String(rawContent), 2000))}</code></pre>`;
}

export function replayScannerEvents(events: Record<string, unknown>[], scanner: ScannerController): void {
  if (!scanner) return;
  if (!events || events.length === 0) return;

  // 过滤扫描器相关事件（包括 static_scan_* 系列）
  const scannerEvents = events.filter(
    (e) =>
      e.type === "scanner_progress" ||
      e.type === "scanner_issues_summary" ||
      e.type === "static_scan_start" ||
      e.type === "static_scan_file_start" ||
      e.type === "static_scan_file_done" ||
      e.type === "static_scan_complete"
  );

  if (scannerEvents.length === 0) return;

  // 重置扫描器状态
  scanner.reset();

  // 显示扫描器面板（不主动折叠）
  const scannerSection = scanner.getSectionElement() || document.getElementById("scannerWorkflowSection");
  if (scannerSection) {
    scannerSection.style.display = "block";
  }

  const optionalNumber = (value: unknown): number | undefined => {
    if (value === undefined || value === null || value === "") return undefined;
    const num = Number(value);
    return Number.isFinite(num) ? num : undefined;
  };

  // 回放每个扫描器事件
  scannerEvents.forEach((evt) => {
    try {
      if (evt.type === "scanner_progress") {
        scanner.handleScannerProgress(evt);
      } else if (evt.type === "scanner_issues_summary") {
        scanner.handleScannerSummary(evt);
      } else if (evt.type === "static_scan_start") {
        // 转换为 scanner_progress 格式
        scanner.handleScannerProgress({
          status: "start",
          scanner: "static_scan",
          file: `${evt.files_total || 0} files`,
          timestamp: evt.timestamp,
        });
      } else if (evt.type === "static_scan_file_start") {
        // 更新当前扫描文件，不创建新卡片
        scanner.updateScanningFile(
          "static_scan",
          String(evt.file ?? ""),
          typeof evt.language === "string" ? evt.language : undefined
        );
      } else if (evt.type === "static_scan_file_done") {
        // 更新文件进度，不创建新卡片
        scanner.updateFileProgress("static_scan", {
          file: String(evt.file ?? ""),
          language: typeof evt.language === "string" ? evt.language : undefined,
          duration_ms: optionalNumber(evt.duration_ms),
          issues_count: Number(evt.issues_count || 0),
          progress: optionalNumber(evt.progress),
        });
      } else if (evt.type === "static_scan_complete") {
        // 将 static_scan 扫描器标记为完成
        scanner.handleScannerProgress({
          status: "complete",
          scanner: "static_scan",
          duration_ms: evt.duration_ms || 0,
          issue_count: evt.total_issues || 0,
          error_count: evt.error_count || 0,
          files_scanned: evt.files_scanned,
          files_total: evt.files_total,
        });
        // 发送汇总
        scanner.handleScannerSummary({
          total_issues: evt.total_issues || 0,
          by_severity: {
            error: evt.error_count || 0,
            warning: evt.warning_count || 0,
            info: evt.info_count || 0,
          },
          critical_issues: evt.issues || [],
          files_scanned: evt.files_scanned,
          files_total: evt.files_total,
          duration_ms: evt.duration_ms,
          scanners_used: evt.scanners_used || [],
        });
      }
    } catch (e) {
      console.warn("Scanner replay error:", e);
    }
  });

  console.log(`[WorkflowReplay] Replayed ${scannerEvents.length} scanner events`);
}

// --- Planner Visualization Helpers (Copied from review.js for independence) ---
function extractPlanItemsSafe(jsonStr: string): Array<Record<string, unknown>> {
  const items: Array<Record<string, unknown>> = [];
  const planStart = jsonStr.indexOf('"plan"');
  if (planStart === -1) return items;

  const arrayStart = jsonStr.indexOf("[", planStart);
  if (arrayStart === -1) return items;

  let depth = 0;
  let start = -1;
  let inString = false;
  let escape = false;

  for (let i = arrayStart + 1; i < jsonStr.length; i++) {
    const char = jsonStr[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (char === "\\") {
      escape = true;
      continue;
    }
    if (char === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;

    if (char === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (char === "}") {
      depth--;
      if (depth === 0 && start !== -1) {
        try {
          const itemStr = jsonStr.substring(start, i + 1);
          const item = JSON.parse(itemStr) as Record<string, unknown>;
          items.push(item);
        } catch {
          // 旧版同样忽略不完整 JSON
        }
        start = -1;
      }
    }
  }
  return items;
}

function renderPlannerVisualsReplay(container: HTMLElement, fullText: string): boolean {
  const items = extractPlanItemsSafe(fullText);
  if (!items.length) return false;

  const visualizer = document.createElement("div");
  visualizer.className = "plan-visualizer";

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "plan-item";

    let ctxClass = "tag-context-file";
    if (item.llm_context_level === "diff_only") ctxClass = "tag-context-diff";
    else if (item.llm_context_level === "function") ctxClass = "tag-context-func";

    const skipTag = item.skip_review ? '<span class="plan-tag tag-skip">跳过</span>' : "";
    const ctxTag = `<span class="plan-tag ${ctxClass}">${String(item.llm_context_level ?? "")}</span>`;

    const unitId = String(item.unit_id ?? "");
    const displayName =
      unitId.length > 20 ? unitId.substring(0, 8) + "..." + unitId.substring(unitId.length - 6) : unitId;

    card.innerHTML = `
            <div class="plan-header">
                <div class="plan-title-group">
                    <svg class="plan-icon"><use href="#icon-folder"></use></svg>
                    <span class="plan-id" title="${unitId}">${displayName}</span>
                </div>
            </div>
            <div class="plan-reason">${String(item.reason ?? "")}</div>
            <div class="plan-tags">
                ${ctxTag}
                ${skipTag}
            </div>
        `;
    visualizer.appendChild(card);
  });

  const toggleRaw = document.createElement("div");
  toggleRaw.className = "plan-raw-toggle";
  toggleRaw.textContent = "切换原始 JSON 视图";
  toggleRaw.onclick = () => {
    const p = container.querySelector<HTMLElement>(".workflow-raw-text");
    const v = container.querySelector<HTMLElement>(".plan-visualizer");
    if (p && v) {
      const isHidden = p.style.display === "none";
      p.style.display = isHidden ? "block" : "none";
      v.style.display = isHidden ? "none" : "flex";
    }
  };

  container.appendChild(visualizer);
  container.appendChild(toggleRaw);

  const rawDiv = document.createElement("div");
  rawDiv.className = "workflow-raw-text markdown-body";
  rawDiv.style.display = "none";
  rawDiv.innerHTML = renderMarkdown(fullText);
  container.appendChild(rawDiv);

  return true;
}

type StageToggleWindow = Window & {
  toggleStageSection?: (headerEl: HTMLElement) => void;
};

/** 旧版 toggleStageSection 定义在 state.js；新壳没有该全局，这里补一个等价实现。 */
function ensureStageToggleGlobal(): void {
  if (typeof window === "undefined") return;
  const win = window as StageToggleWindow;
  if (typeof win.toggleStageSection === "function") return;
  win.toggleStageSection = (headerEl: HTMLElement) => {
    const section = headerEl.closest(".workflow-stage-section");
    if (section) {
      section.classList.toggle("collapsed");
    }
  };
}

export function replayWorkflowEvents(container: HTMLElement, events: Record<string, unknown>[]): void {
  if (!container || !events || events.length === 0) return;

  ensureStageToggleGlobal();
  container.innerHTML = "";

  let currentStage: string | null = null;
  let currentStageContent: HTMLElement | null = null;
  let chunkBuffer = "";
  const toolCallEntries = new Map<string, ToolEntry>();

  function createStageHeader(stage: string): HTMLElement {
    const info = getStageInfo(stage);
    const section = document.createElement("div");
    section.className = "workflow-stage-section";
    section.dataset.stage = stage;
    section.innerHTML = `
            <div class="stage-header collapsible" onclick="toggleStageSection(this)">
                <div class="stage-indicator" style="--stage-color: ${info.color}">
                    ${getIcon(info.icon)}
                    <span>${info.title}</span>
                </div>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="stage-content"></div>
        `;
    return section;
  }

  function ensureStage(stage: string): HTMLElement | null {
    const normalizedStage = normalizeStage(stage);
    if (normalizedStage === currentStage) {
      return currentStageContent;
    }
    if (!shouldShowStage(normalizedStage)) {
      return null;
    }
    const section = createStageHeader(normalizedStage);
    container.appendChild(section);
    currentStage = normalizedStage;
    currentStageContent = section.querySelector<HTMLElement>(".stage-content");
    return currentStageContent;
  }

  function getToolKey(evt: ReplayEvent): string {
    const callIdx = evt.call_index ?? evt.index ?? "0";
    const toolName = evt.tool_name || evt.tool || "tool";
    // [FIX] 旧版已移除 hash；start/result 参数可能不同，避免 key 不匹配。
    return `${String(callIdx)}-${String(toolName)}`;
  }

  function ensureToolCard(stageContent: HTMLElement | null, evt: ReplayEvent): ToolEntry | null {
    if (!stageContent) return null;
    const key = getToolKey(evt);
    const toolName = String(evt.tool_name || evt.tool || "未知工具");

    const existing = toolCallEntries.get(key);
    if (existing) {
      return existing;
    }

    // [FIX] Orphan Claiming Logic:
    // 若已有具体 index（如 "3-tool"）却找不到对应卡片，检查仍在运行的 "0-tool" 通用卡片，
    // 认领（改名）而不是新建。用于 start(no-index) → start(index) 的后端事件序列。
    const callIdx = evt.call_index ?? evt.index;
    if (callIdx && String(callIdx) !== "0") {
      const genericKey = `0-${toolName}`;
      const genericEntry = toolCallEntries.get(genericKey);
      if (genericEntry && genericEntry.statusEl && genericEntry.statusEl.classList.contains("status-running")) {
        // Claim it!
        toolCallEntries.delete(genericKey);

        genericEntry.key = key;
        genericEntry.card.dataset.callKey = key;

        const titleText = genericEntry.card.querySelector(".tool-title-text");
        if (titleText && !titleText.querySelector(".tool-badge")) {
          titleText.innerHTML += `<span class="tool-badge">#${escapeHtml(String(callIdx))}</span>`;
        }

        toolCallEntries.set(key, genericEntry);
        return genericEntry;
      }
    }

    const card = document.createElement("div");
    card.className = "workflow-tool";
    card.dataset.callKey = key;
    card.innerHTML = `
            <div class="tool-head">
                <div class="tool-title">
                    ${getIcon("terminal")}
                    <div class="tool-title-text">
                        <span class="tool-name">${escapeHtml(toolName)}</span>
                        ${evt.call_index !== undefined && evt.call_index !== null ? `<span class="tool-badge">#${escapeHtml(String(evt.call_index))}</span>` : ""}
                    </div>
                </div>
                <span class="tool-status status-running">调用中</span>
            </div>
            <div class="tool-section tool-args">${formatToolArgsGlobal(toolName, evt.arguments || evt.detail)}</div>
            <div class="tool-section tool-output" style="display:none"></div>
            <div class="tool-section tool-meta" style="display:none"></div>
        `;
    stageContent.appendChild(card);

    const entry: ToolEntry = {
      key,
      card,
      statusEl: card.querySelector<HTMLElement>(".tool-status"),
      argsEl: card.querySelector<HTMLElement>(".tool-args"),
      outputEl: card.querySelector<HTMLElement>(".tool-output"),
      metaEl: card.querySelector<HTMLElement>(".tool-meta"),
      name: toolName,
    };
    toolCallEntries.set(key, entry);
    return entry;
  }

  function setToolStatus(entry: ToolEntry | null, status: string, label: string): void {
    if (!entry || !entry.statusEl) return;
    entry.statusEl.className = `tool-status status-${status}`;
    entry.statusEl.textContent = label;
  }

  function updateToolMeta(entry: ToolEntry | null, evt: ReplayEvent): void {
    if (!entry || !entry.metaEl) return;
    const chips: string[] = [];
    if (evt.duration_ms !== undefined && evt.duration_ms !== null) {
      chips.push(`<span class="meta-chip">耗时 ${Math.round(Number(evt.duration_ms))}ms</span>`);
    }
    if (!chips.length) return;
    entry.metaEl.innerHTML = chips.join("");
    entry.metaEl.style.display = "flex";
  }

  function updateToolOutput(entry: ToolEntry | null, evt: ReplayEvent): void {
    if (!entry || !entry.outputEl) return;
    const hasError = Boolean(evt.error);
    const body = hasError
      ? `<div class="tool-result error">${escapeHtml(String(evt.error))}</div>`
      : `<div class="tool-result success">${renderToolContentGlobal(entry.name, evt.content || evt.result)}</div>`;
    entry.outputEl.innerHTML = body;
    entry.outputEl.style.display = "block";
    setToolStatus(entry, hasError ? "error" : "success", hasError ? "失败" : "完成");
    updateToolMeta(entry, evt);
  }

  function flushChunk(stage: string, chunkText: string, nextEvt: ReplayEvent | null): void {
    if (!chunkText.trim() || !currentStageContent) {
      return;
    }
    if (stage === "review") {
      if (nextEvt && (nextEvt.type === "tool_start" || nextEvt.type === "tool_call_start")) {
        const explanation = document.createElement("div");
        explanation.className = "workflow-tool-explanation";
        explanation.innerHTML = `
                    <div class="tool-explanation-content markdown-body">
                        ${renderMarkdown(chunkText)}
                    </div>
                `;
        currentStageContent.appendChild(explanation);
      }
      return;
    }

    const chunkTitle = stage === "planner" ? "上下文决策" : "输出内容";
    // Planner 默认展开以便查看，其他内容默认折叠保持整洁
    const initialClass = stage === "planner" ? "workflow-chunk-wrapper" : "workflow-chunk-wrapper collapsed";

    const wrapper = document.createElement("div");
    wrapper.className = initialClass;
    wrapper.innerHTML = `
            <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                ${getIcon("folder")}
                <span>${chunkTitle}</span>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="chunk-body">
                <div class="workflow-chunk"></div>
            </div>
        `;
    currentStageContent.appendChild(wrapper);

    const chunkEl = wrapper.querySelector<HTMLElement>(".workflow-chunk");
    if (!chunkEl) return;

    // 尝试可视化渲染 (Planner)
    if (stage === "planner") {
      // 如果成功渲染出可视化组件，就不再渲染默认 Markdown
      if (renderPlannerVisualsReplay(chunkEl, chunkText)) {
        return;
      }
    }

    // 默认 Markdown 渲染
    chunkEl.classList.add("markdown-body");
    chunkEl.innerHTML = renderMarkdown(chunkText);
  }

  const RENDER_EVENT_TYPES = new Set([
    "thought",
    "chunk",
    "delta",
    "tool_start",
    "tool_call_start",
    "tool_result",
    "tool_call_end",
    "workflow_chunk",
  ]);

  function getNextRelevantEvent(
    startIdx: number,
    stage: string
  ): { evt: ReplayEvent | null; idx: number; stage: string } {
    for (let k = startIdx; k < events.length; k++) {
      const e = events[k];
      const s = normalizeStage(e.stage || stage || "review");
      if (!shouldShowStage(s)) continue;
      if (!RENDER_EVENT_TYPES.has(String(e.type))) continue;
      return { evt: e, idx: k, stage: s };
    }
    return { evt: null, idx: -1, stage: stage };
  }

  for (let i = 0; i < events.length; i++) {
    const evt = events[i];
    const stage = normalizeStage(evt.stage || "review");

    if (!shouldShowStage(stage)) {
      continue;
    }
    if (!RENDER_EVENT_TYPES.has(String(evt.type))) {
      continue;
    }
    const stageContent = ensureStage(stage);
    if (!stageContent) continue;

    if (evt.type === "thought") {
      // 收集当前 stage 的所有 thought 事件，跳过不属于当前 stage 的事件
      let thoughtContent = String(evt.content || evt.text || "");
      let j = i + 1;
      while (j < events.length) {
        const nextThoughtEvt = events[j];
        const nextStage = normalizeStage(nextThoughtEvt.stage || "review");

        // 如果是同 stage 的 thought，累积内容
        if (nextThoughtEvt.type === "thought" && nextStage === stage) {
          thoughtContent += String(nextThoughtEvt.content || nextThoughtEvt.text || "");
          j++;
          continue;
        }

        // 如果是不同 stage 的事件，跳过它（不打断合并）
        if (nextStage !== stage) {
          j++;
          continue;
        }

        // 如果是同 stage 的非 thought 事件，停止合并
        break;
      }
      // 跳过已经处理的事件
      i = j - 1;

      if (!thoughtContent.trim()) continue;

      const thoughtEl = document.createElement("div");
      thoughtEl.className = "workflow-thought collapsed";
      thoughtEl.innerHTML = `
                <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                    ${getIcon("bot")}
                    <span>思考过程</span>
                    <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                </div>
                <div class="thought-body"><pre class="thought-text">${escapeHtml(thoughtContent)}</pre></div>
            `;
      stageContent.appendChild(thoughtEl);
      continue;
    }

    if (evt.type === "chunk" || evt.type === "delta" || evt.type === "workflow_chunk") {
      const content = String(evt.content || evt.text || "");
      if (content) {
        chunkBuffer += content;
      }

      // Merge across intervening non-render / hidden-stage events.
      // Only stop when the next *relevant* event is not a same-stage chunk stream.
      const next = getNextRelevantEvent(i + 1, stage);
      const nextEvt = next.evt;
      const nextStage = next.stage;
      const continueChunk =
        Boolean(nextEvt) &&
        nextStage === stage &&
        (nextEvt?.type === "chunk" || nextEvt?.type === "delta" || nextEvt?.type === "workflow_chunk");

      if (continueChunk) continue;

      flushChunk(stage, chunkBuffer, nextEvt);
      chunkBuffer = "";
      continue;
    }

    chunkBuffer = "";

    if (evt.type === "tool_start" || evt.type === "tool_call_start") {
      const entry = ensureToolCard(stageContent, evt);
      // [FIX] Always try to update arguments from latest event
      if (entry && entry.argsEl && (evt.arguments || evt.detail)) {
        entry.argsEl.innerHTML = formatToolArgsGlobal(entry.name, evt.arguments || evt.detail);
      }
      setToolStatus(entry, "running", "调用中");
      continue;
    }

    if (evt.type === "tool_result" || evt.type === "tool_call_end") {
      const key = getToolKey(evt);
      let entry = toolCallEntries.get(key) ?? null;

      // [FIX] Fallback matching: if exact key not found (e.g. index mismatch),
      // find the LAST running tool with same name.
      if (!entry) {
        const entries = Array.from(toolCallEntries.values());
        const targetName = String(evt.tool_name || evt.tool || evt.name || "未知工具");
        for (let k = entries.length - 1; k >= 0; k--) {
          const e = entries[k];
          if (e.name === targetName && e.statusEl && e.statusEl.classList.contains("status-running")) {
            entry = e;
            break;
          }
        }
      }

      if (entry) {
        if (evt.type === "tool_result") {
          updateToolOutput(entry, evt);
        } else {
          setToolStatus(entry, evt.success === false ? "error" : "success", evt.success === false ? "失败" : "完成");
          updateToolMeta(entry, evt);
        }
      }
      continue;
    }

    if (evt.content) {
      const block = document.createElement("div");
      block.className = "workflow-block markdown-body";
      block.innerHTML = renderMarkdown(String(evt.content));
      stageContent.appendChild(block);
    }
  }
}

export function replayMonitorEvents(container: HTMLElement, events: Record<string, unknown>[]): void {
  if (!container || !events) return;

  container.innerHTML = "";

  const monitorEvents = events.filter(
    (e) => e.type === "warning" || e.type === "usage_summary" || e.type === "error"
  );

  monitorEvents.forEach((evt) => {
    const div = document.createElement("div");
    div.className = `monitor-entry ${String(evt.type)}`;

    if (evt.type === "warning") {
      div.innerHTML = `
                <div class="monitor-icon">${getIcon("alert-triangle")}</div>
                <div class="monitor-content">${escapeHtml(evt.message || "")}</div>
            `;
    } else if (evt.type === "usage_summary") {
      // 历史会话的字段是 usage.data.total_tokens/total_cost，
      // 与实时 usage_summary 的 call_usage/session_usage 不同。
      const usage = (evt.data || {}) as Record<string, unknown>;
      div.innerHTML = `
                <div class="monitor-icon">${getIcon("bar-chart")}</div>
                <div class="monitor-content">
                    <span>Tokens: ${usage.total_tokens || 0}</span>
                    <span>Cost: $${Number(usage.total_cost || 0).toFixed(4)}</span>
                </div>
            `;
    } else if (evt.type === "error") {
      div.innerHTML = `
                <div class="monitor-icon">${getIcon("x")}</div>
                <div class="monitor-content error">${escapeHtml(evt.message || evt.error || "")}</div>
            `;
    }

    container.appendChild(div);
  });
}
