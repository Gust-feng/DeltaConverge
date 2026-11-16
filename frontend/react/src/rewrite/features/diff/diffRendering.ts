/**
 * Diff2Html 渲染与“大文件”保护，逐行对应 legacy/ui_v1/static/modules/diff.js:
 * renderDiff2Html(:758-834) / forceRenderLargeDiff(:837-876) / toggleDiffView(:878-896)。
 *
 * 实际绘制委托给共享层 lib/diff.ts 的 renderDiff2Html；这里只补齐旧版的两个
 * 可观察细节：
 *  1. 阻止渲染时把 `{diffText, outputFormat}` 存入 `window._pendingLargeDiff`；
 *  2. 强制渲染按钮保留旧版的内联 `onclick="forceRenderLargeDiff()"`。
 */

import {
  MAX_DIFF_CHARS_BLOCK,
  MAX_DIFF_LINES_BLOCK,
  renderDiff2Html,
  type DiffOutputFormat,
} from "../../lib/diff";

type PendingLargeDiff = { diffText: string; outputFormat: DiffOutputFormat };

type RenderWindow = Window & {
  _pendingLargeDiff?: PendingLargeDiff | null;
  currentDiffText?: string | null;
  currentDiffViewMode?: string | null;
};

export function renderWindow(): RenderWindow {
  return window as RenderWindow;
}

export function renderDiff2HtmlInto(
  targetElement: HTMLElement | null,
  diffText: string,
  outputFormat: DiffOutputFormat
): void {
  if (!targetElement || !window.Diff2HtmlUI) return;

  // 与旧版一致的阈值判断（旧版在渲染阻止页之后保存 pending 数据）
  const lineCount = (diffText.match(/\n/g) || []).length;
  const charCount = diffText.length;
  if (lineCount > MAX_DIFF_LINES_BLOCK || charCount > MAX_DIFF_CHARS_BLOCK) {
    renderWindow()._pendingLargeDiff = { diffText, outputFormat };
  }

  // 共享层渲染（不传回调，按钮的点击行为改由旧版全局函数承担）
  renderDiff2Html(targetElement, diffText, outputFormat);

  // 共享层使用 data-action + addEventListener；旧版是内联 onclick。
  // 还原成旧版 DOM，保证“强制渲染”按钮逐字一致。
  const button = targetElement.querySelector<HTMLButtonElement>('[data-action="force-render-large-diff"]');
  if (button) {
    button.removeAttribute("data-action");
    button.setAttribute("onclick", "forceRenderLargeDiff()");
  }
}

// 强制渲染大型diff（用户明确选择）
export function forceRenderLargeDiff(): void {
  const pending = renderWindow()._pendingLargeDiff;
  if (!pending) return;

  const { diffText, outputFormat } = pending;
  const targetElement = document.getElementById("diff-ui-container");
  if (!targetElement) return;

  targetElement.innerHTML = '<div style="padding:1rem;color:var(--text-muted);">正在渲染大型文件，请稍候...</div>';

  // 使用 requestIdleCallback 或 setTimeout 延迟渲染，避免阻塞UI
  const doRender = () => {
    try {
      const configuration = {
        drawFileList: false,
        fileListToggle: false,
        fileContentToggle: false,
        matching: "none",
        outputFormat: outputFormat,
        synchronisedScroll: false,
        highlight: false, // 禁用高亮以提高性能
        renderNothingWhenEmpty: false,
      };

      targetElement.innerHTML = "";
      const diff2htmlUi = new window.Diff2HtmlUI!(targetElement, diffText, configuration);
      diff2htmlUi.draw();
      renderWindow()._pendingLargeDiff = null;
    } catch (e) {
      console.error("Force render failed:", e);
      targetElement.innerHTML =
        '<div style="padding:1rem;color:red;">渲染失败: ' + (e as Error).message + "</div>";
    }
  };

  // 使用 requestIdleCallback 如果可用，否则用 setTimeout
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(doRender, { timeout: 2000 });
  } else {
    window.setTimeout(doRender, 100);
  }
}

export function toggleDiffView(mode: string): void {
  renderWindow().currentDiffViewMode = mode;

  const controls = document.querySelector(".diff-controls");
  if (controls) {
    controls.querySelectorAll("label").forEach((label) => {
      const input = label.querySelector("input");
      if (input && input.value === mode) {
        label.classList.add("active");
      } else {
        label.classList.remove("active");
      }
    });
  }

  const currentDiffText = renderWindow().currentDiffText;
  if (currentDiffText) {
    renderDiff2HtmlInto(
      document.getElementById("diff-ui-container"),
      currentDiffText,
      mode as DiffOutputFormat
    );
  }
}
