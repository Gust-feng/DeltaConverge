/**
 * 代码变更页控制器：1:1 移植 legacy/ui_v1/static/modules/diff.js。
 *
 * 设计说明（与旧版一致的部分）：
 * - 状态放在模块作用域，等价于旧版的全局变量（window.currentDiffMode /
 *   window.currentDiffActivePath / window.currentDiffText 等仍然同步写出，
 *   方便审查页等其它模块读取）；
 * - 缓存 Map、60s TTL、30s 超时、骨架屏 HTML、错误文案、commit 流程、
 *   列表重渲染丢失 active 高亮等旧版行为全部保留；
 * - commit 范围同时写入 appStore.commitFrom/commitTo（供审查启动读取）。
 */

import { analyzeDiff, getCommitRange, getCommits, getDiffQuickStatus, getFileDiff } from "../../lib/api";
import { renderPlainDiff, type DiffOutputFormat } from "../../lib/diff";
import { escapeHtml, getIcon } from "../../lib/html";
import { useAppStore } from "../../state/appStore";
import type { DiffFileItem, DiffMode, GitCommit } from "../../types";
import { disposeEasterEgg, initEasterEgg, type EasterEggData, type EasterEggType } from "../easterEgg/EasterEggController";
import { forceRenderLargeDiff, renderDiff2HtmlInto, toggleDiffView } from "./diffRendering";
import { updateDiffStatusHint, updateReviewModeBadge } from "./diffStatus";

const DIFF_CACHE_TTL_MS = 60 * 1000;
const DIFF_REQUEST_TIMEOUT_MS = 30000;

type AnalysisData = { mode: string; files: DiffFileItem[] };

type AnalysisEntry = {
  ts: number;
  data: AnalysisData | null;
  promise: Promise<void> | null;
};

type FileDiffData = {
  file_path?: string;
  diff_text?: string;
  diff_content?: string;
  error?: string | null;
};

type FileEntry = {
  ts: number;
  data: FileDiffData | null;
  promise: Promise<FileDiffData> | null;
};

type CommitModeFilesCache = {
  files: DiffFileItem[];
  diffText?: string;
  commitFrom: string;
  commitTo: string;
};

export type RefreshOptions = { force?: boolean; reload_active?: boolean };

type CommitRangeResponse = {
  success?: boolean;
  error?: string | null;
  diff_text?: string;
  files?: Array<Record<string, unknown>>;
};

type DiffWindow = Window & {
  currentProjectRoot?: string | null;
  currentDiffMode?: string;
  currentDiffActivePath?: string | null;
  currentDiffText?: string | null;
  currentDiffViewMode?: string | null;
  EasterEgg?: { init: typeof initEasterEgg };
  refreshDiffAnalysis?: (options?: RefreshOptions) => Promise<void>;
  renderDiffFileList?: (files: Array<DiffFileItem | string>) => void;
  loadFileDiff?: (filePath: string, clickedEl?: HTMLElement | null, options?: { force?: boolean }) => Promise<void>;
  renderDiff2Html?: (diffText: string, outputFormat: DiffOutputFormat) => void;
  toggleDiffView?: (mode: string) => void;
  forceRenderLargeDiff?: () => void;
  resetDiffState?: () => void;
  initDiffModeDropdown?: () => void;
  initHeaderModeDropdown?: () => void;
  selectDiffMode?: (mode: string) => void;
  loadCommitHistory?: () => Promise<void>;
  loadCommitRangeDiff?: () => Promise<void>;
  getCurrentDiffSettings?: () => { mode: string; commit_from: string | null; commit_to: string | null };
  collapseCommitSelector?: (from: string | null, to: string | null) => void;
  expandCommitSelector?: () => void;
  showDiffContentEasterEgg?: (
    typeOrIsEmpty?: boolean | EasterEggType,
    diffMode?: string,
    data?: EasterEggData
  ) => void;
  onSelectCommitFrom?: (hash: string) => void;
  onSelectCommitTo?: (hash: string) => void;
  toggleCommitItem?: (event: Event, btn: HTMLElement) => void;
  toggleCommitDropdown?: (dropdownId: string) => void;
};

function legacyWindow(): DiffWindow {
  return window as DiffWindow;
}

const diffAnalysisCache = new Map<string, AnalysisEntry>();
const diffFileCache = new Map<string, FileEntry>();

let activeDiffItemEl: HTMLElement | null = null;
let manualDiffMode: DiffMode | null = null; // 用户手动选择的模式,null表示使用自动检测

// Commit模式相关状态
let currentDiffMode = "auto";
let commitHistoryData: GitCommit[] = [];
let selectedCommitFrom: string | null = null;
let selectedCommitTo = "HEAD";
let userExplicitlySelectedTo = false; // 用户是否明确选择了结束提交
let isEditingCommitRange = false; // 用户是否正在编辑提交范围
let commitModeFilesCache: CommitModeFilesCache | null = null; // 缓存commit模式加载的文件列表

// 显示彩蛋到 diff 内容区域
let isFirstEasterEggLoad = true;
let lastEasterEggType = "default";
let lastEasterEggData: EasterEggData = null;

// 初始化/生命周期
let initialized = false;
let abortController: AbortController | null = null;
let unsubscribeStore: (() => void) | null = null;
let prefetchTimerId: number | null = null;
let lastPrefetchProjectRoot: string | null = null;

function currentProjectRoot(): string | null {
  return useAppStore.getState().projectRoot;
}

function currentActivePath(): string | null {
  return legacyWindow().currentDiffActivePath ?? null;
}

function setCurrentActivePath(path: string | null): void {
  legacyWindow().currentDiffActivePath = path;
}

function currentDiffText(): string | null {
  return legacyWindow().currentDiffText ?? null;
}

function setCurrentDiffText(text: string | null): void {
  legacyWindow().currentDiffText = text;
}

function setCurrentDiffMode(mode: string): void {
  currentDiffMode = mode;
  legacyWindow().currentDiffMode = mode;
  useAppStore.getState().setCurrentDiffMode(mode);
}

function setCommitRange(from: string | null, to: string): void {
  useAppStore.getState().setCommitRange(from, to);
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      const error = new Error("The operation was aborted.");
      error.name = "AbortError";
      reject(error);
    }, timeoutMs);
    promise.then(
      (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(error);
      }
    );
  });
}

/**
 * 显示彩蛋到 diff 内容区域（旧版 diff.js:41-69）。
 */
export function showDiffContentEasterEgg(
  typeOrIsEmpty: boolean | EasterEggType = false,
  diffMode = "working",
  data: EasterEggData = null
): void {
  const contentArea = document.getElementById("diff-content-area");
  const EasterEgg = legacyWindow().EasterEgg;
  if (contentArea && EasterEgg) {
    // 兼容旧调用（布尔值）和新调用（字符串类型）
    let type: EasterEggType;
    if (typeof typeOrIsEmpty === "string") {
      type = typeOrIsEmpty;
    } else {
      type = typeOrIsEmpty ? "no-changes" : "default";
    }

    // 如果类型变化、数据变化或首次加载，使用动画
    const dataChanged = JSON.stringify(data) !== JSON.stringify(lastEasterEggData);
    const shouldAnimate = isFirstEasterEggLoad || lastEasterEggType !== type || dataChanged;

    if (shouldAnimate) {
      EasterEgg.init(contentArea, true, type, diffMode, data);
      isFirstEasterEggLoad = false;
    } else {
      // 状态没变，只显示静态以避免干扰
      EasterEgg.init(contentArea, false, type, diffMode, data);
    }

    lastEasterEggType = type;
    lastEasterEggData = data;
  } else if (contentArea) {
    contentArea.innerHTML = '<div class="empty-state">请选择文件查看 Diff</div>';
  }
}

// 获取当前diff设置 (供审查时使用)
export function getCurrentDiffSettings(): {
  mode: string;
  commit_from: string | null;
  commit_to: string | null;
} {
  const state = useAppStore.getState();
  return {
    mode: manualDiffMode || "auto",
    commit_from: manualDiffMode === "commit" ? state.commitFrom : null,
    commit_to: manualDiffMode === "commit" ? state.commitTo : null,
  };
}

/**
 * 刷新分析（旧版 diff.js:233-498）。
 */
export async function refreshDiffAnalysis(options: RefreshOptions = {}): Promise<void> {
  const diffFileList = document.getElementById("diff-file-list");
  if (!diffFileList) return;

  const projectRoot = currentProjectRoot();
  if (!projectRoot) {
    diffFileList.innerHTML = '<div class="empty-state">请先在仪表盘或审查页面选择项目</div>';
    return;
  }

  const force = Boolean(options && options.force);
  const now = Date.now();

  // 确定当前要使用的模式
  let targetMode = "working";
  if (manualDiffMode && manualDiffMode !== "auto") {
    targetMode = manualDiffMode;
  }

  // 对于commit模式，不走普通的diff分析流程
  if (targetMode === "commit") {
    setCurrentDiffMode("commit");
    updateReviewModeBadge("commit");

    // 显示commit选择面板
    const commitPanel = document.getElementById("commitSelectorPanel");
    if (commitPanel) commitPanel.style.display = "block";

    // 如果有缓存的commit模式文件列表，恢复显示
    if (commitModeFilesCache && commitModeFilesCache.files && commitModeFilesCache.files.length > 0) {
      updateDiffStatusHint("commit", commitModeFilesCache.files.length, Boolean(selectedCommitFrom));
      renderDiffFileList(commitModeFilesCache.files);
    } else {
      // 没有缓存数据，显示提示
      diffFileList.innerHTML = '<div class="empty-state">请选择提交范围后点击"查看"</div>';
    }
    return;
  }

  // 缓存键需要包含模式，避免模式切换时使用错误的缓存
  const key = `${projectRoot}::${targetMode}`;

  if (force) {
    try {
      diffAnalysisCache.delete(key);
    } catch {
      // 旧版同样吞掉异常
    }
    try {
      const prefix = `${projectRoot}::`;
      for (const k of Array.from(diffFileCache.keys())) {
        if (typeof k === "string" && k.startsWith(prefix)) {
          diffFileCache.delete(k);
        }
      }
    } catch {
      // 旧版同样吞掉异常
    }
  }

  const cached = diffAnalysisCache.get(key);
  if (!force && cached && cached.data && now - cached.ts < DIFF_CACHE_TTL_MS) {
    setCurrentDiffMode(cached.data.mode);
    updateDiffStatusHint(cached.data.mode, cached.data.files.length, Boolean(selectedCommitFrom));
    renderDiffFileList(cached.data.files);
    if (cached.data.files.length > 0 && !currentActivePath()) {
      showDiffContentEasterEgg(false);
    }
    return;
  }

  // 显示骨架屏加载动画
  diffFileList.innerHTML = `
        <div class="diff-loading-skeleton">
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title"></div>
                    <div class="skeleton-line subtitle"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title" style="width:75%"></div>
                    <div class="skeleton-line subtitle" style="width:50%"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title" style="width:55%"></div>
                    <div class="skeleton-line subtitle" style="width:35%"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title" style="width:65%"></div>
                    <div class="skeleton-line subtitle" style="width:45%"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
        </div>
        </div>
    `;

  // 如果右侧内容区为空，显示彩蛋
  // 这样在首次加载时（isFirstEasterEggLoad=true）会播放动画
  const contentArea = document.getElementById("diff-content-area");
  if (
    contentArea &&
    (!contentArea.innerHTML || contentArea.innerHTML.trim() === "" || contentArea.querySelector(".empty-state"))
  ) {
    showDiffContentEasterEgg();
  }

  if (!force && cached && cached.promise && now - cached.ts < DIFF_CACHE_TTL_MS) {
    try {
      await cached.promise;
    } catch {
      // 旧版同样忽略
    }
    return;
  }

  const promise: Promise<void> = (async () => {
    updateReviewModeBadge("loading"); // Show loading state immediately
    let reqMode = targetMode;

    // 使用新的轻量级快速状态 API（单次 git status 调用）
    // 只有在 auto 模式下才需要检测
    if (!manualDiffMode || manualDiffMode === "auto") {
      try {
        const quickData = await withTimeout(getDiffQuickStatus(projectRoot), DIFF_REQUEST_TIMEOUT_MS);
        if (!quickData.error) {
          // 直接使用快速 API 返回的数据
          reqMode = quickData.mode;
          setCurrentDiffMode(reqMode);

          const files = quickData.files || [];
          updateDiffStatusHint(reqMode, files.length, Boolean(selectedCommitFrom));
          diffAnalysisCache.set(key, { ts: Date.now(), data: { mode: reqMode, files }, promise: null });
          renderDiffFileList(files);

          if (files.length > 0 && !currentActivePath()) {
            showDiffContentEasterEgg(false);
          } else if (files.length === 0) {
            showDiffContentEasterEgg(true, reqMode);
          }

          if (options && options.reload_active && currentActivePath()) {
            reloadActiveFile();
          }

          return; // 快速路径完成，直接返回
        }
      } catch {
        // 快速 API 失败，回退到原来的流程
        console.log("[Diff] Quick status API failed, falling back to analyze API");
      }
    }

    // 回退路径：使用原来的 analyze API
    const data = await withTimeout(analyzeDiff(projectRoot, reqMode as DiffMode), DIFF_REQUEST_TIMEOUT_MS);

    let errorMsg: string | null = null;
    if (data && data.status && data.status.error) {
      errorMsg = String(data.status.error);
    } else if (data && data.summary && data.summary.error) {
      errorMsg = String(data.summary.error);
    }

    if (errorMsg) {
      if (errorMsg.indexOf("not a git repository") >= 0) {
        diffFileList.innerHTML = '<div class="empty-state">此目录不是 Git 仓库</div>';
        updateDiffStatusHint(reqMode, 0, Boolean(selectedCommitFrom));
      } else if (
        errorMsg.indexOf("No changes detected") >= 0 ||
        errorMsg.indexOf("No PR") >= 0 ||
        errorMsg.indexOf("no pull request") >= 0
      ) {
        diffFileList.innerHTML = '<div class="empty-state">未检测到所选模式的差异</div>';
        updateDiffStatusHint(reqMode, 0, Boolean(selectedCommitFrom));
        showDiffContentEasterEgg(true, reqMode);
      } else {
        diffFileList.innerHTML = '<div class="empty-state">' + escapeHtml(errorMsg) + "</div>";
        // 即使有错误也更新状态提示
        updateDiffStatusHint(reqMode, 0, Boolean(selectedCommitFrom));
        if (diffFileList.innerHTML.indexOf("empty-state") !== -1) {
          showDiffContentEasterEgg(true, reqMode);
        }
      }
      diffAnalysisCache.delete(key);
      return;
    }

    setCurrentDiffMode(reqMode);
    const files = data && data.files ? data.files : [];
    updateDiffStatusHint(reqMode, files.length, Boolean(selectedCommitFrom)); // Update status hint
    diffAnalysisCache.set(key, { ts: Date.now(), data: { mode: reqMode, files }, promise: null });
    renderDiffFileList(files);

    // 如果有文件，且当前没有选中的文件在查看（即刚加载完列表），确保彩蛋显示为"请选择文件"状态
    // 这会触发从 "无变更" -> "请选择文件" 的动画
    if (files.length > 0 && !currentActivePath()) {
      showDiffContentEasterEgg(false);
    }

    if (options && options.reload_active && currentActivePath()) {
      reloadActiveFile();
    }
  })();

  diffAnalysisCache.set(key, { ts: now, data: null, promise });

  try {
    await promise;
  } catch (e) {
    const latest = diffAnalysisCache.get(key);
    if (latest && latest.promise === promise) {
      diffAnalysisCache.delete(key);
    }
    console.error("Refresh diff error:", e);
    const error = e as { name?: string; message?: string };
    const msg =
      error && error.name === "AbortError"
        ? "请求超时，请稍后重试"
        : error && error.message
          ? error.message
          : "Unknown error";
    diffFileList.innerHTML = '<div style="padding:1rem;color:red;">Error: ' + escapeHtml(msg) + "</div>";
    // 更新状态提示为错误状态
    const hintBox = document.getElementById("diff-status-hint");
    const hintText = document.getElementById("diff-status-text");
    if (hintBox && hintText) {
      hintText.textContent = "加载失败";
      hintBox.style.background = "rgba(239, 68, 68, 0.1)";
      hintBox.style.border = "1px solid rgba(239, 68, 68, 0.2)";
    }
  }
}

function reloadActiveFile(): void {
  const p = currentActivePath();
  if (!p) return;
  let el: HTMLElement | null = null;
  try {
    const list = document.getElementById("diff-file-list");
    if (list) {
      const items = list.querySelectorAll<HTMLElement>(".file-list-item");
      for (const item of items) {
        let raw = item.getAttribute("data-path");
        if (!raw) continue;
        try {
          raw = decodeURIComponent(raw);
        } catch {
          // 保留原始值
        }
        if (raw === p) {
          el = item;
          break;
        }
      }
    }
  } catch {
    // 旧版同样忽略
  }
  void loadFileDiff(p, el, { force: true });
}

/**
 * 重置所有 diff 状态（切换项目时调用，旧版 diff.js:500-537）。
 */
export function resetDiffState(): void {
  try {
    diffAnalysisCache.clear();
  } catch {
    // 旧版同样忽略
  }
  try {
    diffFileCache.clear();
  } catch {
    // 旧版同样忽略
  }
  activeDiffItemEl = null;
  setCurrentDiffText(null);
  setCurrentActivePath(null);

  // 重置历史提交模式相关状态（关键：切换项目时必须重置）
  selectedCommitFrom = null;
  selectedCommitTo = "HEAD";
  commitHistoryData = [];
  commitModeFilesCache = null;
  userExplicitlySelectedTo = false;
  isEditingCommitRange = false;
  setCommitRange(null, "HEAD");

  // 重置历史提交选择器 UI
  const commitFromText = document.getElementById("commitFromText");
  const commitToText = document.getElementById("commitToText");
  if (commitFromText) commitFromText.textContent = "选择起始提交...";
  if (commitToText) commitToText.textContent = "HEAD (最新)";

  // 清空提交历史菜单
  const fromMenu = document.getElementById("commitFromMenu");
  const toMenu = document.getElementById("commitToMenu");
  if (fromMenu) fromMenu.innerHTML = "";
  if (toMenu) toMenu.innerHTML = "";

  const diffFileList = document.getElementById("diff-file-list");
  if (diffFileList) {
    diffFileList.innerHTML = '<div class="empty-state">请先在仪表盘或审查页面选择项目</div>';
  }
  const diffContentArea = document.getElementById("diff-content-area");
  if (diffContentArea) {
    diffContentArea.innerHTML = '<div class="empty-state">请选择左侧文件查看差异</div>';
  }
}

/**
 * 重置 diff 内容区域状态（用于模式切换时）
 * 只有当前有选中文件时才清空面板，避免打断正在播放的彩蛋动画
 * @returns 是否需要重新显示彩蛋（true = 之前有选中文件，现在需要切换到彩蛋）
 */
function resetDiffContentArea(mode: string): boolean {
  // 检查当前是否有选中的文件
  const hadActiveFile = Boolean(currentActivePath() || currentDiffText());

  // 清空当前 diff 数据
  setCurrentDiffText(null);
  setCurrentActivePath(null);

  // 清除文件列表中的活动状态
  if (activeDiffItemEl) {
    activeDiffItemEl.classList.remove("active");
    activeDiffItemEl = null;
  }

  // 只有当之前有选中文件时，才需要清空右侧面板
  if (hadActiveFile) {
    const diffContentArea = document.getElementById("diff-content-area");
    if (diffContentArea) {
      // 直接清空，让后续的 showDiffContentEasterEgg 重新渲染
      diffContentArea.innerHTML = "";
    }
    console.log("[Diff] Content area reset for mode:", mode, "(had active file)");
  } else {
    console.log("[Diff] Mode switch to:", mode, "(keeping easter egg)");
  }

  return hadActiveFile;
}

/**
 * 渲染文件列表（旧版 diff.js:574-642）。
 * 重渲染后 activeDiffItemEl 置空 —— 旧版的“丢高亮”缺陷必须保留。
 */
export function renderDiffFileList(files: Array<DiffFileItem | string> | null | undefined): void {
  const diffFileList = document.getElementById("diff-file-list");
  if (!diffFileList) return;

  if (!files || files.length === 0) {
    diffFileList.innerHTML = '<div class="empty-state">无文件变更</div>';
    // 显示空状态彩蛋
    showDiffContentEasterEgg(true, currentDiffMode || "working");
    return;
  }

  // Fast render via single innerHTML + event delegation
  const html = files
    .map((file) => {
      const requestPath = typeof file === "string" ? file : file.path || "Unknown File";
      const displayPath = typeof file === "object" && file && file.display_path ? file.display_path : requestPath;
      const changeType = typeof file === "object" ? file.change_type : "modify";

      // 使用 Git 标准状态字母
      const icon = getIcon("file");
      let statusClass = "status-modify";
      let statusLetter = "M";

      if (changeType === "add") {
        statusClass = "status-add";
        statusLetter = "A";
      } else if (changeType === "delete") {
        statusClass = "status-delete";
        statusLetter = "D";
      } else if (changeType === "rename") {
        statusClass = "status-rename";
        statusLetter = "R";
      }

      const fileName = displayPath.split("/").pop() || "";
      const dirPath = displayPath.substring(0, displayPath.lastIndexOf("/"));

      const encodedPath = encodeURIComponent(requestPath);
      return `
            <div class="file-list-item ${statusClass}" data-path="${encodedPath}">
                <div class="file-item-row">
                    <span class="file-icon">${icon}</span>
                    <div class="file-info">
                        <div class="file-name" title="${escapeHtml(displayPath)}">${escapeHtml(fileName)}</div>
                        <div class="file-path" title="${escapeHtml(dirPath)}">${escapeHtml(dirPath)}</div>
                    </div>
                    <span class="file-status-badge ${statusClass}">${statusLetter}</span>
                </div>
            </div>
        `;
    })
    .join("");

  diffFileList.innerHTML = html;

  // Reset active state pointer after re-render
  activeDiffItemEl = null;
}

function onFileListClick(event: MouseEvent): void {
  const diffFileList = document.getElementById("diff-file-list");
  if (!diffFileList) return;
  const target = event.target instanceof Element ? event.target : null;
  const item = target ? target.closest<HTMLElement>(".file-list-item") : null;
  if (!item || !diffFileList.contains(item)) return;
  const raw = item.getAttribute("data-path");
  if (!raw) return;
  let p = raw;
  try {
    p = decodeURIComponent(raw);
  } catch {
    // 保留原始值
  }
  void loadFileDiff(p, item);
}

/**
 * 加载单文件 Diff（旧版 diff.js:644-756）。
 */
export async function loadFileDiff(
  filePath: string,
  clickedEl: HTMLElement | null = null,
  options: { force?: boolean } = {}
): Promise<void> {
  const diffContentArea = document.getElementById("diff-content-area");
  const diffFileList = document.getElementById("diff-file-list");
  if (!diffContentArea) return;

  const projectRoot = currentProjectRoot();
  if (!projectRoot) {
    diffContentArea.innerHTML = '<div style="padding:1rem;color:red;">请先选择项目文件夹</div>';
    return;
  }

  diffContentArea.innerHTML = '<div class="empty-state">Loading...</div>';

  if (diffFileList && clickedEl) {
    if (activeDiffItemEl && activeDiffItemEl !== clickedEl) {
      activeDiffItemEl.classList.remove("active");
    }
    clickedEl.classList.add("active");
    activeDiffItemEl = clickedEl;
  }

  setCurrentActivePath(filePath);

  try {
    const cacheKey = `${projectRoot}::${currentDiffMode}::${filePath}`;
    const now = Date.now();
    const force = Boolean(options && options.force);
    if (force) {
      try {
        diffFileCache.delete(cacheKey);
      } catch {
        // 旧版同样忽略
      }
    }
    const cached = force ? null : diffFileCache.get(cacheKey);

    let data: FileDiffData | null = null;
    if (cached && cached.data && now - cached.ts < DIFF_CACHE_TTL_MS) {
      data = cached.data;
    } else {
      const inFlight = Boolean(cached && cached.promise && now - cached.ts < DIFF_CACHE_TTL_MS);
      const promise = inFlight
        ? (cached!.promise as Promise<FileDiffData>)
        : (async () => {
            const state = useAppStore.getState();
            const d = await withTimeout(
              getFileDiff({
                filePath,
                projectRoot,
                mode: currentDiffMode,
                commitFrom: currentDiffMode === "commit" ? state.commitFrom : undefined,
                commitTo: currentDiffMode === "commit" ? state.commitTo || undefined : undefined,
              }),
              DIFF_REQUEST_TIMEOUT_MS
            );
            diffFileCache.set(cacheKey, { ts: Date.now(), data: d, promise: null });
            return d;
          })();

      if (!inFlight) {
        diffFileCache.set(cacheKey, { ts: now, data: null, promise });
      }

      try {
        data = await promise;
      } catch (e) {
        const latest = diffFileCache.get(cacheKey);
        if (latest && latest.promise === promise) {
          diffFileCache.delete(cacheKey);
        }
        throw e;
      }
    }

    if (data.error) {
      diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">${escapeHtml(data.error)}</div>`;
      return;
    }

    const diffText = data.diff_text || data.diff_content || "";

    if (window.Diff2HtmlUI && diffText.trim()) {
      const currentViewMode = legacyWindow().currentDiffViewMode || "side-by-side";

      diffContentArea.innerHTML = `
                <div class="diff-header">
                    <h3 title="${escapeHtml(filePath)}">${escapeHtml(filePath)}</h3>
                    <div class="diff-controls">
                        <label class="${currentViewMode === "line-by-line" ? "active" : ""}">
                            <input type="radio" name="diff-view" value="line-by-line" ${currentViewMode === "line-by-line" ? "checked" : ""} onclick="toggleDiffView('line-by-line')">
                            <span class="view-option">Unified</span>
                        </label>
                        <label class="${currentViewMode === "side-by-side" ? "active" : ""}">
                            <input type="radio" name="diff-view" value="side-by-side" ${currentViewMode === "side-by-side" ? "checked" : ""} onclick="toggleDiffView('side-by-side')">
                            <span class="view-option">Split</span>
                        </label>
                    </div>
                </div>
                <div id="diff-ui-container" style="padding: 0;"></div>
            `;

      setCurrentDiffText(diffText);
      renderDiff2HtmlInto(document.getElementById("diff-ui-container"), diffText, currentViewMode as DiffOutputFormat);
    } else {
      renderPlainDiff(diffContentArea, filePath, diffText);
    }
  } catch (e) {
    console.error("Load file diff error:", e);
    const error = e as { name?: string; message?: string };
    const msg =
      error && error.name === "AbortError"
        ? "请求超时，请稍后重试"
        : error && error.message
          ? error.message
          : "Unknown error";
    diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">Error: ${escapeHtml(msg)}</div>`;
  }
}

/**
 * 选择 diff 模式（旧版 diff.js:941-1028）。
 */
export function selectDiffMode(mode: string): void {
  if (mode === "commit") {
    const store = useAppStore.getState();
    if (store.activePage !== "diff") store.setActivePage("diff");
  }

  manualDiffMode = mode as DiffMode;
  useAppStore.getState().setDiffMode(mode as DiffMode);
  setCurrentDiffMode(mode);

  // 更新显示文本
  const modeNames: Record<string, string> = {
    auto: "自动检测",
    working: "工作区",
    staged: "暂存区",
    pr: "PR模式",
    commit: "历史提交",
  };

  const text = document.getElementById("selectedDiffModeText");
  if (text) {
    text.textContent = modeNames[mode] || "自动检测";
  }

  // 处理commit模式的面板显示
  const commitPanel = document.getElementById("commitSelectorPanel");
  const diffFileList = document.getElementById("diff-file-list");

  if (commitPanel) {
    if (mode === "commit") {
      commitPanel.style.display = "block";

      // [模式切换] 重置右侧面板状态（只有之前有选中文件时才清空）
      const needShowEasterEgg = resetDiffContentArea(mode);

      // 如果有缓存数据，恢复显示而不是清空
      if (commitModeFilesCache && commitModeFilesCache.files && commitModeFilesCache.files.length > 0) {
        updateDiffStatusHint("commit", commitModeFilesCache.files.length, Boolean(selectedCommitFrom));
        renderDiffFileList(commitModeFilesCache.files);
        // 只有之前有选中文件时才需要重新显示彩蛋
        if (needShowEasterEgg) {
          showDiffContentEasterEgg("default", "commit");
        }
      } else {
        // 没有缓存，显示提示并更新状态提示
        updateDiffStatusHint("commit", 0, Boolean(selectedCommitFrom));
        if (diffFileList) diffFileList.innerHTML = '<div class="empty-state">请选择提交范围后点击"查看"</div>';
        // 切换到 commit 模式的特殊彩蛋需要显示（无论之前是什么状态）
        showDiffContentEasterEgg("waiting-commit", "commit");
      }
      // 立即更新主界面徽章
      updateReviewModeBadge("commit");
      void loadCommitHistory(); // 自动加载commit历史
      return; // commit模式不自动刷新,需要用户选择后手动加载
    } else {
      commitPanel.style.display = "none";
      // 切换离开commit模式时，清除缓存和状态
      commitModeFilesCache = null;
      selectedCommitFrom = null;
      selectedCommitTo = "HEAD";
      setCommitRange(null, "HEAD"); // 关键：清除发送到 API 的 commit 变量
      userExplicitlySelectedTo = false;
    }
  }

  // [模式切换] 重置右侧面板状态（只有之前有选中文件时才清空）
  const needShowEasterEgg = resetDiffContentArea(mode);

  // 立即显示加载状态，防止残留旧消息
  const hintBox = document.getElementById("diff-status-hint");
  const hintText = document.getElementById("diff-status-text");
  if (hintBox && hintText) {
    hintText.textContent = "正在加载...";
    hintBox.style.background = "rgba(156, 163, 175, 0.1)";
    hintBox.style.border = "1px solid rgba(156, 163, 175, 0.2)";
  }

  // 只有之前有选中文件时才需要重新显示彩蛋
  if (needShowEasterEgg) {
    showDiffContentEasterEgg("default", mode === "auto" ? "working" : mode);
  }

  // 刷新diff分析
  void refreshDiffAnalysis({ force: true, reload_active: false });
}

// ========== Commit模式相关函数 ==========

// 切换Commit下拉菜单显示
export function toggleCommitDropdown(dropdownId: string): void {
  const dropdown = document.getElementById(dropdownId);
  if (!dropdown) return;

  // 关闭其他打开的菜单
  document.querySelectorAll(".custom-dropdown.open").forEach((el) => {
    if (el.id !== dropdownId) el.classList.remove("open");
  });

  dropdown.classList.toggle("open");
}

// 展开/收起Commit消息
export function toggleCommitItem(event: Event, btn: HTMLElement): void {
  event.stopPropagation(); // 阻止触发选择
  const item = btn.closest(".commit-item");
  if (item) {
    item.classList.toggle("expanded");
  }
}

// 渲染Commit菜单项 (通用)
function renderCommitHtml(commit: GitCommit, clickHandlerName: string): string {
  const shortHash = commit.hash?.substring(0, 7) || "";
  const msg = (commit.message || "").trim();
  const dateStr = commit.date ? new Date(commit.date).toLocaleDateString() : "";

  // 判断是否有更多内容（多行或长度超过限制）
  const isLong = msg.length > 50 || msg.includes("\n");
  const expandBtn = isLong
    ? `<div class="commit-expand-btn" onclick="toggleCommitItem(event, this)" title="展开完整消息">
             <svg class="icon" style="width:12px;height:12px;"><use href="#icon-chevron-down"></use></svg>
           </div>`
    : "";

  return `
        <div class="commit-item" data-hash="${commit.hash}">
            <div class="commit-content-clickable" onclick="${clickHandlerName}('${commit.hash}')">
                <div class="commit-info-row">
                    <span class="commit-hash">${shortHash}</span>
                    <span class="commit-date">${dateStr}</span>
                </div>
            </div>
            <div class="commit-msg-row">
                 <div class="commit-msg" onclick="${clickHandlerName}('${commit.hash}')" title="${escapeHtml(msg)}">${escapeHtml(msg)}</div>
                 ${expandBtn}
            </div>
        </div>
    `;
}

// 加载commit历史
export async function loadCommitHistory(): Promise<void> {
  const fromMenu = document.getElementById("commitFromMenu");
  const toMenu = document.getElementById("commitToMenu");
  const fromText = document.getElementById("commitFromText");

  if (!fromMenu || !toMenu) return;

  // 显示加载状态
  if (fromText) fromText.textContent = "加载中...";

  try {
    const data = await getCommits(currentProjectRoot() || "", 50);
    commitHistoryData = data.commits || [];

    // 渲染起始菜单
    let fromHtml = "";
    commitHistoryData.forEach((commit) => {
      fromHtml += renderCommitHtml(commit, "onSelectCommitFrom");
    });
    fromMenu.innerHTML = fromHtml;
    if (fromText) fromText.textContent = "选择起始提交...";

    // 渲染结束菜单 (默认包含HEAD)
    renderToMenu();
  } catch (e) {
    console.error("Failed to load commit history:", e);
    if (fromText) fromText.textContent = "加载失败";
  }
}

// 渲染结束菜单 (基于起始commit过滤)
function renderToMenu(): void {
  const toMenu = document.getElementById("commitToMenu");
  if (!toMenu) return;

  let toHtml = `
        <div class="commit-item" onclick="onSelectCommitTo('HEAD')">
            <div class="commit-content-clickable">
                <div class="commit-info-row">
                    <span class="commit-hash">HEAD</span>
                    <span class="commit-tag">当前工作区</span>
                </div>
            </div>
             <div class="commit-msg-row">
                <div class="commit-msg">最新状态</div>
             </div>
        </div>
    `;

  // 如果选择了起始commit，只显示它之前的commit (索引更小)
  let startIndex = -1;
  if (selectedCommitFrom) {
    startIndex = commitHistoryData.findIndex((c) => c.hash === selectedCommitFrom);
  }

  const limitIndex = startIndex === -1 ? commitHistoryData.length : startIndex;

  for (let i = 0; i < limitIndex; i++) {
    const commit = commitHistoryData[i];
    toHtml += renderCommitHtml(commit, "onSelectCommitTo");
  }

  toMenu.innerHTML = toHtml;
}

// 选择起始Commit
export function onSelectCommitFrom(hash: string): void {
  selectedCommitFrom = hash;
  const commit = commitHistoryData.find((c) => c.hash === hash);
  const textEl = document.getElementById("commitFromText");
  if (textEl && commit) {
    textEl.textContent = `${commit.hash.substring(0, 7)} - ${commit.message.split("\n")[0]}`;
  }

  // 与旧版对齐：选择只更新待选值，成功加载后才写入生效的 commit 范围。

  // 关闭菜单
  document.getElementById("commitFromDropdown")?.classList.remove("open");

  // 重置并更新结束菜单
  // 如果当前的结束commit比起始commit更早（在列表中索引更大），则需重置
  // 简单起见，每次改变起始，结束若不合法则重置为HEAD
  const fromIndex = commitHistoryData.findIndex((c) => c.hash === hash);
  const toIndex = selectedCommitTo === "HEAD" ? -1 : commitHistoryData.findIndex((c) => c.hash === selectedCommitTo);

  if (toIndex > fromIndex && toIndex !== -1) {
    // reset to HEAD
    onSelectCommitTo("HEAD");
  }

  renderToMenu();

  // 智能自动加载：
  // - 如果用户已经明确选择了结束提交，且不在编辑模式，则自动加载
  // - 编辑模式下需要用户点击"查看变更"按钮
  if (userExplicitlySelectedTo && !isEditingCommitRange) {
    void loadCommitRangeDiff();
  }
}

// 选择结束Commit
export function onSelectCommitTo(hash: string): void {
  selectedCommitTo = hash;
  const textEl = document.getElementById("commitToText");
  if (textEl) {
    if (hash === "HEAD") {
      textEl.textContent = "HEAD (最新)";
    } else {
      const commit = commitHistoryData.find((c) => c.hash === hash);
      if (commit) {
        textEl.textContent = `${commit.hash.substring(0, 7)} - ${commit.message.split("\n")[0]}`;
      }
    }
  }

  document.getElementById("commitToDropdown")?.classList.remove("open");

  // 标记用户已明确选择了结束提交
  userExplicitlySelectedTo = true;

  // 智能自动加载：
  // - 如果不在编辑模式（首次选择），选择To后自动加载
  // - 如果在编辑模式，需要用户点击"查看变更"按钮
  if (selectedCommitFrom && !isEditingCommitRange) {
    void loadCommitRangeDiff();
  }
}

// 加载commit范围的diff
export async function loadCommitRangeDiff(): Promise<void> {
  if (!selectedCommitFrom) {
    window.alert("请选择起始Commit");
    return;
  }

  const commitFrom = selectedCommitFrom;
  const commitTo = selectedCommitTo || "HEAD";

  const fileListEl = document.getElementById("diff-file-list");
  const contentArea = document.getElementById("diff-content-area");

  if (fileListEl) fileListEl.innerHTML = '<div class="empty-state">加载中...</div>';
  // 使用彩蛋显示加载状态，而不是简单的"加载中"文本
  showDiffContentEasterEgg("commit-selected", "commit", { from: commitFrom, to: commitTo });

  try {
    const data = (await getCommitRange(currentProjectRoot() || "", commitFrom, commitTo)) as CommitRangeResponse;

    if (!data.success) {
      if (fileListEl) {
        fileListEl.innerHTML = `<div class="empty-state" style="color:#ef4444;">${escapeHtml(
          data.error || "加载失败"
        )}</div>`;
      }
      updateDiffStatusHint("commit", 0, Boolean(selectedCommitFrom));
      return;
    }

    if (!data.files || data.files.length === 0) {
      if (fileListEl) fileListEl.innerHTML = '<div class="empty-state">该范围内没有文件变更</div>';
      if (contentArea) contentArea.innerHTML = '<div class="empty-state">没有变更内容</div>';
      updateDiffStatusHint("commit", 0, Boolean(selectedCommitFrom));
      return;
    }

    // 渲染文件列表
    const filesForRender: DiffFileItem[] = data.files.map((f) => {
      const added = Number(f.added_lines ?? 0);
      const removed = Number(f.removed_lines ?? 0);
      const changeType =
        (f.change_type as string | undefined) ||
        (added > 0 && removed === 0 ? "add" : removed > 0 && added === 0 ? "delete" : "modify");
      return {
        // 优先使用后端返回的 change_type，否则使用行数判断作为后备
        path: String(f.path || f.target_file || ""),
        language: "unknown",
        change_type: changeType,
        lines_added: added,
        lines_removed: removed,
      };
    });

    // 保存commit范围到全局状态(供审查时使用)
    setCommitRange(commitFrom, commitTo);

    // 缓存commit模式的文件列表，以便页面切换后恢复
    commitModeFilesCache = {
      files: filesForRender,
      diffText: data.diff_text,
      commitFrom: commitFrom,
      commitTo: commitTo,
    };

    updateDiffStatusHint("commit", filesForRender.length, Boolean(selectedCommitFrom));
    renderDiffFileList(filesForRender);

    showDiffContentEasterEgg("commit-selected", "commit", { from: commitFrom, to: commitTo });

    // 加载成功后折叠选择器，更新摘要
    collapseCommitSelector(commitFrom, commitTo);
  } catch (e) {
    console.error("Failed to load commit diff:", e);
    if (fileListEl) {
      fileListEl.innerHTML = `<div class="empty-state" style="color:#ef4444;">请求失败: ${
        (e as Error).message
      }</div>`;
    }
  }
}

// 折叠提交选择器，显示摘要
export function collapseCommitSelector(fromHash: string | null, toHash: string | null): void {
  const card = document.getElementById("commitRangeCard");
  const summaryFrom = document.getElementById("summaryFromHash");
  const summaryTo = document.getElementById("summaryToHash");

  if (card) {
    // 更新摘要显示
    if (summaryFrom) {
      summaryFrom.textContent = fromHash ? fromHash.substring(0, 7) : "---";
    }
    if (summaryTo) {
      summaryTo.textContent = toHash === "HEAD" ? "HEAD" : toHash ? toHash.substring(0, 7) : "HEAD";
    }

    // 添加折叠效果
    card.classList.add("collapsed");

    // 清除编辑状态
    isEditingCommitRange = false;
  }
}

// 展开提交选择器
export function expandCommitSelector(): void {
  const card = document.getElementById("commitRangeCard");
  if (card) {
    card.classList.remove("collapsed");

    // 设置编辑状态，防止自动折叠
    isEditingCommitRange = true;

    // 重置选择状态，要求用户重新选择两个提交
    userExplicitlySelectedTo = false;
  }
}

function scheduleProjectPrefetch(): void {
  const projectRoot = currentProjectRoot();
  if (!projectRoot) return;

  // Avoid re-prefetching the same project repeatedly
  if (lastPrefetchProjectRoot === projectRoot) return;

  if (prefetchTimerId != null) {
    window.clearTimeout(prefetchTimerId);
  }

  prefetchTimerId = window.setTimeout(() => {
    prefetchTimerId = null;
    // Ensure user didn't switch projects during debounce
    if (currentProjectRoot() !== projectRoot) return;
    lastPrefetchProjectRoot = projectRoot;
    void refreshDiffAnalysis();
  }, 150);
}

/**
 * 挂载控制器：绑定下拉、外部点击、文件列表委托、store 订阅与全局函数。
 */
export function initDiffPage(): void {
  if (initialized) return;
  initialized = true;

  const w = legacyWindow();
  w.EasterEgg = { init: initEasterEgg };
  w.refreshDiffAnalysis = (options) => refreshDiffAnalysis(options);
  w.renderDiffFileList = (files) => renderDiffFileList(files);
  w.loadFileDiff = (filePath, clickedEl, options) => loadFileDiff(filePath, clickedEl ?? null, options ?? {});
  w.renderDiff2Html = (diffText, outputFormat) =>
    renderDiff2HtmlInto(document.getElementById("diff-ui-container"), diffText, outputFormat);
  w.toggleDiffView = (mode) => toggleDiffView(mode);
  w.forceRenderLargeDiff = () => forceRenderLargeDiff();
  w.resetDiffState = () => resetDiffState();
  w.initDiffModeDropdown = () => {
    // 下拉已由 React onClick 绑定，保留旧版全局入口
  };
  w.initHeaderModeDropdown = () => {
    // 顶部徽章下拉由 ReviewController 绑定，保留旧版全局入口
  };
  w.selectDiffMode = (mode) => selectDiffMode(mode);
  w.loadCommitHistory = () => loadCommitHistory();
  w.loadCommitRangeDiff = () => loadCommitRangeDiff();
  w.getCurrentDiffSettings = () => getCurrentDiffSettings();
  w.collapseCommitSelector = (from, to) => collapseCommitSelector(from, to);
  w.expandCommitSelector = () => expandCommitSelector();
  w.showDiffContentEasterEgg = (typeOrIsEmpty, diffMode, data) =>
    showDiffContentEasterEgg(typeOrIsEmpty, diffMode, data);
  w.onSelectCommitFrom = (hash) => onSelectCommitFrom(hash);
  w.onSelectCommitTo = (hash) => onSelectCommitTo(hash);
  w.toggleCommitItem = (event, btn) => toggleCommitItem(event, btn);
  w.toggleCommitDropdown = (dropdownId) => toggleCommitDropdown(dropdownId);

  // 旧版这些按钮/触发器使用内联 onclick（index.html:570-646），
  // React 的 onClick 不会产生 onclick 属性，这里按旧版写法补回，保证 DOM 一致。
  const pageDiff = document.getElementById("page-diff");
  pageDiff
    ?.querySelector<HTMLElement>(".commit-range-header")
    ?.setAttribute("onclick", "expandCommitSelector()");
  pageDiff?.querySelector<HTMLElement>(".change-btn")?.setAttribute("onclick", "expandCommitSelector()");
  pageDiff?.querySelector<HTMLElement>(".commit-view-btn")?.setAttribute("onclick", "loadCommitRangeDiff()");
  pageDiff
    ?.querySelector<HTMLElement>(".header-actions > .btn-primary")
    ?.setAttribute("onclick", "refreshDiffAnalysis({ force: true, reload_active: true })");
  document.getElementById("commitFromTrigger")?.setAttribute("onclick", "toggleCommitDropdown('commitFromDropdown')");
  document.getElementById("commitToTrigger")?.setAttribute("onclick", "toggleCommitDropdown('commitToDropdown')");

  const controller = new AbortController();
  abortController = controller;

  // 全局点击事件监听：点击外部关闭下拉菜单
  document.addEventListener(
    "click",
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target || !target.closest(".custom-dropdown")) {
        document.querySelectorAll(".custom-dropdown.open").forEach((el) => {
          el.classList.remove("open");
        });
      }
    },
    { signal: controller.signal }
  );

  // diff 模式下拉：点击外部关闭（旧版 initDiffModeDropdown 的第二段逻辑）
  document.addEventListener(
    "click",
    (event) => {
      const dropdown = document.getElementById("diffModeDropdown");
      const target = event.target;
      if (dropdown && target instanceof Node && !dropdown.contains(target)) {
        dropdown.classList.remove("open");
      }
    },
    { signal: controller.signal }
  );

  // 审查页切换 / 头部模式徽章选择都会派发该事件（旧版 navigation.js:42）
  window.addEventListener(
    "dc:refresh-diff-analysis",
    () => {
      void refreshDiffAnalysis();
    },
    { signal: controller.signal }
  );

  document.getElementById("diff-file-list")?.addEventListener("click", onFileListClick, {
    signal: controller.signal,
  });

  unsubscribeStore = useAppStore.subscribe((state, prevState) => {
    if (state.projectRoot !== prevState.projectRoot) {
      w.currentProjectRoot = state.projectRoot;
      resetDiffState();
      scheduleProjectPrefetch();
    }
    // 审查页顶部的模式徽章下拉由 ReviewController 驱动 store.diffMode，
    // 这里同步执行旧版 selectDiffMode 的页面级副作用。
    if (state.diffMode !== prevState.diffMode && state.diffMode !== manualDiffMode) {
      selectDiffMode(state.diffMode);
    }
  });

  w.currentProjectRoot = useAppStore.getState().projectRoot;
  w.currentDiffMode = currentDiffMode;
  if (w.currentProjectRoot) {
    // 旧版 app.js:initializeGlobalState 恢复上次项目路径时会先 resetDiffState()
    resetDiffState();
  }
  scheduleProjectPrefetch();
}

/**
 * 卸载控制器：移除监听与订阅。旧版页面从不卸载，这里仅用于 React StrictMode。
 * 模块作用域状态（模式、缓存、commit 选择）保留，与旧版全局变量一致。
 */
export function disposeDiffPage(): void {
  abortController?.abort();
  abortController = null;
  unsubscribeStore?.();
  unsubscribeStore = null;
  if (prefetchTimerId != null) {
    window.clearTimeout(prefetchTimerId);
    prefetchTimerId = null;
  }
  // 仅用于 React StrictMode 的重复挂载：取消仍在进行的彩蛋动画
  disposeEasterEgg(document.getElementById("diff-content-area"));
  initialized = false;
}
