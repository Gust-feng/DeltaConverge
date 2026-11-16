import type { FlatEvent } from "../../lib/events";
import { escapeHtml, getIcon } from "../../lib/html";
import { renderMarkdown } from "../../lib/markdown";

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

type ChunkElement = HTMLElement & {
  dataset: DOMStringMap & { fullText?: string; stage?: string; visualizedItems?: string };
  _markedRendered?: boolean;
  _streamMdTimer?: number | null;
};

const STAGE_MAP: Record<string, StageInfo> = {
  intent: { title: "意图分析", icon: "bot", color: "#6366f1" },
  planner: { title: "审查规划", icon: "plan", color: "#8b5cf6" },
  review: { title: "代码审查", icon: "review", color: "#10b981" },
  default: { title: "处理中", icon: "settings", color: "#64748b" },
};

function truncateText(text: unknown, max = 240): string {
  const safe = text == null ? "" : String(text);
  return safe.length > max ? `${safe.slice(0, max)}...` : safe;
}

function formatToolArgs(rawArgs: unknown): string {
  if (rawArgs === undefined || rawArgs === null || rawArgs === "") {
    return '<span class="tool-args-empty">无参数</span>';
  }
  let parsed: unknown = rawArgs;
  if (typeof rawArgs === "string") {
    try {
      parsed = JSON.parse(rawArgs);
    } catch {
      // 保持原字符串
    }
  }
  if (typeof parsed === "object" && parsed !== null) {
    const entries: Array<[string, unknown]> = Array.isArray(parsed)
      ? parsed.map((value, index) => [`#${index}`, value])
      : Object.entries(parsed as Record<string, unknown>);
    const limited = entries.slice(0, 6);
    const pills = limited
      .map(([key, value]) => {
        const valueText = typeof value === "object" ? JSON.stringify(value) : String(value ?? "");
        return `<span class="kv-pill"><span class="kv-key">${escapeHtml(truncateText(key, 40))}</span><span class="kv-value">${escapeHtml(truncateText(valueText, 160))}</span></span>`;
      })
      .join("");
    const more = entries.length > limited.length ? '<span class="kv-pill muted">...</span>' : "";
    return `<div class="kv-pills">${pills}${more}</div>`;
  }
  return `<code class="mono">${escapeHtml(truncateText(parsed, 200))}</code>`;
}

function renderToolContent(toolName: string, rawContent: unknown): string {
  if (rawContent === undefined || rawContent === null || rawContent === "") {
    return '<span class="tool-empty">无返回内容</span>';
  }
  let data: unknown = rawContent;
  if (typeof rawContent === "string") {
    try {
      data = JSON.parse(rawContent);
    } catch {
      // 保持原字符串
    }
  }
  if (data && typeof data === "object" && (data as Record<string, unknown>).error) {
    return `<div class="tool-result error">${escapeHtml(String((data as Record<string, unknown>).error))}</div>`;
  }
  if (typeof data === "object") {
    const jsonStr = JSON.stringify(data, null, 2);
    return `<pre class="tool-json"><code>${escapeHtml(truncateText(jsonStr, 3000))}</code></pre>`;
  }
  return `<pre class="tool-text"><code>${escapeHtml(truncateText(String(rawContent), 2000))}</code></pre>`;
}

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
          items.push(JSON.parse(jsonStr.substring(start, i + 1)) as Record<string, unknown>);
        } catch {
          // 旧版同样忽略不完整 JSON
        }
        start = -1;
      }
    }
  }
  return items;
}

export type LiveWorkflowOptions = {
  /** review stage 的 chunk 不进右侧工作流，交给控制器写入左侧报告。 */
  onReviewChunk: (text: string) => void;
  /** 工具调用前取出待定的审查文字说明。 */
  consumePendingReviewChunk: () => string;
};

export class LiveWorkflowRenderer {
  private readonly root: HTMLElement;
  private readonly workflowEntries: HTMLElement | null;
  private readonly scrollArea: HTMLElement | null;
  private readonly options: LiveWorkflowOptions;

  private currentStage: string | null = null;
  private currentChunkEl: ChunkElement | null = null;
  private currentThoughtEl: HTMLElement | null = null;
  private thoughtStartTime: number | null = null;
  private thoughtTimer: number | null = null;
  private toolCallEntries = new Map<string, ToolEntry>();
  private manualExpandStates = new Map<string, boolean>();
  private userScrolled = false;
  private lastScrollTime = 0;
  private isAutoScrolling = false;
  private autoScrollTimer: number | null = null;
  private renderFrame: number | null = null;
  private pendingThoughts = new Map<HTMLElement, string[]>();
  private pendingChunks = new Set<ChunkElement>();
  private streamingChunks = new Set<ChunkElement>();
  private pendingScrollTargets = new Set<HTMLElement>();
  private readonly SCROLL_RESET_TIMEOUT = 4000;
  private readonly handleUserScroll = () => {
    if (this.isAutoScrolling) return;
    this.userScrolled = true;
    this.lastScrollTime = Date.now();
  };

  constructor(root: HTMLElement, options: LiveWorkflowOptions) {
    this.root = root;
    this.options = options;
    this.workflowEntries = root.querySelector<HTMLElement>("#workflowEntries");
    this.scrollArea = root.querySelector<HTMLElement>("#rightPanelScrollArea");
  }

  init(): void {
    this.scrollArea?.addEventListener("scroll", this.handleUserScroll);
    this.workflowEntries?.addEventListener("scroll", this.handleUserScroll);
  }

  dispose(): void {
    this.cancelScheduledUpdates();
    this.stopThoughtTimer();
    this.scrollArea?.removeEventListener("scroll", this.handleUserScroll);
    this.workflowEntries?.removeEventListener("scroll", this.handleUserScroll);
    for (const entry of this.toolCallEntries.values()) {
      if (entry.card.dataset.timerId) window.clearTimeout(Number(entry.card.dataset.timerId));
    }
    this.toolCallEntries.clear();
  }

  finalize(): void {
    if (this.renderFrame !== null) cancelAnimationFrame(this.renderFrame);
    this.renderFrame = null;
    this.flushPendingUpdates(true);
    this.stopThoughtTimer();
  }

  reset(): void {
    this.cancelScheduledUpdates();
    this.stopThoughtTimer();
    this.currentStage = null;
    this.currentChunkEl = null;
    this.currentThoughtEl = null;
    this.toolCallEntries.clear();
    this.manualExpandStates.clear();
    this.userScrolled = false;
    if (this.workflowEntries) this.workflowEntries.innerHTML = "";
  }

  private normalizeStage(rawStage: string): string {
    if (rawStage === "intent_analysis") return "intent";
    if (rawStage === "reviewer") return "review";
    if (["fusion", "context_provider", "context_bundle", "final_context_plan"].includes(rawStage)) {
      return "planner";
    }
    return rawStage;
  }

  /**
   * 立即创建阶段容器（不等首个 token）。
   * 返回该阶段的 .stage-content，供后续内容/等待提示插入。
   */
  ensureStage(rawStage: string): HTMLElement | null {
    if (!this.workflowEntries) return null;
    const stage = this.normalizeStage(rawStage);
    if (stage === "init") return null;

    if (stage !== this.currentStage) {
      this.workflowEntries
        .querySelectorAll(".workflow-chunk-wrapper:not(.collapsed), .workflow-thought:not(.collapsed)")
        .forEach((item) => item.classList.add("collapsed"));
      this.currentStage = stage;
      this.currentChunkEl = null;
      this.currentThoughtEl = null;
      this.stopThoughtTimer();
      this.workflowEntries.appendChild(this.createStageHeader(stage));
      this.workflowEntries.querySelectorAll('[data-waiting="init"]').forEach((item) => item.remove());
    }
    return this.getCurrentStageContent();
  }

  /** 阶段已开始但模型还没吐 token 时的可见等待提示。 */
  showWaiting(rawStage: string, text: string): void {
    if (!this.workflowEntries) return;
    const stage = this.normalizeStage(rawStage);
    const waiting = document.createElement("div");
    waiting.className = "workflow-waiting";
    waiting.dataset.waiting = stage;
    waiting.setAttribute(
      "style",
      "display:flex;align-items:center;gap:0.5rem;padding:0.6rem 0.75rem;color:var(--text-secondary);font-size:0.85rem;"
    );
    waiting.innerHTML = `<span class="spinner-small"></span><span>${escapeHtml(text)}</span>`;

    if (stage === "init") {
      this.clearWaiting("init");
      this.workflowEntries.appendChild(waiting);
      this.liveFollowScroll();
      return;
    }

    const stageContent = this.ensureStage(stage);
    if (!stageContent) return;
    stageContent.querySelectorAll(`.workflow-waiting[data-waiting="${stage}"]`).forEach((item) => item.remove());
    stageContent.appendChild(waiting);
    this.liveFollowScroll();
  }

  clearWaiting(rawStage?: string): void {
    if (!this.workflowEntries) return;
    const stage = rawStage ? this.normalizeStage(rawStage) : null;
    const selector = stage ? `.workflow-waiting[data-waiting="${stage}"]` : ".workflow-waiting";
    this.workflowEntries.querySelectorAll(selector).forEach((item) => item.remove());
  }

  append(evt: FlatEvent): void {
    if (!this.workflowEntries) return;
    const stage = this.normalizeStage(String(evt.stage || "review"));
    const stageContent = this.ensureStage(stage);
    if (!stageContent) return;

    // 首个真实内容到达，撤掉该阶段的等待提示。
    this.clearWaiting(stage);
    this.clearWaiting("init");

    if (evt.type === "thought") {
      const thoughtText = String(evt.content || "");
      if (!thoughtText) return;
      if (!this.currentThoughtEl) {
        const thought = document.createElement("div");
        thought.className = "workflow-thought";
        thought.id = this.generateElementId();
        thought.innerHTML = `
          <div class="thought-toggle">
            ${getIcon("bot")}
            <span>思考过程</span>
            <span class="thought-timer">0s</span>
            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
          </div>
          <div class="thought-body"><pre class="thought-text"></pre></div>
        `;
        const toggle = thought.querySelector<HTMLElement>(".thought-toggle");
        toggle?.addEventListener("click", () => {
          thought.classList.toggle("collapsed");
          this.manualExpandStates.set(thought.id, !thought.classList.contains("collapsed"));
        });
        stageContent.appendChild(thought);
        this.currentThoughtEl = thought;
        const timerEl = thought.querySelector<HTMLElement>(".thought-timer");
        this.startThoughtTimer(timerEl);
        const thoughtBody = thought.querySelector(".thought-body");
        thoughtBody?.addEventListener("scroll", this.handleUserScroll);
      }
      const textEl = this.currentThoughtEl.querySelector<HTMLElement>(".thought-text");
      if (textEl) {
        const pending = this.pendingThoughts.get(textEl) ?? [];
        pending.push(thoughtText);
        this.pendingThoughts.set(textEl, pending);
      }
      const thoughtBody = this.currentThoughtEl.querySelector<HTMLElement>(".thought-body");
      if (thoughtBody) this.pendingScrollTargets.add(thoughtBody);
      this.liveFollowScroll();
      return;
    }

    if (evt.type === "chunk" || evt.type === "workflow_chunk") {
      this.stopThoughtTimer();
      if (this.currentThoughtEl) this.liveFollowCollapse(this.currentThoughtEl);

      if (stage === "review") {
        this.options.onReviewChunk(String(evt.content || evt.text || ""));
        return;
      }

      if (!this.currentChunkEl) {
        const wrapper = document.createElement("div");
        wrapper.className = stage === "planner" ? "workflow-chunk-wrapper" : "workflow-chunk-wrapper collapsed";
        wrapper.id = this.generateElementId();
        const chunkTitle = stage === "planner" ? "上下文决策" : "输出内容";
        wrapper.innerHTML = `
          <div class="chunk-toggle">
            ${getIcon("folder")}
            <span>${chunkTitle}</span>
            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
          </div>
          <div class="chunk-body">
            <div class="workflow-chunk markdown-body"></div>
          </div>
        `;
        const toggle = wrapper.querySelector<HTMLElement>(".chunk-toggle");
        toggle?.addEventListener("click", () => {
          wrapper.classList.toggle("collapsed");
          this.manualExpandStates.set(wrapper.id, !wrapper.classList.contains("collapsed"));
        });
        stageContent.appendChild(wrapper);
        this.currentChunkEl = wrapper.querySelector(".workflow-chunk") as ChunkElement | null;
        if (this.currentChunkEl) {
          this.currentChunkEl.dataset.fullText = "";
          this.currentChunkEl.dataset.stage = stage;
        }
      }
      this.streamAppendIntoChunkEl(this.currentChunkEl, String(evt.content || evt.text || ""));
      this.liveFollowScroll();
      return;
    }

    if (this.currentChunkEl) {
      const wrapper = this.currentChunkEl.closest(".workflow-chunk-wrapper");
      if (wrapper) this.liveFollowCollapse(wrapper as HTMLElement);
    }
    this.currentChunkEl = null;
    if (this.currentThoughtEl) this.liveFollowCollapse(this.currentThoughtEl);
    this.stopThoughtTimer();

    if (
      evt.type === "tool_start" ||
      evt.type === "tool_call_start" ||
      evt.type === "tool_result" ||
      evt.type === "tool_call_end"
    ) {
      this.currentThoughtEl = null;
      this.currentChunkEl = null;

      if (stage === "review") {
        const pending = this.options.consumePendingReviewChunk().trim();
        if (pending) {
          const explanationEl = document.createElement("div");
          explanationEl.className = "workflow-tool-explanation";
          explanationEl.innerHTML = `<div class="tool-explanation-content markdown-body">${renderMarkdown(pending)}</div>`;
          stageContent.appendChild(explanationEl);
        }
      }

      let entry: ToolEntry | null = null;
      if (evt.type === "tool_result" || evt.type === "tool_call_end") {
        const key = this.getToolKey(evt);
        entry = this.toolCallEntries.get(key) ?? null;
        if (!entry) {
          const entries = Array.from(this.toolCallEntries.values());
          const targetName = String(evt.tool_name || evt.tool || evt.name || "未知工具");
          for (let index = entries.length - 1; index >= 0; index--) {
            const candidate = entries[index];
            if (candidate.name === targetName && candidate.statusEl?.classList.contains("status-running")) {
              entry = candidate;
              break;
            }
          }
        }
      }

      if (!entry) entry = this.ensureToolCard(stageContent, evt);

      if (evt.type === "tool_result") {
        this.updateToolOutput(entry, evt);
      } else if (evt.type === "tool_call_end") {
        this.setToolStatus(entry, evt.success === false ? "error" : "success", evt.success === false ? "失败" : "完成");
        this.updateToolMeta(entry, evt);
      } else {
        if (entry.argsEl && (evt.arguments || evt.detail)) {
          entry.argsEl.innerHTML = formatToolArgs(evt.arguments || evt.detail);
        }
        this.setToolStatus(entry, "running", "调用中");
      }
      this.liveFollowScroll();
      return;
    }

    if (evt.content) {
      const block = document.createElement("div");
      block.className = "workflow-block markdown-body";
      block.innerHTML = renderMarkdown(String(evt.content));
      stageContent.appendChild(block);
      this.liveFollowScroll();
    }
  }

  private getStageInfo(stage: string): StageInfo {
    return STAGE_MAP[stage] ?? STAGE_MAP.default;
  }

  private createStageHeader(stage: string): HTMLElement {
    const info = this.getStageInfo(stage);
    const header = document.createElement("div");
    header.className = "workflow-stage-section";
    header.id = `stage-${stage}-${Date.now()}`;
    header.dataset.stage = stage;
    header.innerHTML = `
      <div class="stage-header collapsible">
        <div class="stage-indicator" style="--stage-color: ${info.color}">
          ${getIcon(info.icon)}
          <span>${info.title}</span>
        </div>
        <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
      </div>
      <div class="stage-content"></div>
    `;
    header.querySelector(".stage-header")?.addEventListener("click", function onToggle(this: HTMLElement) {
      this.parentElement?.classList.toggle("collapsed");
    });
    return header;
  }

  private getCurrentStageContent(): HTMLElement {
    if (!this.workflowEntries) return this.root;
    const sections = this.workflowEntries.querySelectorAll(".workflow-stage-section");
    const lastSection = sections[sections.length - 1];
    return (lastSection?.querySelector(".stage-content") as HTMLElement | null) ?? this.workflowEntries;
  }

  private renderPlannerVisuals(chunkEl: ChunkElement, fullText: string): void {
    const items = extractPlanItemsSafe(fullText);
    let visualizer = chunkEl.querySelector<HTMLElement>(".plan-visualizer");
    if (!visualizer) {
      if (items.length === 0) return;

      const pre = chunkEl.querySelector(".workflow-stream-text") as HTMLElement | null;
      if (pre) pre.style.display = "none";

      visualizer = document.createElement("div");
      visualizer.className = "plan-visualizer";

      const toggleRaw = document.createElement("div");
      toggleRaw.className = "plan-raw-toggle";
      toggleRaw.textContent = "切换原始 JSON 视图";
      toggleRaw.addEventListener("click", () => {
        const currentPre = chunkEl.querySelector<HTMLElement>(".workflow-stream-text");
        const currentVisualizer = chunkEl.querySelector<HTMLElement>(".plan-visualizer");
        if (!currentPre || !currentVisualizer) return;
        const hidden = currentPre.style.display === "none";
        currentPre.style.display = hidden ? "block" : "none";
        currentVisualizer.style.display = hidden ? "none" : "flex";
      });

      chunkEl.appendChild(visualizer);
      chunkEl.appendChild(toggleRaw);
      chunkEl.dataset.visualizedItems = "0";
    }

    const currentRenderedCount = parseInt(chunkEl.dataset.visualizedItems || "0", 10);
    if (items.length > currentRenderedCount) {
      for (let index = currentRenderedCount; index < items.length; index++) {
        const item = items[index];
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
      }
      chunkEl.dataset.visualizedItems = String(items.length);
    }
  }

  private streamAppendIntoChunkEl(chunkEl: ChunkElement | null, deltaText: string): void {
    if (!chunkEl) return;
    chunkEl.dataset.fullText = (chunkEl.dataset.fullText || "") + deltaText;
    if (chunkEl._streamMdTimer != null) window.clearTimeout(chunkEl._streamMdTimer);
    chunkEl._streamMdTimer = null;
    this.streamingChunks.add(chunkEl);
    this.pendingChunks.add(chunkEl);
    this.scheduleUpdate();
  }

  private renderStreamingChunk(chunkEl: ChunkElement): void {
    if (!chunkEl.isConnected) return;
    const fullText = chunkEl.dataset.fullText || "";
    let pre = chunkEl.querySelector<HTMLElement>(".workflow-stream-text");
    if (!pre) {
      if (chunkEl._markedRendered) chunkEl.innerHTML = "";
      pre = document.createElement("pre");
      pre.className = "workflow-stream-text";
      pre.setAttribute("style", "white-space:pre-wrap;word-break:break-word;font-family:inherit;margin:0;");
      chunkEl.appendChild(pre);
    }
    pre.textContent = fullText;
    chunkEl._markedRendered = false;

    if (chunkEl.dataset.stage === "planner") {
      this.renderPlannerVisuals(chunkEl, fullText);
      if (chunkEl.querySelector(".plan-visualizer")) return;
    }

    chunkEl._streamMdTimer = window.setTimeout(() => {
      chunkEl._streamMdTimer = null;
      if (!chunkEl.isConnected) return;
      chunkEl._markedRendered = true;
      chunkEl.innerHTML = renderMarkdown(chunkEl.dataset.fullText || "");
      this.liveFollowScroll();
    }, 500);
  }

  private scheduleUpdate(): void {
    if (this.renderFrame !== null) return;
    this.renderFrame = requestAnimationFrame(() => {
      this.renderFrame = null;
      this.flushPendingUpdates();
    });
  }

  private flushPendingUpdates(finalize = false): void {
    for (const [textEl, deltas] of this.pendingThoughts) {
      if (!textEl.isConnected) continue;
      const text = deltas.join("");
      const lastNode = textEl.lastChild;
      if (lastNode?.nodeType === Node.TEXT_NODE) (lastNode as Text).appendData(text);
      else textEl.appendChild(document.createTextNode(text));
    }
    this.pendingThoughts.clear();
    for (const chunkEl of this.pendingChunks) this.renderStreamingChunk(chunkEl);
    this.pendingChunks.clear();

    if (finalize) {
      for (const chunkEl of this.streamingChunks) {
        if (chunkEl._streamMdTimer != null) window.clearTimeout(chunkEl._streamMdTimer);
        chunkEl._streamMdTimer = null;
        if (!chunkEl.isConnected || chunkEl._markedRendered || chunkEl.querySelector(".plan-visualizer")) continue;
        chunkEl._markedRendered = true;
        chunkEl.innerHTML = renderMarkdown(chunkEl.dataset.fullText || "");
      }
      this.streamingChunks.clear();
    }

    for (const target of this.pendingScrollTargets) {
      if (target.isConnected) this.smartScrollToBottom(target);
    }
    this.pendingScrollTargets.clear();
  }

  private cancelScheduledUpdates(): void {
    if (this.renderFrame !== null) cancelAnimationFrame(this.renderFrame);
    this.renderFrame = null;
    for (const chunkEl of this.streamingChunks) {
      if (chunkEl._streamMdTimer != null) window.clearTimeout(chunkEl._streamMdTimer);
      chunkEl._streamMdTimer = null;
    }
    this.streamingChunks.clear();
    this.pendingThoughts.clear();
    this.pendingChunks.clear();
    this.pendingScrollTargets.clear();
    if (this.autoScrollTimer !== null) window.clearTimeout(this.autoScrollTimer);
    this.autoScrollTimer = null;
    this.isAutoScrolling = false;
  }

  private startThoughtTimer(timerEl: HTMLElement | null): void {
    this.thoughtStartTime = Date.now();
    if (this.thoughtTimer) window.clearInterval(this.thoughtTimer);
    this.thoughtTimer = window.setInterval(() => {
      if (timerEl && this.thoughtStartTime) {
        const elapsed = Math.floor((Date.now() - this.thoughtStartTime) / 1000);
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        timerEl.textContent = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
      }
    }, 1000);
  }

  private stopThoughtTimer(): void {
    if (this.thoughtTimer) {
      window.clearInterval(this.thoughtTimer);
      this.thoughtTimer = null;
    }
  }

  private smartScrollToBottom(el: HTMLElement): void {
    if (!el) return;
    if (this.userScrolled) {
      const now = Date.now();
      if (now - this.lastScrollTime > this.SCROLL_RESET_TIMEOUT) {
        this.userScrolled = false;
      } else {
        return;
      }
    }
    const currentScrollTop = el.scrollTop;
    const targetScrollTop = el.scrollHeight - el.clientHeight;
    const distance = targetScrollTop - currentScrollTop;
    if (distance <= 0) return;

    this.isAutoScrolling = true;
    el.scrollTop = targetScrollTop;
    if (this.autoScrollTimer !== null) window.clearTimeout(this.autoScrollTimer);
    this.autoScrollTimer = window.setTimeout(() => {
      this.autoScrollTimer = null;
      this.isAutoScrolling = false;
    }, 50);
  }

  private liveFollowScroll(): void {
    if (this.scrollArea) this.pendingScrollTargets.add(this.scrollArea);
    if (this.workflowEntries) this.pendingScrollTargets.add(this.workflowEntries);
    this.scheduleUpdate();
  }

  private liveFollowCollapse(el: HTMLElement): void {
    const elementId = el.id || el.dataset.elementId;
    if (elementId && this.manualExpandStates.get(elementId)) return;
    if (!el.classList.contains("collapsed")) el.classList.add("collapsed");
  }

  private generateElementId(): string {
    return "el-" + Math.random().toString(36).slice(2, 11);
  }

  private getToolKey(evt: FlatEvent): string {
    if (evt.tool_call_id) return `id-${String(evt.tool_call_id)}`;
    const callIndex = evt.call_index ?? evt.index ?? "0";
    const toolName = evt.tool_name || evt.tool || "tool";
    return `${String(callIndex)}-${String(toolName)}`;
  }

  private ensureToolCard(stageContent: HTMLElement, evt: FlatEvent): ToolEntry {
    const key = this.getToolKey(evt);
    const name = String(evt.tool_name || evt.tool || "未知工具");
    let entry = this.toolCallEntries.get(key);
    if (entry) return entry;

    const callIndex = evt.call_index ?? evt.index;
    if (callIndex && String(callIndex) !== "0") {
      const genericKey = `0-${name}`;
      const genericEntry = this.toolCallEntries.get(genericKey);
      if (genericEntry?.statusEl?.classList.contains("status-running")) {
        this.toolCallEntries.delete(genericKey);
        genericEntry.key = key;
        genericEntry.card.dataset.callKey = key;
        const titleText = genericEntry.card.querySelector(".tool-title-text");
        if (titleText && !titleText.querySelector(".tool-badge")) {
          titleText.innerHTML += `<span class="tool-badge">#${escapeHtml(String(callIndex))}</span>`;
        }
        this.toolCallEntries.set(key, genericEntry);
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
            <span class="tool-name">${escapeHtml(name)}</span>
            ${evt.call_index !== undefined && evt.call_index !== null ? `<span class="tool-badge">#${escapeHtml(String(evt.call_index))}</span>` : ""}
          </div>
        </div>
        <span class="tool-status status-running">调用中</span>
      </div>
      <div class="tool-section tool-args">${formatToolArgs(evt.arguments || evt.detail)}</div>
      <div class="tool-section tool-output" style="display:none"></div>
      <div class="tool-section tool-meta" style="display:none"></div>
    `;
    stageContent.appendChild(card);

    entry = {
      key,
      card,
      statusEl: card.querySelector(".tool-status"),
      argsEl: card.querySelector(".tool-args"),
      outputEl: card.querySelector(".tool-output"),
      metaEl: card.querySelector(".tool-meta"),
      name,
    };
    this.toolCallEntries.set(key, entry);
    return entry;
  }

  private setToolStatus(entry: ToolEntry, status: string, label: string): void {
    if (!entry?.statusEl) return;
    entry.statusEl.className = `tool-status status-${status}`;
    entry.statusEl.textContent = label;
  }

  private updateToolMeta(entry: ToolEntry, evt: FlatEvent): void {
    if (!entry?.metaEl) return;
    const chips: string[] = [];
    if (evt.duration_ms !== undefined && evt.duration_ms !== null) {
      chips.push(`<span class="meta-chip">耗时 ${Math.round(Number(evt.duration_ms))}ms</span>`);
    }
    if (chips.length === 0) return;
    entry.metaEl.innerHTML = chips.join("");
    entry.metaEl.style.display = "flex";
  }

  private updateToolOutput(entry: ToolEntry, evt: FlatEvent): void {
    if (!entry?.outputEl) return;
    const hasError = Boolean(evt.error);
    const body = hasError
      ? `<div class="tool-result error">${escapeHtml(String(evt.error))}</div>`
      : `<div class="tool-result success">${renderToolContent(entry.name, evt.content)}</div>`;
    entry.outputEl.innerHTML = body;
    entry.outputEl.style.display = "block";
    this.setToolStatus(entry, hasError ? "error" : "success", hasError ? "失败" : "完成");
    this.updateToolMeta(entry, evt);
  }
}
