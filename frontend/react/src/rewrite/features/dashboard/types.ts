/**
 * GET /api/v2/dashboard/summary 的响应结构。
 * 字段来源：kernel/application/facade.py::get_dashboard_summary。
 */

export type DashboardProvider = {
  id?: string;
  name?: string;
  label?: string;
  available?: boolean;
  error?: string | null;
};

export type DashboardScannerInfo = {
  name?: string;
  language?: string;
  available?: boolean;
  enabled?: boolean;
};

export type DashboardScannerLanguage = {
  language: string;
  available_count: number;
  enabled_count?: number;
  total_count: number;
  detected?: boolean;
  scanners?: DashboardScannerInfo[];
};

export type DashboardScanners = {
  detected_languages?: string[];
  languages?: DashboardScannerLanguage[];
};

export type DashboardSessionStats = {
  total_sessions?: number;
  total_messages?: number;
  by_status?: Record<string, number>;
  by_project?: Record<string, number>;
};

export type DashboardDiffStatus = {
  error?: string | null;
  has_working_changes?: boolean;
  has_staged_changes?: boolean;
  detected_mode?: string | null;
};

export type DashboardSummary = {
  health?: { status?: string } | null;
  project_root?: string | null;
  project?: { info?: { detected_languages?: unknown } } | null;
  diff_status?: DashboardDiffStatus | null;
  session_stats?: DashboardSessionStats | null;
  providers?: DashboardProvider[] | null;
  scanners?: DashboardScanners | null;
};

/** legacy/dashboard.js:184-190 的英文语言名 → 内部语言标识映射。 */
const DETECTED_LANGUAGE_MAP: Record<string, string> = {
  Python: "python",
  TypeScript: "typescript",
  JavaScript: "javascript",
  Java: "java",
  Go: "go",
  Ruby: "ruby",
  C: "c",
  "C++": "cpp",
  "C#": "csharp",
  Rust: "rust",
  Kotlin: "kotlin",
  Swift: "swift",
  PHP: "php",
  Scala: "scala",
};

/**
 * 旧版 /api/scanners/status.languages 的固定顺序。
 * 新版 dashboard/summary 返回字母序，这里恢复旧版展示顺序（UI 只按该顺序过滤，不排序）。
 */
export const LEGACY_SCANNER_LANGUAGE_ORDER = [
  "python",
  "javascript",
  "typescript",
  "java",
  "go",
  "ruby",
  "c",
  "cpp",
  "csharp",
  "rust",
  "kotlin",
  "swift",
  "php",
  "scala",
];

const LEGACY_SCANNER_LANGUAGE_INDEX = new Map(
  LEGACY_SCANNER_LANGUAGE_ORDER.map((language, index) => [language, index])
);

/** 按旧版 API 顺序稳定排序；未知语言排在末尾并保持 API 原始相对顺序。 */
export function sortScannerLanguagesByLegacyOrder<T extends { language: string }>(languages: T[]): T[] {
  return languages
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const left = LEGACY_SCANNER_LANGUAGE_INDEX.get(a.item.language) ?? Number.MAX_SAFE_INTEGER;
      const right = LEGACY_SCANNER_LANGUAGE_INDEX.get(b.item.language) ?? Number.MAX_SAFE_INTEGER;
      return left === right ? a.index - b.index : left - right;
    })
    .map((entry) => entry.item);
}

/**
 * 与 legacy/dashboard.js:183-190 完全一致：
 * 读取 project.info.detected_languages，并按旧映射表转换；未识别的丢弃。
 */
export function getDetectedLanguages(summary: DashboardSummary | null): string[] {
  const names = summary?.project?.info?.detected_languages;
  if (!Array.isArray(names)) return [];
  return names.map((name) => DETECTED_LANGUAGE_MAP[String(name)]).filter((value): value is string => Boolean(value));
}
