import { escapeHtml } from "./html";

declare global {
  interface Window {
    marked?: {
      parse(src: string, options?: Record<string, unknown>): string;
    };
  }
}

/**
 * 使用与旧版完全相同的本地 marked.min.js 进行渲染。
 * 不引入 react-markdown，避免 HTML 结构差异。
 */
export function renderMarkdown(text: string): string {
  if (!text) return "";
  const marked = typeof window !== "undefined" ? window.marked : undefined;
  if (marked && typeof marked.parse === "function") {
    return marked.parse(text);
  }
  return escapeHtml(text);
}

/**
 * 旧版流式渲染的防抖间隔（review.js: STREAM_MD_DEBOUNCE_MS）。
 */
export const STREAM_MD_DEBOUNCE_MS = 500;

/**
 * 按旧版规则判断内容是否处于 Markdown 渲染状态。
 * 旧版会在流式暂停 500ms 后把 <pre> 替换为 marked.parse 的结果。
 */
export function createStreamingMarkdownRenderer(target: HTMLElement): {
  push(text: string): void;
  flush(): void;
  dispose(): void;
} {
  let timer: number | null = null;
  let rendered = false;
  let latestText = "";

  const renderPlain = (text: string) => {
    target.innerHTML = '<pre class="workflow-stream-text" style="white-space:pre-wrap;word-break:break-word;font-family:inherit;margin:0;"></pre>';
    const pre = target.querySelector(".workflow-stream-text");
    if (pre) pre.textContent = text;
  };

  return {
    push(text: string) {
      latestText = text;
      if (!rendered) renderPlain(text);
      if (timer != null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        timer = null;
        if (!target.isConnected) return;
        rendered = true;
        target.innerHTML = renderMarkdown(latestText);
      }, STREAM_MD_DEBOUNCE_MS);
    },
    flush() {
      if (timer != null) {
        window.clearTimeout(timer);
        timer = null;
      }
      rendered = true;
      target.innerHTML = renderMarkdown(latestText);
    },
    dispose() {
      if (timer != null) {
        window.clearTimeout(timer);
        timer = null;
      }
    },
  };
}
