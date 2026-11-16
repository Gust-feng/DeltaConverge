import { escapeHtml } from "./html";

declare global {
  interface Window {
    Diff2HtmlUI?: new (
      target: HTMLElement,
      diffText: string,
      config?: Record<string, unknown>
    ) => {
      draw(): void;
      highlightCode(): void;
    };
  }
}

export const MAX_DIFF_LINES_WARNING = 5000;
export const MAX_DIFF_LINES_BLOCK = 20000;
export const MAX_DIFF_CHARS_WARNING = 200000;
export const MAX_DIFF_CHARS_BLOCK = 500000;

export type DiffOutputFormat = "side-by-side" | "line-by-line";

/**
 * 与 legacy/ui_v1/static/modules/diff.js:renderDiff2Html 完全一致的渲染策略：
 * - 超过阻止阈值：显示“文件过大”提示，可强制渲染
 * - 超过警告阈值：先提示，再延迟用简化配置渲染
 * - 正常：Diff2HtmlUI 绘制 + 语法高亮
 */
export function renderDiff2Html(
  targetElement: HTMLElement | null,
  diffText: string,
  outputFormat: DiffOutputFormat,
  onForceRender?: () => void
): void {
  if (!targetElement || !window.Diff2HtmlUI) return;

  const lineCount = (diffText.match(/\n/g) || []).length;
  const charCount = diffText.length;
  const fileSizeKB = Math.round(charCount / 1024);

  if (lineCount > MAX_DIFF_LINES_BLOCK || charCount > MAX_DIFF_CHARS_BLOCK) {
    targetElement.innerHTML = `
      <div class="diff-size-warning" style="padding: 2rem; text-align: center; color: #dc2626;">
        <svg class="icon" style="width:48px;height:48px;margin-bottom:1rem;"><use href="#icon-alert-triangle"></use></svg>
        <h3>文件过大，无法显示</h3>
        <p>此差异包含 ${lineCount.toLocaleString()} 行，约 ${fileSizeKB.toLocaleString()} KB，超过了安全渲染限制。</p>
        <p style="color: var(--text-muted);">建议使用命令行工具（如 git diff）查看此文件的差异。</p>
        <button class="btn-secondary" style="margin-top: 1rem;" data-action="force-render-large-diff">
          强制渲染（可能导致浏览器卡顿）
        </button>
      </div>`;
    const button = targetElement.querySelector<HTMLButtonElement>('[data-action="force-render-large-diff"]');
    button?.addEventListener("click", () => onForceRender?.());
    return;
  }

  if (lineCount > MAX_DIFF_LINES_WARNING || charCount > MAX_DIFF_CHARS_WARNING) {
    const warningDiv = document.createElement("div");
    warningDiv.className = "diff-size-warning";
    warningDiv.style.cssText =
      "padding: 0.75rem 1rem; background: #fef3c7; border-bottom: 1px solid #fcd34d; color: #92400e; font-size: 0.85rem;";
    warningDiv.innerHTML = `⚠️ 此差异较大（${lineCount.toLocaleString()} 行，${fileSizeKB} KB），渲染可能较慢...`;
    targetElement.innerHTML = "";
    targetElement.appendChild(warningDiv);

    const diffContainer = document.createElement("div");
    targetElement.appendChild(diffContainer);

    window.setTimeout(() => {
      const configuration = {
        drawFileList: false,
        fileListToggle: false,
        fileContentToggle: false,
        matching: "none",
        outputFormat,
        synchronisedScroll: false,
        highlight: false,
        renderNothingWhenEmpty: false,
      };
      try {
        const diff2htmlUi = new window.Diff2HtmlUI!(diffContainer, diffText, configuration);
        diff2htmlUi.draw();
      } catch (e) {
        console.error("Render large diff failed:", e);
        diffContainer.innerHTML = '<div style="padding:1rem;color:red;">渲染失败，文件可能过大</div>';
      }
    }, 100);
    return;
  }

  const configuration = {
    drawFileList: false,
    fileListToggle: false,
    fileContentToggle: false,
    matching: "lines",
    outputFormat,
    synchronisedScroll: true,
    highlight: true,
    renderNothingWhenEmpty: false,
  };

  const diff2htmlUi = new window.Diff2HtmlUI!(targetElement, diffText, configuration);
  diff2htmlUi.draw();
  diff2htmlUi.highlightCode();
}

/**
 * 旧版 diff.js 的普通文本兜底渲染（Diff2Html 不可用时）。
 */
export function renderPlainDiff(targetElement: HTMLElement, filePath: string, diffText: string): void {
  const formattedDiff = diffText ? diffText.replace(/\r\n/g, "\n") : "No content";
  targetElement.innerHTML = `
    <div style="padding:1rem;">
      <h3>${escapeHtml(filePath)}</h3>
      <pre style="background:var(--bg-secondary);padding:1rem;overflow:auto;"><code>${escapeHtml(formattedDiff)}</code></pre>
    </div>`;
}
