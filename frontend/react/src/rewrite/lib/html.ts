/**
 * 与 legacy/ui_v1/static/modules/utils.js 保持一致的格式化与转义工具。
 * 这里逐行对齐旧实现，避免出现“看起来差不多”的差异。
 */

export function escapeHtml(text: unknown): string {
  if (text == null) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function getIcon(name: string): string {
  return `<svg class="icon icon-${name}"><use href="#icon-${name}"></use></svg>`;
}

export function truncateTextGlobal(text: unknown, maxLen = 100): string {
  if (!text) return "";
  const str = String(text);
  return str.length > maxLen ? str.slice(0, maxLen) + "..." : str;
}

export function formatFileSizeGlobal(bytes?: number | null): string {
  if (bytes == null) return "?";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

export function formatTimestamp(timestamp?: string | null): string {
  if (!timestamp) return "-";
  try {
    const d = new Date(timestamp);
    const now = new Date();

    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterdayStart = new Date(todayStart.getTime() - 24 * 60 * 60 * 1000);
    const targetDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());

    const timeStr = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

    if (targetDate.getTime() === todayStart.getTime()) {
      return "今天 " + timeStr;
    } else if (targetDate.getTime() === yesterdayStart.getTime()) {
      return "昨天 " + timeStr;
    } else {
      const diffDays = Math.floor((todayStart.getTime() - targetDate.getTime()) / (1000 * 60 * 60 * 24));
      if (diffDays < 7) {
        return `${diffDays}天前 ${timeStr}`;
      }
      const month = d.getMonth() + 1;
      const day = d.getDate();
      return `${month}月${day}日 ${timeStr}`;
    }
  } catch {
    return String(timestamp);
  }
}

const LANGUAGE_LABELS: Record<string, string> = {
  py: "Python",
  python: "Python",
  js: "JavaScript",
  javascript: "JavaScript",
  ts: "TypeScript",
  typescript: "TypeScript",
  jsx: "React JSX",
  tsx: "React TSX",
  java: "Java",
  go: "Go",
  rust: "Rust",
  cpp: "C++",
  c: "C",
  cs: "C#",
  rb: "Ruby",
  php: "PHP",
  swift: "Swift",
  kt: "Kotlin",
  scala: "Scala",
  html: "HTML",
  css: "CSS",
  scss: "SCSS",
  vue: "Vue",
  svelte: "Svelte",
  sql: "SQL",
  sh: "Shell",
  bash: "Bash",
  yaml: "YAML",
  yml: "YAML",
  json: "JSON",
  md: "Markdown",
  markdown: "Markdown",
};

export function formatLanguageLabel(lang?: string | null): string {
  if (!lang) return "";
  const lower = lang.toLowerCase();
  return LANGUAGE_LABELS[lower] || lang;
}

export function setButtonLoading(btn: HTMLButtonElement | null, isLoading: boolean, loadingText?: string | null): void {
  if (!btn) return;
  if (isLoading) {
    btn.dataset.originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = loadingText || '<div class="spinner-small"></div>';
  } else {
    btn.disabled = false;
    if (btn.dataset.originalText) {
      btn.innerHTML = btn.dataset.originalText;
      delete btn.dataset.originalText;
    }
  }
}
