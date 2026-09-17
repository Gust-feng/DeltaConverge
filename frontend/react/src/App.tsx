import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  applyRule,
  askReviewQuestion,
  cleanupRuleGrowth,
  createReview,
  deleteSession,
  getCommitHistory,
  getCommitRangeDiff,
  getConfig,
  getDashboardSummary,
  getDiff,
  getDiffFiles,
  getDiffStatus,
  getDiffSummary,
  getEvents,
  getFileDiff,
  getMessages,
  getProviders,
  getRuleGrowthSuggestions,
  getRuleGrowthSummary,
  getScan,
  getSession,
  getSystemEnv,
  getTools,
  listDirectories,
  listSessions,
  promoteHint,
  updateConfig,
} from "./api";
import { useAppStore } from "./store";
import type {
  CommitInfo,
  DashboardSummary,
  DiffFile,
  MessageRecord,
  ReferenceHint,
  ScanResult,
  SessionSummary,
  WorkflowEvent,
} from "./types";

type IconName =
  | "maximize"
  | "send"
  | "folder"
  | "clock"
  | "trending-up"
  | "settings"
  | "x"
  | "bot"
  | "report"
  | "return"
  | "copy"
  | "info"
  | "chevron-down"
  | "rule"
  | "lightbulb"
  | "scan"
  | "plan"
  | "review"
  | "init"
  | "spark"
  | "edit";

type StageBucket = "init" | "analysis" | "planning" | "reviewing" | "report";
type ResolvedDiffMode = "auto" | "working" | "staged" | "pr" | "commit";
type DropdownOption = { value: string; label: string };
type DropdownGroup = { id: string; label: string; options: DropdownOption[] };

const STAGE_STEPS: Array<{ key: StageBucket; title: string; desc: string; icon: IconName }> = [
  { key: "init", title: "初始化", desc: "准备审查环境...", icon: "init" },
  { key: "analysis", title: "项目分析", desc: "扫描变更与意图...", icon: "scan" },
  { key: "planning", title: "策略规划", desc: "制定审查计划...", icon: "plan" },
  { key: "reviewing", title: "深入审查", desc: "执行审查与调用工具...", icon: "review" },
  { key: "report", title: "整理报告", desc: "生成结论与摘要...", icon: "report" },
];

const PAGE_LABELS = {
  dashboard: "仪表盘",
  review: "代码审查",
  diff: "代码变更",
  "rule-growth": "规则优化",
  config: "设置",
} as const;

function isResolvedDiffMode(value: string): value is ResolvedDiffMode {
  return value === "auto" || value === "working" || value === "staged" || value === "pr" || value === "commit";
}

function resolveDiffMode(requestedMode: string, diffStatus: Record<string, unknown> | null, diffSummaryMode?: string | null): ResolvedDiffMode {
  if (requestedMode !== "auto" && isResolvedDiffMode(requestedMode)) {
    return requestedMode;
  }
  const detectedMode = typeof diffStatus?.detected_mode === "string" ? diffStatus.detected_mode.toLowerCase() : "";
  if (isResolvedDiffMode(detectedMode)) {
    return detectedMode;
  }
  const summaryMode = typeof diffSummaryMode === "string" ? diffSummaryMode.toLowerCase() : "";
  if (isResolvedDiffMode(summaryMode)) {
    return summaryMode;
  }
  return "auto";
}

function getModeMeta(mode: ResolvedDiffMode, loading = false): { className: string; label: string } {
  if (loading) {
    return { className: "mode-loading", label: "自动检测" };
  }
  switch (mode) {
    case "working":
      return { className: "mode-working", label: "工作区模式" };
    case "staged":
      return { className: "mode-staged", label: "暂存区模式" };
    case "pr":
      return { className: "mode-pr", label: "PR 模式" };
    case "commit":
      return { className: "mode-commit", label: "历史提交模式" };
    default:
      return { className: "mode-default", label: "自动检测" };
  }
}

function getDiffStatusHint(mode: ResolvedDiffMode, fileCount: number): string {
  if (fileCount <= 0) {
    return "暂无可分析变更";
  }
  switch (mode) {
    case "staged":
      return `暂存区 ${fileCount} 个文件，建议审查后提交`;
    case "working":
      return `工作区 ${fileCount} 个文件，包含未暂存修改`;
    case "pr":
      return `PR 模式 ${fileCount} 个文件，正在等待审查`;
    case "commit":
      return `历史提交范围 ${fileCount} 个文件`;
    default:
      return `自动检测到 ${fileCount} 个文件`;
  }
}

function getDiffStatusDisplay(diffStatus: Record<string, unknown> | null): string {
  if (!diffStatus) {
    return "未知";
  }
  const explicit = diffStatus.status;
  if (typeof explicit === "string" && explicit.trim()) {
    return explicit;
  }
  const detectedMode = typeof diffStatus.detected_mode === "string" ? diffStatus.detected_mode.toLowerCase() : "";
  const hasStaged = Boolean(diffStatus.has_staged_changes);
  const hasWorking = Boolean(diffStatus.has_working_changes);
  if (hasStaged || detectedMode === "staged") {
    return "Has Changes (staged)";
  }
  if (hasWorking || detectedMode === "working") {
    return "Has Changes (working)";
  }
  if (detectedMode === "commit") {
    return "Commit Range";
  }
  if (detectedMode === "pr") {
    return "PR Mode";
  }
  return "No Changes";
}

function normalizeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function formatDateTime(value?: string | null): string {
  if (!value) {
    return "未知";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatCount(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function truncatePath(value?: string | null): string {
  if (!value) {
    return "未选择";
  }
  return value.length > 64 ? `...${value.slice(-61)}` : value;
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value);
  }
}

function splitDisplayPath(path: string): { fileName: string; dirPath: string } {
  const normalized = path.replace(/\\/g, "/");
  const lastSlash = normalized.lastIndexOf("/");
  if (lastSlash < 0) {
    return { fileName: normalized, dirPath: "根目录" };
  }
  const fileName = normalized.slice(lastSlash + 1) || normalized;
  const dirPath = normalized.slice(0, lastSlash) || "根目录";
  return { fileName, dirPath };
}

function getDiffChangeBadge(changeType: string, linesAdded: number, linesRemoved: number): { className: string; label: string } {
  const normalized = changeType.toLowerCase();
  if (normalized === "added" || normalized === "add") {
    return { className: "add", label: "A" };
  }
  if (normalized === "deleted" || normalized === "delete" || normalized === "removed" || normalized === "remove") {
    return { className: "delete", label: "D" };
  }
  if (normalized === "renamed" || normalized === "rename") {
    return { className: "rename", label: "R" };
  }
  if (linesAdded > 0 && linesRemoved === 0) {
    return { className: "add", label: "A" };
  }
  if (linesRemoved > 0 && linesAdded === 0) {
    return { className: "delete", label: "D" };
  }
  return { className: "modify", label: "M" };
}

function buildDiffPreviewLines(diffText: string): Array<{ lineNumber: string; text: string; kind: "meta" | "add" | "delete" | "context" }> {
  return diffText
    .replace(/\r\n/g, "\n")
    .split("\n")
    .slice(0, 320)
    .map((line, index) => {
      const kind =
        line.startsWith("diff --git") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")
          ? "meta"
          : line.startsWith("+")
            ? "add"
            : line.startsWith("-")
              ? "delete"
              : "context";
      return {
        lineNumber: kind === "meta" ? "" : String(index + 1),
        text: line || " ",
        kind,
      };
    });
}

function getRuleGrowthTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    rule_high_llm_expand: "LLM 要求更多上下文",
    rule_high_llm_skip: "LLM 建议跳过",
    rule_low_llm_consistent: "可提取新规则",
    context_level_mismatch: "上下文级别不匹配",
  };
  return labels[type] || type;
}

function getSortedCountEntries(value: Record<string, number> | undefined, labelTransform?: (key: string) => string): Array<{ key: string; label: string; count: number }> {
  return Object.entries(value ?? {})
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([key, count]) => ({
      key,
      label: labelTransform ? labelTransform(key) : key,
      count,
    }));
}

function getParentPath(path: string): string | null {
  if (!path) {
    return null;
  }
  const normalized = path.replace(/[\\/]+$/, "");
  if (/^[A-Za-z]:$/.test(normalized)) {
    return null;
  }
  const parts = normalized.split(/[/\\]/);
  if (parts.length <= 1) {
    return null;
  }
  parts.pop();
  const parent = parts.join("\\");
  return parent || null;
}

function reportMessageFrom(messages: MessageRecord[]): MessageRecord | null {
  return (
    [...messages]
      .reverse()
      .find((message) => message.role === "assistant" && message.metadata?.kind === "final_report") ?? null
  );
}

function getStageBucket(event: WorkflowEvent): StageBucket {
  const stage = String(event.stage ?? "").toLowerCase();
  const type = event.type.toLowerCase();
  if (type === "review.completed" || type === "review.failed" || stage === "report" || stage === "diff_snapshot") {
    return "report";
  }
  if (stage.includes("plan")) {
    return "planning";
  }
  if (stage.includes("intent") || stage.includes("analysis") || type.startsWith("scan.") || stage === "scan") {
    return "analysis";
  }
  if (type === "review.started" || stage === "init" || stage === "setup" || stage === "orchestrator") {
    return "init";
  }
  return "reviewing";
}

function summarizeEvent(event: WorkflowEvent): string {
  const payload = asRecord(event.payload);
  const message = payload?.message;
  if (typeof message === "string" && message.trim()) {
    return message;
  }
  const preview = payload?.content_preview;
  if (typeof preview === "string" && preview.trim()) {
    return preview;
  }
  const legacyType = payload?.legacy_type;
  if (typeof legacyType === "string" && legacyType.trim()) {
    return legacyType;
  }
  if (event.type === "review.completed") {
    return "审查完成，报告已生成。";
  }
  if (event.type === "review.failed") {
    return typeof payload?.error === "string" ? payload.error : "审查失败。";
  }
  return event.type;
}

function getDiffSnapshotFiles(snapshot: Record<string, unknown>): string[] {
  const direct = asStringArray(snapshot.diff_files);
  if (direct.length > 0) {
    return direct;
  }
  const units = Array.isArray(snapshot.diff_units) ? snapshot.diff_units : [];
  const unitFiles = units
    .map((item) => {
      const record = asRecord(item);
      if (!record) return null;
      return typeof record.file_path === "string"
        ? record.file_path
        : typeof record.path === "string"
          ? record.path
          : typeof record.file === "string"
            ? record.file
            : null;
    })
    .filter((item): item is string => Boolean(item));
  return [...new Set(unitFiles)];
}

function filterSnapshotByFile(snapshot: Record<string, unknown>, filePath: string | null): unknown {
  if (!filePath) {
    return snapshot;
  }
  const units = Array.isArray(snapshot.diff_units) ? snapshot.diff_units : [];
  const filtered = units.filter((item) => {
    const record = asRecord(item);
    if (!record) return false;
    return record.file_path === filePath || record.path === filePath || record.file === filePath;
  });
  if (filtered.length > 0) {
    return { diff_files: [filePath], diff_units: filtered };
  }
  return snapshot;
}

function getSessionItemClass(session: SessionSummary, currentSessionId: string | null): string {
  const parts = ["session-item"];
  if (session.id === currentSessionId) parts.push("active");
  if (session.status === "running" || session.status === "active") parts.push("running");
  return parts.join(" ");
}

function getSessionBadgeClass(session: SessionSummary): string {
  if (session.status === "running" || session.status === "active") {
    return "session-badge running";
  }
  return "session-badge active";
}

function getProviderClass(configured: boolean): string {
  return configured ? "status-badge configured" : "status-badge unconfigured";
}

function getProviderState(provider: { available?: boolean; configured?: boolean; error?: string | null }): {
  dotClass: "success" | "error";
  text: string;
} {
  if (provider.available || provider.configured) {
    return { dotClass: "success", text: "已配置" };
  }
  return { dotClass: "error", text: provider.error ? "未就绪" : "未配置" };
}

function detectProjectPath(summary: DashboardSummary | undefined, fallback: string): string {
  return summary?.project_root || fallback;
}

function countScanIssues(scan: ScanResult | null, severity?: string): number {
  if (!scan) return 0;
  if (severity && severity !== "all") {
    const list = scan.issues_by_severity[severity];
    return Array.isArray(list) ? list.length : 0;
  }
  return Object.values(scan.issues_by_severity).reduce((total, value) => {
    return total + (Array.isArray(value) ? value.length : 0);
  }, 0);
}

function Icon({ name, className }: { name: IconName; className?: string }) {
  const props = {
    className: className ? `icon ${className}` : "icon",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (name) {
    case "maximize":
      return <svg {...props}><path d="M15 4h5v5" /><path d="M9 20H4v-5" /><path d="M20 4l-7 7" /><path d="M4 20l7-7" /></svg>;
    case "send":
      return <svg {...props}><path d="M22 2L11 13" /><path d="M22 2L15 22l-4-9-9-4z" /></svg>;
    case "folder":
      return <svg {...props}><path d="M3 7h5l2 2h11v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 7a2 2 0 0 1 2-2h4l2 2" /></svg>;
    case "clock":
      return <svg {...props}><circle cx="12" cy="12" r="8" /><path d="M12 8v5l3 2" /></svg>;
    case "trending-up":
      return <svg {...props}><path d="M3 17l6-6 4 4 7-8" /><path d="M14 7h6v6" /></svg>;
    case "settings":
      return <svg {...props}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a2 2 0 0 1 0 2.8l-.1.1a2 2 0 0 1-2.8 0l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 0 1-2 2h-.2a2 2 0 0 1-2-2v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a2 2 0 0 1-2.8 0l-.1-.1a2 2 0 0 1 0-2.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 0 1-2-2v-.2a2 2 0 0 1 2-2h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a2 2 0 0 1 0-2.8l.1-.1a2 2 0 0 1 2.8 0l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a2 2 0 0 1 2-2h.2a2 2 0 0 1 2 2v.2a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a2 2 0 0 1 2.8 0l.1.1a2 2 0 0 1 0 2.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H20a2 2 0 0 1 2 2v.2a2 2 0 0 1-2 2h-.2a1 1 0 0 0-.9.6Z" /></svg>;
    case "x":
      return <svg {...props}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>;
    case "bot":
      return <svg {...props}><rect x="5" y="8" width="14" height="10" rx="3" /><path d="M12 4v4" /><circle cx="9.5" cy="13" r="1" fill="currentColor" stroke="none" /><circle cx="14.5" cy="13" r="1" fill="currentColor" stroke="none" /></svg>;
    case "report":
      return <svg {...props}><path d="M8 3h6l5 5v13H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" /><path d="M14 3v6h6" /><path d="M10 14h6" /><path d="M10 18h4" /></svg>;
    case "return":
      return <svg {...props}><path d="M9 6 4 11l5 5" /><path d="M20 18v-3a4 4 0 0 0-4-4H4" /></svg>;
    case "copy":
      return <svg {...props}><rect x="9" y="9" width="10" height="10" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>;
    case "info":
      return <svg {...props}><circle cx="12" cy="12" r="9" /><path d="M12 10v6" /><circle cx="12" cy="7" r="1" fill="currentColor" stroke="none" /></svg>;
    case "chevron-down":
      return <svg {...props}><path d="m6 9 6 6 6-6" /></svg>;
    case "rule":
      return <svg {...props}><path d="M8 6h12" /><path d="M8 12h12" /><path d="M8 18h12" /><path d="M4 6h.01" /><path d="M4 12h.01" /><path d="M4 18h.01" /></svg>;
    case "lightbulb":
      return <svg {...props}><path d="M9 18h6" /><path d="M10 22h4" /><path d="M12 2a6 6 0 0 0-3 11.2c.7.4 1.2 1 1.4 1.8h3.2c.2-.8.7-1.4 1.4-1.8A6 6 0 0 0 12 2Z" /></svg>;
    case "scan":
      return <svg {...props}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 8h8" /><path d="M8 12h8" /><path d="M8 16h5" /></svg>;
    case "plan":
      return <svg {...props}><path d="M4 6h16" /><path d="M4 12h10" /><path d="M4 18h7" /></svg>;
    case "review":
      return <svg {...props}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>;
    case "init":
      return <svg {...props}><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 3" /></svg>;
    case "spark":
      return <svg {...props}><path d="m12 3 1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6Z" /><path d="m5 18 .8 2 .8-2 2-.8-2-.8-.8-2-.8 2-2 .8 2 .8Z" /></svg>;
    case "edit":
      return <svg {...props}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4Z" /></svg>;
    default:
      return null;
  }
}

function CustomDropdown({
  id,
  value,
  onChange,
  options = [],
  groups = [],
  triggerLabel,
  className,
  triggerClassName,
  menuClassName,
  width,
  menuMinWidth,
  alignLeft = false,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  options?: DropdownOption[];
  groups?: DropdownGroup[];
  triggerLabel?: string;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
  width?: string | number;
  menuMinWidth?: string | number;
  alignLeft?: boolean;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const selectedOption = useMemo(() => {
    const flat = options.find((item) => item.value === value);
    if (flat) {
      return flat;
    }
    for (const group of groups) {
      const matched = group.options.find((item) => item.value === value);
      if (matched) {
        return matched;
      }
    }
    return null;
  }, [groups, options, value]);

  useEffect(() => {
    if (groups.length === 0) {
      return;
    }
    setExpandedGroups((current) => {
      const next = { ...current };
      groups.forEach((group, index) => {
        if (!(group.id in next)) {
          next[group.id] = group.options.some((item) => item.value === value) || index === 0;
        }
      });
      return next;
    });
  }, [groups, value]);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current) {
        return;
      }
      if (!rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  return (
    <div id={id} ref={rootRef} className={`custom-dropdown ${open ? "open" : ""} ${className ?? ""}`.trim()} style={width ? { width } : undefined}>
      <button type="button" className={`dropdown-trigger ${triggerClassName ?? ""}`.trim()} onClick={() => setOpen((current) => !current)}>
        <span>{triggerLabel ?? selectedOption?.label ?? value}</span>
        <Icon name="chevron-down" className={groups.length > 0 ? "chevron-dropdown" : "chevron"} />
      </button>
      <div
        className={`dropdown-menu ${alignLeft ? "align-left" : ""} ${menuClassName ?? ""}`.trim()}
        style={menuMinWidth ? { minWidth: menuMinWidth } : undefined}
      >
        {options.map((option) => (
          <div
            key={option.value}
            className={`dropdown-item ${option.value === value ? "selected" : ""}`.trim()}
            onClick={() => {
              onChange(option.value);
              setOpen(false);
            }}
          >
            <span className="dropdown-item-label">{option.label}</span>
          </div>
        ))}
        {groups.map((group) => (
          <div key={group.id} className={`dropdown-group-container ${expandedGroups[group.id] ? "expanded" : ""}`.trim()}>
            <div className="dropdown-group-header" onClick={() => setExpandedGroups((current) => ({ ...current, [group.id]: !current[group.id] }))}>
              <span>{group.label}</span>
              <Icon name="chevron-down" className="chevron-dropdown" />
            </div>
            <div className="dropdown-group-models">
              {group.options.map((option) => (
                <div
                  key={option.value}
                  className={`dropdown-item ${option.value === value ? "selected" : ""}`.trim()}
                  onClick={() => {
                    onChange(option.value);
                    setOpen(false);
                  }}
                >
                  <span className="dropdown-item-label">{option.label}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function App() {
  const queryClient = useQueryClient();
  const {
    activePage,
    historyDrawerOpen,
    reviewLayoutState,
    selectedSessionId,
    sessionFilter,
    statusText,
    projectRoot,
    model,
    selectedTools,
    autoApprove,
    enableStaticScan,
    diffMode,
    selectedDiffFile,
    selectedCommitFrom,
    selectedCommitTo,
    reportView,
    question,
    qaAnswer,
    folderPickerOpen,
    setActivePage,
    setHistoryDrawerOpen,
    toggleHistoryDrawer,
    setReviewLayoutState,
    setSelectedSessionId,
    setSessionFilter,
    setStatusText,
    setProjectRoot,
      setModel,
    toggleTool,
    setAutoApprove,
    setEnableStaticScan,
    setDiffMode,
    setSelectedDiffFile,
    setCommitRange,
    setReportView,
    setQuestion,
    setQaAnswer,
    resetQA,
    setFolderPickerOpen,
  } = useAppStore();

  const [configText, setConfigText] = useState("{}");
  const [busyAction, setBusyAction] = useState<
    "review" | "qa" | "config" | "rule-apply" | "rule-promote" | "rule-cleanup" | null
  >(null);
  const [streamingRunId, setStreamingRunId] = useState<string | null>(null);
  const [reportFullscreen, setReportFullscreen] = useState(false);
  const [monitorCollapsed, setMonitorCollapsed] = useState(true);
  const [scannerCollapsed, setScannerCollapsed] = useState(false);
  const [activeScannerSeverity, setActiveScannerSeverity] = useState<"all" | "error" | "warning" | "info">("all");
  const [folderBrowsePath, setFolderBrowsePath] = useState<string | null>(null);
  const [collapsedWorkflowStages, setCollapsedWorkflowStages] = useState<Record<string, boolean>>({});
  const [toolsCollapsed, setToolsCollapsed] = useState(true);
  const [showDashboardIntentDetails, setShowDashboardIntentDetails] = useState(false);
  const [dashboardScannerView, setDashboardScannerView] = useState<"summary" | "detail">("summary");
  const [scannerHelpOpen, setScannerHelpOpen] = useState(false);
  const [hintsHelpOpen, setHintsHelpOpen] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const systemEnvQuery = useQuery({
    queryKey: ["system-env"],
    queryFn: getSystemEnv,
  });
  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: listSessions,
  });
  const configQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });
  const toolsQuery = useQuery({
    queryKey: ["tools"],
    queryFn: getTools,
  });
  const providersQuery = useQuery({
    queryKey: ["providers"],
    queryFn: getProviders,
  });
  const dashboardQuery = useQuery({
    queryKey: ["dashboard-summary", projectRoot],
    queryFn: () => getDashboardSummary(projectRoot || null),
  });
  const sessionDetailQuery = useQuery({
    queryKey: ["session", selectedSessionId],
    queryFn: () => getSession(selectedSessionId!),
    enabled: Boolean(selectedSessionId),
  });

  const currentRunId = streamingRunId ?? sessionDetailQuery.data?.latest_run?.id ?? sessionDetailQuery.data?.summary.latest_run_id ?? null;

  const messagesQuery = useQuery({
    queryKey: ["messages", selectedSessionId],
    queryFn: () => getMessages(selectedSessionId!),
    enabled: Boolean(selectedSessionId),
  });
  const eventsQuery = useQuery({
    queryKey: ["events", selectedSessionId, currentRunId],
    queryFn: () => getEvents(selectedSessionId!, currentRunId),
    enabled: Boolean(selectedSessionId) && Boolean(currentRunId),
  });
  const reviewDiffQuery = useQuery({
    queryKey: ["review-diff", currentRunId],
    queryFn: () => getDiff(currentRunId!),
    enabled: Boolean(currentRunId),
  });
  const scanQuery = useQuery({
    queryKey: ["scan", currentRunId],
    queryFn: () => getScan(currentRunId!),
    enabled: Boolean(currentRunId),
  });
  const diffStatusQuery = useQuery({
    queryKey: ["diff-status", projectRoot],
    queryFn: () => getDiffStatus(projectRoot || null),
    enabled: Boolean(projectRoot),
  });
  const diffSummaryQuery = useQuery({
    queryKey: ["diff-summary", projectRoot, diffMode],
    queryFn: () => getDiffSummary(projectRoot || null, diffMode),
    enabled: Boolean(projectRoot) && diffMode !== "commit",
  });
  const diffFilesQuery = useQuery({
    queryKey: ["diff-files", projectRoot, diffMode],
    queryFn: () => getDiffFiles(projectRoot || null, diffMode),
    enabled: Boolean(projectRoot) && diffMode !== "commit",
  });
  const commitHistoryQuery = useQuery({
    queryKey: ["commit-history", projectRoot],
    queryFn: () => getCommitHistory(projectRoot, 40),
    enabled: Boolean(projectRoot) && diffMode === "commit",
  });
  const dashboardCommitHistoryQuery = useQuery({
    queryKey: ["dashboard-commit-history", projectRoot],
    queryFn: () => getCommitHistory(projectRoot, 20),
    enabled: Boolean(projectRoot),
  });
  const commitRangeQuery = useQuery({
    queryKey: ["commit-range", projectRoot, selectedCommitFrom, selectedCommitTo],
    queryFn: () => getCommitRangeDiff(projectRoot, selectedCommitFrom!, selectedCommitTo || null),
    enabled: Boolean(projectRoot) && diffMode === "commit" && Boolean(selectedCommitFrom),
  });
  const fileDiffQuery = useQuery({
    queryKey: ["file-diff", projectRoot, diffMode, selectedDiffFile, selectedCommitFrom, selectedCommitTo],
    queryFn: () =>
      getFileDiff({
        filePath: selectedDiffFile!,
        projectRoot: projectRoot || null,
        mode: diffMode,
        commitFrom: selectedCommitFrom,
        commitTo: selectedCommitTo,
      }),
    enabled: Boolean(projectRoot) && Boolean(selectedDiffFile) && (diffMode !== "commit" || Boolean(selectedCommitFrom)),
  });
  const ruleSummaryQuery = useQuery({
    queryKey: ["rule-growth-summary"],
    queryFn: getRuleGrowthSummary,
  });
  const ruleSuggestionsQuery = useQuery({
    queryKey: ["rule-growth-suggestions"],
    queryFn: getRuleGrowthSuggestions,
  });
  const folderListQuery = useQuery({
    queryKey: ["folder-list", folderBrowsePath],
    queryFn: () => listDirectories(folderBrowsePath),
    enabled: folderPickerOpen,
  });

  const sessions = sessionsQuery.data ?? [];
  const messages = messagesQuery.data ?? [];
  const events = eventsQuery.data ?? [];
  const sessionDetail = sessionDetailQuery.data ?? null;
  const dashboard = dashboardQuery.data;
  const reviewDiffSnapshot = useMemo(() => {
    const data = reviewDiffQuery.data;
    return data && typeof data === "object" ? data : {};
  }, [reviewDiffQuery.data]);
  const scanResult = useMemo(() => {
    const value = scanQuery.data;
    return value && !("status" in value) ? (value as ScanResult) : null;
  }, [scanQuery.data]);
  const tools = toolsQuery.data?.items ?? [];
  const providers = providersQuery.data?.items ?? [];
  const reportMessage = useMemo(() => reportMessageFrom(messages), [messages]);
  const diffModeOptions = useMemo<DropdownOption[]>(
    () => [
      { value: "auto", label: "自动检测" },
      { value: "working", label: "工作区模式" },
      { value: "staged", label: "暂存区模式" },
      { value: "pr", label: "PR 模式" },
      { value: "commit", label: "历史提交模式" },
    ],
    []
  );
  const dashboardDiffModeOptions = useMemo<DropdownOption[]>(
    () => [
      { value: "auto", label: "自动检测" },
      { value: "working", label: "工作区" },
      { value: "staged", label: "暂存区" },
      { value: "pr", label: "PR模式" },
      { value: "commit", label: "历史提交" },
    ],
    []
  );
  const providerModelGroups = useMemo<DropdownGroup[]>(
    () =>
      [
        { id: "system", label: "系统", options: [{ value: "auto", label: "auto" }] },
        ...providers
          .filter((provider) => provider.models.length > 0)
          .map((provider) => ({
            id: provider.id,
            label: provider.label,
            options: provider.models.map((item) => ({ value: item, label: item })),
          })),
      ].filter((group) => group.options.length > 0),
    [providers]
  );
  const filteredSessions = useMemo(() => {
    const needle = sessionFilter.trim().toLowerCase();
    if (!needle) return sessions;
    return sessions.filter((session) =>
      [session.name, session.project_root, session.status, ...(session.tags ?? [])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle)
    );
  }, [sessionFilter, sessions]);
  const dashboardProjectPath = detectProjectPath(dashboard, projectRoot);
  const diffStatus = useMemo(() => asRecord(diffStatusQuery.data), [diffStatusQuery.data]);
  const diffFiles = useMemo(() => {
    if (diffMode === "commit") {
      return (commitRangeQuery.data?.files ?? []).map((item) => ({
        path: item.path,
        language: item.path.split(".").pop() || "text",
        change_type: "modified",
        lines_added: item.added_lines,
        lines_removed: item.removed_lines,
        tags: item.is_binary ? ["binary"] : [],
      })) satisfies DiffFile[];
    }
    return diffFilesQuery.data?.files ?? [];
  }, [commitRangeQuery.data?.files, diffFilesQuery.data?.files, diffMode]);
  const liveFileDiff = fileDiffQuery.data ?? null;
  const snapshotFiles = useMemo(() => getDiffSnapshotFiles(reviewDiffSnapshot), [reviewDiffSnapshot]);
  const detailSnapshotPayload = useMemo(() => filterSnapshotByFile(reviewDiffSnapshot, selectedDiffFile), [reviewDiffSnapshot, selectedDiffFile]);
  const commitHistory = commitHistoryQuery.data?.commits ?? [];
  const dashboardCommitHistory = dashboardCommitHistoryQuery.data?.commits ?? [];
  const sessionStats = dashboard?.session_stats;
  const scannerSummary = dashboard?.scanners;
  const effectiveDiffMode = useMemo(
    () => resolveDiffMode(diffMode, diffStatus, diffSummaryQuery.data?.mode ?? null),
    [diffMode, diffStatus, diffSummaryQuery.data?.mode]
  );
  const modeMeta = useMemo(
    () => getModeMeta(effectiveDiffMode, diffMode === "auto" && diffStatusQuery.isLoading),
    [diffMode, diffStatusQuery.isLoading, effectiveDiffMode]
  );
  const diffFileCount = diffMode === "commit" ? commitRangeQuery.data?.file_count ?? 0 : diffSummaryQuery.data?.file_count ?? diffFiles.length;
  const diffStatusHint = useMemo(() => getDiffStatusHint(effectiveDiffMode, diffFileCount), [diffFileCount, effectiveDiffMode]);
  const displayedScannerLanguages = useMemo(() => {
    const source = scannerSummary?.languages ?? [];
    const ranked = [...source].sort((left, right) => {
      if (left.detected !== right.detected) {
        return Number(right.detected) - Number(left.detected);
      }
      if (left.enabled_count !== right.enabled_count) {
        return right.enabled_count - left.enabled_count;
      }
      if (left.available_count !== right.available_count) {
        return right.available_count - left.available_count;
      }
      return left.language.localeCompare(right.language);
    });
    const detected = ranked.filter((language) => language.detected);
    const visible =
      detected.length > 0 ? detected : ranked.filter((language) => language.detected || language.enabled_count > 0 || language.available_count > 0);
    return (visible.length > 0 ? visible : ranked).slice(0, 4);
  }, [scannerSummary?.languages]);
  const dashboardScannerDetails = useMemo(
    () =>
      displayedScannerLanguages.flatMap((language) =>
        language.scanners.map((scanner) => ({
          key: `${language.language}-${scanner.name}`,
          language: language.language,
          name: scanner.name,
          available: scanner.available,
          enabled: scanner.enabled,
        }))
      ),
    [displayedScannerLanguages]
  );
  const scannerAvailabilitySummary = useMemo(() => {
    return displayedScannerLanguages.reduce(
      (acc, language) => {
        acc.available += language.enabled_count;
        acc.total += language.total_count;
        return acc;
      },
      { available: 0, total: 0 }
    );
  }, [displayedScannerLanguages]);
  const sessionProjectCount = Object.keys(sessionStats?.by_project ?? {}).length;
  const reviewInputCollapsed = reviewLayoutState !== "initial" || toolsCollapsed;
  const dashboardDiffStatus = useMemo(() => getDiffStatusDisplay(asRecord(dashboard?.diff_status) ?? diffStatus), [dashboard?.diff_status, diffStatus]);
  const visibleScannerLanguageTotal = useMemo(() => {
    const source = scannerSummary?.languages ?? [];
    return source.filter((language) => language.detected || language.enabled_count > 0 || language.available_count > 0).length;
  }, [scannerSummary?.languages]);
  const hasIntentDetails = Boolean(dashboard?.project);
  const applicableRules = ruleSuggestionsQuery.data?.applicable_rules ?? [];
  const referenceHints = ruleSuggestionsQuery.data?.reference_hints ?? [];
  const activeRuleSummary = ruleSummaryQuery.data ?? null;
  const selectedDiffFileMeta = useMemo(() => diffFiles.find((file) => file.path === selectedDiffFile) ?? null, [diffFiles, selectedDiffFile]);
  const selectedDiffText = selectedDiffFile
    ? diffMode === "commit"
      ? commitRangeQuery.data?.error || liveFileDiff?.error || liveFileDiff?.diff_text || commitRangeQuery.data?.diff_text || "暂无 Diff 内容"
      : liveFileDiff?.error || liveFileDiff?.diff_text || "暂无 Diff 内容"
    : "";
  const diffPreviewLines = useMemo(() => buildDiffPreviewLines(selectedDiffText), [selectedDiffText]);

  useEffect(() => {
    if (!projectRoot && systemEnvQuery.data?.default_project_root) {
      setProjectRoot(systemEnvQuery.data.default_project_root);
    }
  }, [projectRoot, setProjectRoot, systemEnvQuery.data]);

  useEffect(() => {
    if (model !== "auto" || providers.length === 0) {
      return;
    }
    const configuredModels = providers.filter((provider) => provider.configured).flatMap((provider) => provider.models);
    const allModels = providers.flatMap((provider) => provider.models);
    const preferred =
      configuredModels.find((item) => item === "deepseek-reasoner") ??
      configuredModels[0] ??
      allModels.find((item) => item === "deepseek-reasoner") ??
      allModels[0];
    if (preferred) {
      setModel(preferred);
    }
  }, [model, providers, setModel]);

  useEffect(() => {
    if (configQuery.data) {
      setConfigText(JSON.stringify(configQuery.data, null, 2));
    }
  }, [configQuery.data]);

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (selectedSessionId && filteredSessions.length > 0 && !filteredSessions.some((session) => session.id === selectedSessionId)) {
      setSelectedSessionId(null);
    }
  }, [filteredSessions, selectedSessionId, setSelectedSessionId]);

  useEffect(() => {
    if (selectedSessionId && sessionDetail?.summary.project_root) {
      setProjectRoot(sessionDetail.summary.project_root);
    }
  }, [selectedSessionId, sessionDetail?.summary.project_root, setProjectRoot]);

  useEffect(() => {
    if (!selectedSessionId) {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      setReviewLayoutState("initial");
      setStreamingRunId(null);
      setStatusText("Idle");
      return;
    }
  }, [selectedSessionId, setReviewLayoutState, setStatusText]);

  useEffect(() => {
    if (folderPickerOpen) {
      setFolderBrowsePath(projectRoot || systemEnvQuery.data?.default_project_root || systemEnvQuery.data?.cwd || null);
    }
  }, [folderPickerOpen, projectRoot, systemEnvQuery.data]);

  useEffect(() => {
    if (reviewLayoutState !== "initial") {
      setToolsCollapsed(true);
    }
  }, [reviewLayoutState]);

  useEffect(() => {
    const candidateFiles =
      activePage === "diff" ? diffFiles.map((file) => file.path) : reportView === "detail" ? snapshotFiles : [];
    if (!selectedDiffFile && candidateFiles.length > 0) {
      setSelectedDiffFile(candidateFiles[0]);
    }
  }, [activePage, diffFiles, reportView, selectedDiffFile, setSelectedDiffFile, snapshotFiles]);

  async function hydrateSessionArtifacts(sessionId: string, runId: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["sessions"] }),
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] }),
      queryClient.invalidateQueries({ queryKey: ["messages", sessionId] }),
      queryClient.invalidateQueries({ queryKey: ["events", sessionId, runId] }),
      queryClient.invalidateQueries({ queryKey: ["review-diff", runId] }),
      queryClient.invalidateQueries({ queryKey: ["scan", runId] }),
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] }),
    ]);
  }

  const attachReviewStream = useCallback(
    (sessionId: string, runId: string, options?: { restore?: boolean }) => {
      if (eventSourceRef.current && streamingRunId === runId) {
        return;
      }

      eventSourceRef.current?.close();
      const source = new EventSource(`/api/v2/reviews/${encodeURIComponent(runId)}/stream`);
      eventSourceRef.current = source;
      setStreamingRunId(runId);
      setReviewLayoutState("running");
      setStatusText(options?.restore ? "正在恢复审查流..." : "正在接收审查输出...");

      source.onmessage = (message) => {
        const event = JSON.parse(message.data) as WorkflowEvent;
        queryClient.setQueryData<WorkflowEvent[]>(["events", sessionId, runId], (current) => {
          const items = current ?? [];
          return [...items.filter((item) => item.seq !== event.seq), event].sort((a, b) => a.seq - b.seq);
        });
        setStatusText(`${event.type}${event.stage ? ` / ${event.stage}` : ""}`);
        if (event.type === "scan.finished") {
          void queryClient.invalidateQueries({ queryKey: ["scan", runId] });
        }
        if (event.type === "review.completed" || event.type === "review.failed") {
          source.close();
          if (eventSourceRef.current === source) {
            eventSourceRef.current = null;
          }
          setStreamingRunId(null);
          setReviewLayoutState(event.type === "review.completed" ? "completed" : "replay");
          void hydrateSessionArtifacts(sessionId, runId);
        }
      };

      source.onerror = () => {
        source.close();
        if (eventSourceRef.current === source) {
          eventSourceRef.current = null;
        }
        setStreamingRunId(null);
        void hydrateSessionArtifacts(sessionId, runId);
        setStatusText("审查流已关闭。");
      };
    },
    [hydrateSessionArtifacts, queryClient, setReviewLayoutState, setStatusText, streamingRunId]
  );

  useEffect(() => {
    const latestRun = sessionDetail?.latest_run;
    if (!selectedSessionId || !latestRun) {
      return;
    }

    if (latestRun.status === "running") {
      attachReviewStream(selectedSessionId, latestRun.id, { restore: true });
      return;
    }

    if (latestRun.status === "completed") {
      setReviewLayoutState("completed");
      setStatusText("审查已完成。");
      return;
    }

    if (latestRun.status === "failed") {
      setReviewLayoutState("replay");
      setStatusText(sessionDetail?.summary.last_error || latestRun.error_message || "审查失败。");
      return;
    }

    setReviewLayoutState(latestRun.id ? "replay" : "initial");
  }, [
    attachReviewStream,
    selectedSessionId,
    sessionDetail?.latest_run,
    sessionDetail?.summary.last_error,
    setReviewLayoutState,
    setStatusText,
  ]);

  async function handleStartReview() {
    if (!projectRoot.trim()) {
      setStatusText("请先选择项目目录。");
      return;
    }

    eventSourceRef.current?.close();
    setBusyAction("review");
    setStatusText("正在创建审查任务...");
    setActivePage("review");
    setReviewLayoutState("running");
    setToolsCollapsed(true);
    setMonitorCollapsed(false);
    setScannerCollapsed(false);
    setReportView("report");
    resetQA();

    try {
      const result = await createReview({
        project_root: projectRoot,
        model,
        enable_static_scan: enableStaticScan,
        auto_approve: autoApprove,
        tools: selectedTools,
        diff_mode: diffMode,
        commit_from: selectedCommitFrom,
        commit_to: selectedCommitTo,
      });

      const sessionId = "summary" in result.session ? result.session.summary.id : result.session.id;
      const runId = result.run.id;
      setSelectedSessionId(sessionId);
      await hydrateSessionArtifacts(sessionId, runId);
      attachReviewStream(sessionId, runId);
    } catch (error) {
      setStreamingRunId(null);
      setReviewLayoutState("initial");
      setStatusText(normalizeError(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleAskQuestion() {
    if (!currentRunId || !question.trim()) {
      return;
    }
    setBusyAction("qa");
    setStatusText("正在生成问答结果...");
    try {
      const result = await askReviewQuestion(currentRunId, question, model);
      setQaAnswer(result.answer);
      setQuestion("");
      if (selectedSessionId) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["messages", selectedSessionId] }),
          queryClient.invalidateQueries({ queryKey: ["session", selectedSessionId] }),
        ]);
      }
      setStatusText("问答结果已更新。");
    } catch (error) {
      setStatusText(normalizeError(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSaveConfig() {
    setBusyAction("config");
    try {
      const parsed = JSON.parse(configText) as Record<string, unknown>;
      const updated = await updateConfig(parsed);
      setConfigText(JSON.stringify(updated, null, 2));
      queryClient.setQueryData(["config"], updated);
      setStatusText("配置已保存。");
    } catch (error) {
      setStatusText(normalizeError(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleDeleteSession(sessionId: string) {
    if (!window.confirm(`删除会话 ${sessionId} 后无法恢复，是否继续？`)) {
      return;
    }
    try {
      await deleteSession(sessionId);
      if (selectedSessionId === sessionId) {
        eventSourceRef.current?.close();
        eventSourceRef.current = null;
        setSelectedSessionId(null);
        setReviewLayoutState("initial");
        setStreamingRunId(null);
        resetQA();
      }
      await queryClient.invalidateQueries({ queryKey: ["sessions"] });
      setStatusText(`已删除会话 ${sessionId}`);
    } catch (error) {
      setStatusText(normalizeError(error));
    }
  }

  async function handleApplyRule(ruleId: string) {
    setBusyAction("rule-apply");
    try {
      const result = await applyRule(ruleId);
      if (!result.success) {
        throw new Error(result.error || "规则应用失败");
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rule-growth-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["rule-growth-suggestions"] }),
      ]);
      setStatusText(`规则 ${ruleId} 已应用。`);
    } catch (error) {
      setStatusText(normalizeError(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handlePromoteHint(hint: ReferenceHint) {
    setBusyAction("rule-promote");
    try {
      const result = await promoteHint({
        language: hint.language,
        tags: hint.tags,
        suggested_context_level: hint.suggested_context_level,
        sample_count: hint.sample_count,
        consistency: hint.consistency,
        conflict_type: hint.conflict_type,
      });
      if (!result.success) {
        throw new Error(result.error || "提示提升失败");
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rule-growth-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["rule-growth-suggestions"] }),
      ]);
      setStatusText(`已将 ${hint.language} 提示提升为规则。`);
    } catch (error) {
      setStatusText(normalizeError(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCleanupRuleGrowth() {
    setBusyAction("rule-cleanup");
    try {
      const result = await cleanupRuleGrowth(30);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["rule-growth-summary"] }),
        queryClient.invalidateQueries({ queryKey: ["rule-growth-suggestions"] }),
      ]);
      setStatusText(`已清理 ${result.deleted_count} 条旧冲突记录。`);
    } catch (error) {
      setStatusText(normalizeError(error));
    } finally {
      setBusyAction(null);
    }
  }

  function toggleWorkflowStage(stage: string) {
    setCollapsedWorkflowStages((current) => ({ ...current, [stage]: !current[stage] }));
  }

  function handleSessionSelect(session: SessionSummary) {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    setSelectedSessionId(session.id);
    setActivePage("review");
    setStreamingRunId(null);
    setReviewLayoutState(session.latest_run_id ? "replay" : "initial");
    setToolsCollapsed(true);
    if (session.project_root) {
      setProjectRoot(session.project_root);
    }
    setStatusText(`已切换到会话 ${session.name}`);
    setReportView("report");
    resetQA();
  }

  async function copyReport() {
    const text = reportMessage?.content || prettyJson(reviewDiffSnapshot);
    await navigator.clipboard.writeText(text);
    setStatusText("内容已复制到剪贴板。");
  }

  const containerLayoutState =
    activePage === "review"
      ? reviewLayoutState === "running"
        ? "reviewing"
        : reviewLayoutState === "completed" || reviewLayoutState === "replay"
          ? "completed"
          : "initial"
      : "initial";

  const stageStatusMap = useMemo(() => {
    const map = new Map<StageBucket, "pending" | "active" | "completed">();
    let reached = false;
    const latestEvent = events[events.length - 1];
    const activeBucket = latestEvent ? getStageBucket(latestEvent) : reviewLayoutState === "completed" ? "report" : null;
    for (const step of STAGE_STEPS) {
      if (activeBucket === step.key) {
        map.set(step.key, reviewLayoutState === "completed" || reviewLayoutState === "replay" ? "completed" : "active");
        reached = true;
        continue;
      }
      if (!reached && activeBucket) {
        map.set(step.key, "completed");
      } else {
        map.set(step.key, "pending");
      }
    }
    if (!activeBucket && (reviewLayoutState === "completed" || reviewLayoutState === "replay")) {
      STAGE_STEPS.forEach((step) => map.set(step.key, "completed"));
    }
    return map;
  }, [events, reviewLayoutState]);

  const workflowGroups = useMemo(() => {
    const buckets = new Map<StageBucket, WorkflowEvent[]>();
    for (const event of events) {
      if (event.type.startsWith("scan.")) continue;
      const bucket = getStageBucket(event);
      const list = buckets.get(bucket) ?? [];
      list.push(event);
      buckets.set(bucket, list);
    }
    return STAGE_STEPS.filter((step) => (buckets.get(step.key) ?? []).length > 0).map((step) => ({
      ...step,
      events: buckets.get(step.key) ?? [],
    }));
  }, [events]);

  const monitorEvents = useMemo(() => [...events].reverse().slice(0, 24), [events]);
  const reportPanelClass = ["report-panel", reportFullscreen ? "fullscreen" : ""].filter(Boolean).join(" ");
  const monitorPanelClass = [
    "monitor-panel",
    monitorCollapsed ? "collapsed" : "",
    sessionDetail?.latest_run?.status === "failed" ? "error" : sessionDetail?.latest_run?.status === "completed" ? "ok" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const scannerIssues =
    activeScannerSeverity === "all"
      ? Object.entries(scanResult?.issues_by_severity ?? {}).flatMap(([severity, items]) =>
          (items as Array<Record<string, unknown>>).map((item) => ({ severity, item }))
        )
      : ((scanResult?.issues_by_severity[activeScannerSeverity] as Array<Record<string, unknown>> | undefined) ?? []).map((item) => ({
          severity: activeScannerSeverity,
          item,
        }));

  return (
    <div className="app-container" data-layout-state={containerLayoutState}>
      <nav className="sidebar-nav">
        <div className="nav-top">
          <button type="button" className={`nav-btn ${activePage === "dashboard" ? "active" : ""}`} title="仪表盘" onClick={() => setActivePage("dashboard")}>
            <Icon name="maximize" />
          </button>
          <button type="button" className={`nav-btn ${activePage === "review" ? "active" : ""}`} title="代码审查" onClick={() => setActivePage("review")}>
            <Icon name="send" />
          </button>
          <button type="button" className={`nav-btn ${activePage === "diff" ? "active" : ""}`} title="代码变更" onClick={() => setActivePage("diff")}>
            <Icon name="folder" />
          </button>
          <button type="button" className="nav-btn" title="历史记录" onClick={toggleHistoryDrawer}>
            <Icon name="clock" />
          </button>
        </div>
        <div className="nav-bottom">
          <button type="button" className={`nav-btn ${activePage === "rule-growth" ? "active" : ""}`} title="规则优化" onClick={() => setActivePage("rule-growth")}>
            <Icon name="trending-up" />
          </button>
          <button type="button" className={`nav-btn ${activePage === "config" ? "active" : ""}`} title="设置" onClick={() => setActivePage("config")}>
            <Icon name="settings" />
          </button>
        </div>
      </nav>

      <aside id="historyDrawer" className={`history-drawer ${historyDrawerOpen ? "open" : ""}`}>
        <div className="drawer-header">
          <h3>历史记录</h3>
          <div className="header-actions">
            <button type="button" className="icon-btn-small" onClick={() => setHistoryDrawerOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
        </div>
        <div className="history-toolbar">
          <input type="search" className="dc-search-input" placeholder="搜索会话 / 路径 / 状态" value={sessionFilter} onChange={(event) => setSessionFilter(event.target.value)} />
          <div className="history-meta">
            <span className="badge">{formatCount(sessions.length)}</span>
            <button type="button" className="btn-text" onClick={() => void queryClient.invalidateQueries({ queryKey: ["sessions"] })}>
              刷新
            </button>
          </div>
        </div>
        <div id="sessionList" className="session-list">
          {sessionsQuery.isLoading ? <div className="empty-state">正在加载历史会话...</div> : null}
          {!sessionsQuery.isLoading && filteredSessions.length === 0 ? <div className="empty-state">暂无历史会话</div> : null}
          {filteredSessions.map((session) => (
            <div key={session.id} className={getSessionItemClass(session, selectedSessionId)}>
              <button type="button" className="dc-session-button" onClick={() => handleSessionSelect(session)}>
                <div className="session-main">
                  <div className="session-topline">
                    <strong>{session.name || session.id}</strong>
                    <span className={getSessionBadgeClass(session)}>{session.status}</span>
                  </div>
                  <div className="session-path">{truncatePath(session.project_root)}</div>
                  <div className="session-footline">
                    <span>{formatDateTime(session.updated_at)}</span>
                    {session.tags?.slice(0, 3).map((tag) => (
                      <span key={tag} className="badge">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </button>
              <div className="session-actions">
                <button type="button" className="icon-btn-small" title="删除会话" onClick={() => void handleDeleteSession(session.id)}>
                  <Icon name="x" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <div className="main-content">
        <div id="page-dashboard" className="page-view" style={{ display: activePage === "dashboard" ? "block" : "none" }}>
          <div className="page-header dashboard-page-header">
            <div id="dashboard-header-container" className="dashboard-title-wrap">
              <h2>仪表盘</h2>
              <span id="dashboard-health-label" className="health-indicator dashboard-health-indicator">
                {dashboard?.health.status?.toUpperCase() || "UNKNOWN"}
              </span>
            </div>
          </div>

          <div className="dashboard-grid">
            <div className="card">
              <div className="card-header">
                <h3>当前项目</h3>
                <button type="button" className="btn-text" onClick={() => setFolderPickerOpen(true)}>
                  切换
                </button>
              </div>
              <div className="card-body dc-card-column">
                <div className="stat-row">
                  <span className="label">路径:</span>
                  <span className="value" id="dash-project-path">
                    {dashboardProjectPath || "未选择"}
                  </span>
                </div>
                <div className="stat-row">
                  <span className="label">Diff 状态:</span>
                  <span className="value" id="dash-diff-status">
                    {dashboardDiffStatus}
                  </span>
                </div>
                <div id="git-history-section" className="dc-history-section">
                  <div className="dc-history-header">
                    <div className="dc-inline-meta">
                      <Icon name="clock" />
                      <span>提交历史</span>
                      {dashboard?.project?.git && asRecord(dashboard.project.git)?.branch ? (
                        <span id="git-current-branch" className="branch-badge">
                          {String(asRecord(dashboard.project.git)?.branch)}
                        </span>
                      ) : null}
                    </div>
                    <button type="button" className="btn-text" onClick={() => void queryClient.invalidateQueries({ queryKey: ["dashboard-commit-history", projectRoot] })}>
                      刷新
                    </button>
                  </div>
                  <div id="git-commit-list" className="git-commit-list">
                    {!projectRoot ? <div className="empty-state compact">请选择项目目录后查看。</div> : null}
                    {projectRoot && dashboardCommitHistoryQuery.isLoading ? <div className="empty-state compact">正在加载提交历史...</div> : null}
                    {projectRoot && !dashboardCommitHistoryQuery.isLoading && dashboardCommitHistory.length === 0 ? <div className="empty-state compact">暂无可显示提交记录</div> : null}
                    {dashboardCommitHistory.slice(0, 6).map((commit: CommitInfo) => (
                      <div key={commit.hash} className="git-commit-item">
                        <div className="git-commit-dot" />
                          <div className="git-commit-content">
                            <div className="git-commit-meta">
                              <span className="commit-hash">{commit.short_hash}</span>
                              <span className="commit-time">{commit.time_ago}</span>
                            </div>
                            <div className="git-commit-message">{commit.message}</div>
                            <div className="git-commit-author">by {commit.author}</div>
                          </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <h3>会话统计</h3>
                <span id="session-total-badge" className="badge">
                  {formatCount(sessionStats?.total_sessions ?? 0)}
                </span>
              </div>
              <div id="session-stats-content" className="card-body dc-stat-list">
                <div className="stat-row">
                  <span className="label">消息总数:</span>
                  <span className="value">{formatCount(sessionStats?.total_messages ?? 0)}</span>
                </div>
                <div className="stat-row">
                  <span className="label">项目数:</span>
                  <span className="value">{formatCount(sessionProjectCount)}</span>
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <h3>LLM 提供商</h3>
                <div className="header-actions">
                  <span id="provider-available-badge" className="badge dashboard-count-badge">
                    {providers.filter((item) => item.configured).length}/{providers.length}
                  </span>
                  <button type="button" className="btn-secondary" onClick={() => setActivePage("config")}>
                    配置服务
                  </button>
                </div>
              </div>
              <div id="provider-status-content" className="card-body dc-provider-list">
                {providers.map((provider) => {
                  const providerState = getProviderState(provider);
                  return (
                    <div key={provider.id} className="stat-row provider-status-row">
                      <span className="label">{provider.label}:</span>
                      <span className="provider-status-inline" title={provider.error ?? providerState.text}>
                        <span className={`status-dot ${providerState.dotClass}`} />
                        <span className="provider-status-text">{providerState.text}</span>
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <h3 style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  代码扫描器
                  <button
                    type="button"
                    id="scannerHelpBtn"
                    className={`hints-help-btn ${scannerHelpOpen ? "active" : ""}`}
                    title="查看扫描器说明"
                    aria-expanded={scannerHelpOpen}
                    onClick={() => setScannerHelpOpen((current) => !current)}
                  >
                    <span className="help-text">?</span>
                  </button>
                </h3>
                <div className="header-actions">
                  <span id="scanner-summary-badge" className="badge dashboard-count-badge">
                    {scannerAvailabilitySummary.available}/{scannerAvailabilitySummary.total || visibleScannerLanguageTotal || displayedScannerLanguages.length || 0}
                  </span>
                  <button type="button" className="btn-text" id="scanner-toggle-btn" onClick={() => setDashboardScannerView((current) => (current === "summary" ? "detail" : "summary"))}>
                    {dashboardScannerView === "summary" ? "扫描器种类" : "扫描器详情"}
                  </button>
                </div>
              </div>
              {scannerHelpOpen ? (
                <div className="dc-inline-help-popover" role="note">
                  <strong>扫描器说明</strong>
                  <p>这里展示当前项目可识别语言的扫描器可用性。界面只负责开启或关闭静态扫描，不负责配置规则提示词。</p>
                  <p>条形进度表示当前语言下已启用扫描器数量，详情视图会列出每个扫描器的就绪状态。</p>
                </div>
              ) : null}
              <div id="scanner-status-content" className="card-body dc-scanner-list">
                {displayedScannerLanguages.length === 0 ? <div className="empty-state compact">暂无可用扫描器</div> : null}
                {dashboardScannerView === "summary"
                  ? displayedScannerLanguages.map((language) => (
                      <div key={language.language} className="scanner-language-row">
                        <div className="scanner-language-main">
                          <div className="scanner-language-name">{language.language}</div>
                          <div className="scanner-language-meta">{language.detected ? "已识别" : "未识别"} / 已启用 {language.enabled_count}</div>
                        </div>
                        <div className="scanner-language-progress">
                          <div className="scanner-progress-track">
                            <div
                              className={`scanner-progress-fill ${
                                language.enabled_count === language.total_count ? "success" : language.enabled_count > 0 ? "warning" : "error"
                              }`}
                              style={{ width: `${language.total_count > 0 ? (language.enabled_count / language.total_count) * 100 : 0}%` }}
                            />
                          </div>
                          <strong>
                            {language.enabled_count}/{language.total_count}
                          </strong>
                        </div>
                      </div>
                    ))
                  : dashboardScannerDetails.map((scanner) => (
                      <div key={scanner.key} className="dashboard-scanner-detail-row">
                        <div className="dashboard-scanner-detail-main">
                          <strong>{scanner.name}</strong>
                            <span className="scanner-language-chip">{scanner.language}</span>
                          </div>
                          <div className="dashboard-scanner-detail-status">
                            <span className={`status-dot ${scanner.available ? "success" : "error"}`} />
                          <span>{scanner.available ? "已就绪" : scanner.enabled ? "未安装" : "已禁用"}</span>
                        </div>
                      </div>
                    ))}
              </div>
            </div>

            <div className="card dc-wide-card">
              <div className="card-header">
                <h3>项目意图分析</h3>
                <div className="header-actions dashboard-intent-actions">
                  <CustomDropdown
                    id="intentModelDropdown"
                    value={model}
                    onChange={setModel}
                    groups={providerModelGroups}
                    triggerLabel={model}
                    width={200}
                    menuMinWidth={320}
                  />
                  <button
                    type="button"
                    className="btn-primary btn-small"
                    id="intent-analyze-btn"
                    onClick={() => {
                      setShowDashboardIntentDetails(true);
                      void queryClient.invalidateQueries({ queryKey: ["dashboard-summary", projectRoot] });
                    }}
                  >
                    <Icon name="bot" />
                    <span>分析</span>
                  </button>
                  <button
                    type="button"
                    className="btn-secondary btn-small dashboard-intent-edit-btn"
                    id="intent-edit-btn"
                    title={showDashboardIntentDetails ? "返回概览" : "查看分析详情"}
                    onClick={() => setShowDashboardIntentDetails((current) => !current)}
                    disabled={!hasIntentDetails}
                  >
                    <Icon name="edit" />
                  </button>
                </div>
              </div>
              <div id="intent-panel" className="card-body dc-intent-panel">
                {!hasIntentDetails || !showDashboardIntentDetails ? (
                  <div className="empty-state dc-dashboard-intent-empty">
                    <div className="empty-icon">
                      <Icon name="bot" className="icon-large" />
                    </div>
                    <p>选择需要审查的代码文件</p>
                  </div>
                ) : null}
                {dashboard?.project && showDashboardIntentDetails ? (
                  <div className="dc-intent-grid">
                    <div className="dc-intent-block">
                      <h4>项目信息</h4>
                      <pre>{prettyJson(dashboard.project.info)}</pre>
                    </div>
                    <div className="dc-intent-block">
                      <h4>README 摘要</h4>
                      <pre>{prettyJson(dashboard.project.readme)}</pre>
                    </div>
                    <div className="dc-intent-block">
                      <h4>依赖</h4>
                      <pre>{prettyJson(dashboard.project.dependencies)}</pre>
                    </div>
                    <div className="dc-intent-block">
                      <h4>Git 信息</h4>
                      <pre>{prettyJson(dashboard.project.git)}</pre>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>

        <div id="page-diff" className="page-view" style={{ display: activePage === "diff" ? "flex" : "none" }}>
          <div className="page-header">
            <h2>代码变更</h2>
            <div className="header-actions diff-header-actions">
              <div id="diff-status-hint" className={`status-hint-box ${effectiveDiffMode === "staged" ? "success" : effectiveDiffMode === "working" ? "warning" : "info"}`}>
                <Icon name="info" />
                <span id="diff-status-text">{diffStatusHint}</span>
              </div>
              <CustomDropdown
                id="diffModeDropdown"
                value={diffMode}
                onChange={(value) => setDiffMode(value as typeof diffMode)}
                options={dashboardDiffModeOptions}
                triggerLabel={diffMode === "auto" ? modeMeta.label : dashboardDiffModeOptions.find((item) => item.value === diffMode)?.label ?? modeMeta.label}
                width={160}
              />
              <button
                type="button"
                className="btn-primary"
                onClick={() => {
                  void Promise.all([
                    queryClient.invalidateQueries({ queryKey: ["diff-status", projectRoot] }),
                    queryClient.invalidateQueries({ queryKey: ["diff-summary", projectRoot, diffMode] }),
                    queryClient.invalidateQueries({ queryKey: ["diff-files", projectRoot, diffMode] }),
                    queryClient.invalidateQueries({ queryKey: ["file-diff"] }),
                  ]);
                }}
              >
                刷新分析
              </button>
            </div>
          </div>

          {diffMode === "commit" ? (
            <div id="commitSelectorPanel" className="dc-commit-range-panel">
              <div className="dc-commit-range-row">
                <label>
                  起始提交
                  <select className="dc-native-select" value={selectedCommitFrom ?? ""} onChange={(event) => setCommitRange(event.target.value || null, selectedCommitTo)}>
                    <option value="">请选择提交</option>
                    {commitHistory.map((commit) => (
                      <option key={commit.hash} value={commit.hash}>
                        {commit.short_hash} · {commit.message}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  结束提交
                  <select className="dc-native-select" value={selectedCommitTo} onChange={(event) => setCommitRange(selectedCommitFrom, event.target.value)}>
                    <option value="HEAD">HEAD</option>
                    {commitHistory.map((commit) => (
                      <option key={commit.hash} value={commit.hash}>
                        {commit.short_hash} · {commit.message}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          ) : null}

          <div className="diff-layout">
            <div className="diff-sidebar">
              <div id="diff-file-list" className="file-list">
                {diffFiles.length === 0 ? <div className="empty-state compact">暂无可分析文件</div> : null}
                {diffFiles.map((file) => {
                  const { fileName, dirPath } = splitDisplayPath(file.path);
                  const changeBadge = getDiffChangeBadge(file.change_type, file.lines_added, file.lines_removed);
                  return (
                    <button
                      key={file.path}
                      type="button"
                      className={`file-list-item ${selectedDiffFile === file.path ? "active" : ""} ${changeBadge.className}`}
                      onClick={() => setSelectedDiffFile(file.path)}
                    >
                      <div className="file-item-row">
                        <span className="file-icon-shell">
                          <Icon name="report" />
                        </span>
                        <div className="file-info">
                          <span className="file-name">{fileName}</span>
                          <span className="file-path">{dirPath}</span>
                        </div>
                        <span className={`file-status-badge ${changeBadge.className}`}>{changeBadge.label}</span>
                      </div>
                      <div className="file-item-meta">
                        <span className="lang-badge">{file.language}</span>
                        <span>
                          +{file.lines_added} / -{file.lines_removed}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="diff-main">
              <div id="diff-content-area" className="code-view">
                {!selectedDiffFile ? <div className="empty-state">请选择文件查看 Diff</div> : null}
                {selectedDiffFile ? (
                  <div className="dc-code-editor">
                    <div className="dc-code-editor-header">
                      <div className="dc-code-editor-tab">
                        <Icon name="report" />
                        <span>{selectedDiffFileMeta ? splitDisplayPath(selectedDiffFileMeta.path).fileName : "未选择文件"}</span>
                      </div>
                    </div>
                    <div className="dc-code-editor-body">
                      {diffPreviewLines.map((line, index) => (
                        <div key={`${line.lineNumber}-${index}`} className={`dc-code-line ${line.kind}`}>
                          <span className="dc-code-line-number">{line.lineNumber}</span>
                          <span className="dc-code-line-text">{line.text}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </div>

        <div id="page-config" className="page-view" style={{ display: activePage === "config" ? "flex" : "none" }}>
          <div className="page-header">
            <h2>系统配置</h2>
            <button type="button" className="btn-primary" onClick={() => void handleSaveConfig()} disabled={busyAction === "config"}>
              保存更改
            </button>
          </div>
          <div className="config-container" id="config-form-container">
            <div className="config-card">
              <div className="config-card-header">
                <h3>服务提供商</h3>
                <span className="count-badge">
                  {providers.filter((item) => item.configured).length}/{providers.length}
                </span>
              </div>
              <div className="provider-list">
                {providers.map((provider) => (
                  <div key={provider.id} className="provider-item">
                    <div>
                      <div className="provider-name">{provider.label}</div>
                      <div className="provider-meta">
                        {provider.api_key_env} · {provider.model_count} 个模型
                      </div>
                    </div>
                    <span className={getProviderClass(provider.configured)}>{provider.configured ? "已配置" : "未配置"}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="config-card">
              <div className="config-card-header">
                <h3>工具能力</h3>
                <span className="count-badge">{tools.length}</span>
              </div>
              <div className="dc-tool-grid">
                {tools.map((tool) => (
                  <div key={tool.name} className="dc-tool-card">
                    <div className="dc-tool-card-head">
                      <strong>{tool.name}</strong>
                      <span className={`badge ${tool.is_default ? "success" : "info"}`}>{tool.is_default ? "默认" : "可选"}</span>
                    </div>
                    <p>{tool.description || "无描述"}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="config-card dc-config-editor-card">
              <div className="config-card-header">
                <h3>配置编辑器</h3>
                <span className="page-subtitle">按截图版布局保留配置区，但编辑能力先由原始 JSON 承接</span>
              </div>
              <textarea className="config-editor" value={configText} onChange={(event) => setConfigText(event.target.value)} />
            </div>
          </div>
        </div>

        <div id="page-rule-growth" className="page-view" style={{ display: activePage === "rule-growth" ? "flex" : "none" }}>
          <div className="page-header">
            <h2>规则优化</h2>
            <span className="page-subtitle">规则与 LLM 决策冲突分析</span>
            <div className="header-actions" style={{ marginLeft: "auto" }}>
              <button type="button" className="btn-secondary" onClick={() => void handleCleanupRuleGrowth()} disabled={busyAction === "rule-cleanup"}>
                清理旧记录
              </button>
            </div>
          </div>
          <div className="rule-growth-content">
            <div className="card">
              <div className="card-header">
                <h3>冲突统计</h3>
              </div>
                <div className="card-body rule-summary-body" id="rg-summary-content">
                {!activeRuleSummary || activeRuleSummary.total_conflicts === 0 ? (
                  <div className="empty-state" id="rg-summary-empty" style={{ flexDirection: "column", padding: "2rem" }}>
                    <p style={{ color: "var(--text-muted)" }}>暂无冲突记录</p>
                    <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                      系统会自动记录规则与 LLM 决策的差异
                    </p>
                  </div>
                ) : (
                  <div className="dc-rule-summary-grid">
                    <div className="dc-rule-stat">
                      <strong>{formatCount(activeRuleSummary.total_conflicts)}</strong>
                      <span>总冲突</span>
                    </div>
                    <div className="dc-rule-stat">
                      <strong>{formatCount(activeRuleSummary.session_conflicts)}</strong>
                      <span>当前会话</span>
                    </div>
                    <div className="dc-rule-block">
                      <h4>按类型</h4>
                      <pre className="dc-rule-json">{prettyJson(activeRuleSummary.by_type)}</pre>
                    </div>
                    <div className="dc-rule-block">
                      <h4>按语言</h4>
                      <pre className="dc-rule-json">{prettyJson(activeRuleSummary.by_language)}</pre>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <h3>
                  <Icon name="rule" className="dc-inline-icon" />
                  可应用规则
                </h3>
                <span id="rg-applicable-badge" className="badge success">
                  {applicableRules.length}
                </span>
              </div>
                <div className="card-body rule-applicable-body" id="rg-applicable-content">
                {applicableRules.length === 0 ? (
                  <div className="empty-state" id="rg-applicable-empty" style={{ flexDirection: "column", padding: "2rem" }}>
                    <p style={{ color: "var(--text-muted)" }}>暂无可应用规则</p>
                    <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                      需要满足：5+ 次出现、90%+ 一致性、2+ 标签、2+ 文件
                    </p>
                  </div>
                ) : (
                  <div id="rg-applicable-list" className="applicable-rules-list">
                    {applicableRules.map((rule) => (
                      <div key={rule.rule_id} className="applicable-rule-card">
                        <div className="rule-header">
                          <div className="rule-title-row">
                            <span className="hint-language-badge">{rule.language}</span>
                            <strong>{rule.rule_id}</strong>
                          </div>
                          <button type="button" className="btn-primary" onClick={() => void handleApplyRule(rule.rule_id)} disabled={busyAction === "rule-apply"}>
                            应用
                          </button>
                        </div>
                        <div className="rule-body">
                          <div className="rule-stat-row">
                            <span>上下文级别</span>
                            <strong>{rule.suggested_context_level}</strong>
                          </div>
                          <div className="rule-stat-row">
                            <span>样本 / 一致性 / 文件</span>
                            <strong>
                              {rule.sample_count} / {Math.round(rule.consistency * 100)}% / {rule.unique_files}
                            </strong>
                          </div>
                        </div>
                        <div className="rule-tags">
                          {rule.required_tags.map((tag) => (
                            <span key={tag} className="tag-badge">
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="card">
              <div className="card-header">
                <h3 style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  <Icon name="lightbulb" />
                  参考提示
                  <button
                    type="button"
                    id="hintsHelpBtn"
                    className={`hints-help-btn ${hintsHelpOpen ? "active" : ""}`}
                    title="查看参考提示说明"
                    aria-expanded={hintsHelpOpen}
                    onClick={() => setHintsHelpOpen((current) => !current)}
                  >
                    <span className="help-text">?</span>
                  </button>
                </h3>
                <span id="rg-hints-badge" className="badge">
                  {referenceHints.length}
                </span>
              </div>
              {hintsHelpOpen ? (
                <div className="dc-inline-help-popover" role="note">
                  <strong>参考提示说明</strong>
                  <p>这里展示还没满足“自动提升为规则”条件的模式，方便你人工判断是否值得沉淀为规则。</p>
                  <p>达到样本数、一致性和文件覆盖要求的模式会出现在“可应用规则”区域。</p>
                </div>
              ) : null}
                <div className="card-body rule-hints-body" id="rg-hints-content">
                {referenceHints.length === 0 ? (
                  <div className="empty-state" id="rg-hints-empty" style={{ flexDirection: "column", padding: "2rem" }}>
                    <p style={{ color: "var(--text-muted)" }}>暂无参考提示</p>
                    <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                      不满足自动应用条件的模式将显示在此
                    </p>
                  </div>
                ) : (
                  <div id="rg-hints-list" className="reference-hints-list">
                    {referenceHints.map((hint, index) => (
                      <div key={`${hint.language}-${hint.tags.join("-")}-${index}`} className="reference-hint-card">
                        <div className="hint-card-header">
                          <div className="hint-title-row">
                            <span className="hint-language-badge">{hint.language}</span>
                            <strong>{hint.reason}</strong>
                          </div>
                          <button type="button" className="btn-secondary" onClick={() => void handlePromoteHint(hint)} disabled={busyAction === "rule-promote"}>
                            提升为规则
                          </button>
                        </div>
                        <div className="hint-meta-row">
                          <span>{hint.suggested_context_level}</span>
                          <span>
                            {hint.sample_count} 样本 / {Math.round(hint.consistency * 100)}% 一致性
                          </span>
                        </div>
                        <div className="rule-tags">
                          {hint.tags.map((tag) => (
                            <span key={tag} className="tag-badge">
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        <div id="page-review" className="workbench" data-layout-state={containerLayoutState} style={{ display: activePage === "review" ? "flex" : "none" }}>
          <section id="reportPanel" className={reportPanelClass}>
            <div className="panel-header">
              <div className="panel-title-group">
                <Icon name="bot" />
                <span className="panel-title">DeltaConverge</span>
              </div>
              <div className="view-toggle-group">
                <button type="button" id="viewToggleReport" className={`view-toggle-btn ${reportView === "report" ? "active" : ""}`} onClick={() => setReportView("report")}>
                  <Icon name="report" />
                  <span>审查报告</span>
                </button>
                <button type="button" id="viewToggleDiff" className={`view-toggle-btn ${reportView === "detail" ? "active" : ""}`} onClick={() => setReportView("detail")}>
                  <Icon name="folder" />
                  <span>详细信息</span>
                </button>
              </div>
              <div className="actions">
                <button type="button" id="reportBackBtn" className="icon-btn" title="返回工作区" onClick={() => setReviewLayoutState("initial")}>
                  <Icon name="return" />
                </button>
                <button type="button" className="icon-btn" title="复制" onClick={() => void copyReport()}>
                  <Icon name="copy" />
                </button>
                <button type="button" className="icon-btn" title="全屏" onClick={() => setReportFullscreen((current) => !current)}>
                  <Icon name="maximize" />
                </button>
              </div>
            </div>
            <div id="reportContainer" className="report-content">
              {reportView === "report" ? (
                reportMessage?.content ? (
                  <div className="markdown-body dc-report-markdown">
                    <pre>{reportMessage.content}</pre>
                  </div>
                ) : (
                  <div className="empty-state">
                    <Icon name="report" className="empty-icon" />
                    <h3>报告尚未生成</h3>
                    <p>启动一次审查后，最终审查结论会出现在这里。</p>
                  </div>
                )
              ) : (
                <div id="diffViewContainer" className="dc-report-detail-layout">
                  <aside id="reportDiffFileList" className="file-list">
                    {snapshotFiles.length === 0 ? <div className="empty-state compact">暂无详细 Diff 快照</div> : null}
                    {snapshotFiles.map((file) => (
                      <button key={file} type="button" className={`file-list-item ${selectedDiffFile === file ? "active" : ""}`} onClick={() => setSelectedDiffFile(file)}>
                        {file}
                      </button>
                    ))}
                  </aside>
                  <div id="reportDiffContent" className="code-view">
                    <pre className="dc-code-block">{prettyJson(detailSnapshotPayload)}</pre>
                  </div>
                </div>
              )}

                {(reportMessage?.content || qaAnswer) && reportView === "report" ? (
                  <div className="dc-qa-panel">
                  <div className="dc-qa-header">
                    <strong>报告问答</strong>
                    <span className="page-subtitle">基于当前审查报告继续追问</span>
                  </div>
                  <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="继续问：这个问题是否会影响线上行为？" rows={3} />
                  <div className="dc-qa-actions">
                    <button type="button" className="btn-primary" onClick={() => void handleAskQuestion()} disabled={!currentRunId || busyAction === "qa"}>
                      继续追问
                    </button>
                  </div>
                  {qaAnswer ? <pre className="dc-code-block secondary">{qaAnswer}</pre> : null}
                </div>
              ) : null}
            </div>
          </section>

          <main className="chat-area">
            <header className="chat-header">
              <div className="header-left">
                <button id="pickFolderBtn" type="button" className="icon-btn-medium" title="选择项目文件夹" onClick={() => setFolderPickerOpen(true)}>
                  <Icon name="folder" />
                </button>
                <div className="path-display">
                  <span id="currentPathLabel" className="path-value">
                    {projectRoot || "请选择文件夹..."}
                  </span>
                </div>
                <CustomDropdown
                  id="headerModeDropdown"
                  value={diffMode}
                  onChange={(value) => setDiffMode(value as typeof diffMode)}
                  options={diffModeOptions}
                  triggerLabel={modeMeta.label}
                  className="dc-review-mode-dropdown"
                  triggerClassName={`mode-badge ${modeMeta.className}`}
                  width="auto"
                />
                <span id="historyModeLabel" className="history-mode-badge" style={{ display: reviewLayoutState === "replay" ? "inline-flex" : "none" }}>
                  只读
                </span>
              </div>

              <div className="header-controls">
                <CustomDropdown
                  id="modelDropdown"
                  value={model}
                  onChange={setModel}
                  groups={providerModelGroups}
                  triggerLabel={model}
                  className="dc-header-model-dropdown"
                  width={250}
                  menuMinWidth={320}
                />
              </div>
            </header>

            {reviewLayoutState === "initial" ? (
              <>
                <div id="heroAnimation" className="hero-animation">
                  <svg className="hero-icon" viewBox="0 0 100 100" aria-hidden="true">
                    <path className="hero-path p1" d="M50 15 L85 35 L85 75 L50 95 L15 75 L15 35 Z" fill="none" stroke="currentColor" strokeWidth="0.8" />
                    <path className="hero-path p2" d="M50 25 L75 40 L75 70 L50 85 L25 70 L25 40 Z" fill="none" stroke="currentColor" strokeWidth="1.2" />
                    <circle className="hero-path c1" cx="50" cy="55" r="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
                    <line className="hero-path l1" x1="50" y1="15" x2="50" y2="47" stroke="currentColor" strokeWidth="1" />
                    <line className="hero-path l2" x1="50" y1="63" x2="50" y2="95" stroke="currentColor" strokeWidth="1" />
                  </svg>
                  <div className="hero-project-name" data-text="DeltaConverge">
                    DeltaConverge
                  </div>
                </div>
                <div id="messageContainer" className="message-container">
                  <div className="message system-message instant">
                    <div className="avatar">
                      <Icon name="spark" />
                    </div>
                    <div className="content">
                      <div className="message-text">准备好审查您的代码，请选择一个项目文件夹开始。</div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div id="messageContainer" className="message-container">
                <div className="dc-review-live-grid">
                  <div className="dc-live-card">
                    <div className="dc-live-card-head">
                      <strong>当前状态</strong>
                      <span className="badge info">{statusText}</span>
                    </div>
                    <div className="dc-live-card-body">
                      <div className="stat-row">
                        <span className="label">页面</span>
                        <span className="value">{PAGE_LABELS[activePage]}</span>
                      </div>
                      <div className="stat-row">
                        <span className="label">会话</span>
                        <span className="value">{sessionDetail?.summary.name ?? selectedSessionId ?? "未创建"}</span>
                      </div>
                      <div className="stat-row">
                        <span className="label">运行</span>
                        <span className="value">{currentRunId ?? "无"}</span>
                      </div>
                    </div>
                  </div>
                  <div className="dc-live-card">
                    <div className="dc-live-card-head">
                      <strong>最近事件</strong>
                      <span className="badge">{events.length}</span>
                    </div>
                    <div className="dc-live-event-list">
                      {[...events].reverse().slice(0, 6).map((event) => (
                        <div key={`${event.run_id}-${event.seq}`} className="dc-live-event-item">
                          <div className="dc-live-event-meta">
                            <span>{event.type}</span>
                            <span>{formatDateTime(event.created_at)}</span>
                          </div>
                          <div className="dc-live-event-text">{summarizeEvent(event)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

              <footer className={`input-area ${reviewInputCollapsed ? "collapsed" : ""}`}>
              <div className="tools-controls-row">
                <label className="toggle-label align-left">
                  <input type="checkbox" checked={autoApprove} onChange={(event) => setAutoApprove(event.target.checked)} />
                  <span>自动运行（实验）</span>
                </label>
                <div className="tools-collapse-trigger">
                  <button id="toolsCollapseBtn" type="button" className="collapse-btn" title="展开/折叠工具" onClick={() => setToolsCollapsed((current) => !current)}>
                    <Icon name="chevron-down" className="chevron" />
                  </button>
                </div>
                <label className="toggle-label align-right">
                  <input type="checkbox" checked={enableStaticScan} onChange={(event) => setEnableStaticScan(event.target.checked)} />
                  <span>静态分析</span>
                </label>
              </div>

              <div className="tools-panel">
                <div className="tools-header">
                  <span className="tools-title">审查工具</span>
                </div>
                <div id="toolListContainer" className="tool-list">
                  {tools.map((tool) => (
                    <label key={tool.name} className={`tool-item ${selectedTools.includes(tool.name) ? "checked" : ""}`}>
                      <input type="checkbox" checked={selectedTools.includes(tool.name)} onChange={() => toggleTool(tool.name)} />
                      <span>{tool.name}</span>
                    </label>
                  ))}
                </div>
                </div>

                <div className="action-wrapper">
                  <button id="startReviewBtn" type="button" className="review-btn-large" onClick={() => void handleStartReview()} disabled={busyAction === "review"}>
                    <Icon name="send" />
                  </button>
              </div>
            </footer>
          </main>

          <aside id="rightPanel" className="right-panel">
            <section id="progressPanel" className="progress-panel">
              <div className="progress-content">
                <ul className="progress-steps">
                  {STAGE_STEPS.map((step) => {
                    const state = stageStatusMap.get(step.key) ?? "pending";
                    return (
                      <li key={step.key} className={`step-item ${state}`}>
                        <div className="step-icon">
                          <Icon name={step.icon} />
                        </div>
                        <div className="step-info">
                          <div className="step-title">{step.title}</div>
                          <div className="step-desc">{step.desc}</div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
                <div className="progress-right-info">
                  <Icon name="folder" />
                  <span className="path-value">{truncatePath(projectRoot)}</span>
                </div>
              </div>
            </section>

            <div id="rightPanelScrollArea">
              <div id="scannerContainer" className="workflow-entries">
                <div id="scannerWorkflowSection" className={`workflow-stage-section scanner-workflow-section ${scannerCollapsed ? "collapsed" : ""}`} style={{ display: enableStaticScan ? "block" : "none" }}>
                  <div className="stage-header" onClick={() => setScannerCollapsed((current) => !current)}>
                    <div className="stage-indicator" style={{ "--stage-color": "#0ea5e9" } as CSSProperties}>
                      <Icon name="scan" />
                      <span>静态扫描</span>
                    </div>
                    <div className="scanner-header-right">
                      <span id="scannerStageMeta" className="scanner-overview-meta scanner-stage-meta">
                        {scanResult ? `${countScanIssues(scanResult)} 项` : "等待结果"}
                      </span>
                      <Icon name="chevron-down" className="chevron" />
                    </div>
                  </div>
                  <div className="stage-content scanner-stage-content">
                    <div className="scanner-tabs">
                      {(["all", "error", "warning", "info"] as const).map((severity) => (
                        <button key={severity} type="button" className={`scanner-tab ${activeScannerSeverity === severity ? "active" : ""}`} onClick={() => setActiveScannerSeverity(severity)}>
                          {severity === "all" ? "总览" : severity === "error" ? "错误" : severity === "warning" ? "警告" : "信息"} <span className={`tab-count ${severity === "all" ? "" : severity}`}>{countScanIssues(scanResult, severity)}</span>
                        </button>
                      ))}
                    </div>
                    <div className="scanner-content">
                      {!scanResult ? <div className="empty-state compact">暂无静态扫描结果</div> : null}
                      {scanResult ? (
                        <div className="scanner-issues-list">
                          {scannerIssues.length === 0 ? <div className="empty-state compact">当前分组暂无问题</div> : null}
                          {scannerIssues.map(({ severity, item }, index) => {
                            const message = item.message ?? item.title ?? item.rule_id ?? "扫描问题";
                            const location = [item.file, item.path, item.line].filter(Boolean).join(":");
                            return (
                              <div key={`${severity}-${index}`} className="scanner-issue-card">
                                <div className="scanner-issue-head">
                                  <span className={`severity-badge ${severity}`}>{severity}</span>
                                  <span className="issue-location">{location || "未提供位置"}</span>
                                </div>
                                <div className="scanner-issue-message">{String(message)}</div>
                                <pre className="dc-inline-json">{prettyJson(item)}</pre>
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>

              <div className="workflow-entries" id="workflowEntries">
                {workflowGroups.length === 0 ? <div className="empty-state compact">执行后这里会显示各阶段详情。</div> : null}
                {workflowGroups.map((group) => {
                  const collapsed = collapsedWorkflowStages[group.key] ?? false;
                  const latest = group.events[group.events.length - 1];
                  const color =
                    group.key === "init" ? "#334155" : group.key === "analysis" ? "#0ea5e9" : group.key === "planning" ? "#6366f1" : group.key === "reviewing" ? "#0f766e" : "#111827";
                  return (
                    <div key={group.key} className={`workflow-stage-section ${collapsed ? "collapsed" : ""}`}>
                      <div className="stage-header" onClick={() => toggleWorkflowStage(group.key)}>
                        <div className="stage-indicator" style={{ "--stage-color": color } as CSSProperties}>
                          <Icon name={group.icon} />
                          <span>{group.title}</span>
                        </div>
                        <div className="scanner-header-right">
                          <span className="scanner-overview-meta">{latest ? summarizeEvent(latest) : group.desc}</span>
                          <Icon name="chevron-down" className="chevron" />
                        </div>
                      </div>
                      <div className="stage-content">
                        {group.events.slice(-5).map((event) => (
                          <div key={`${event.run_id}-${event.seq}`} className="dc-workflow-event">
                            <div className="dc-workflow-event-head">
                              <strong>{event.type}</strong>
                              <span>{formatDateTime(event.created_at)}</span>
                            </div>
                            <div className="dc-workflow-event-body">{summarizeEvent(event)}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <section id="monitorPanel" className={monitorPanelClass}>
              <div className="panel-header collapsible" onClick={() => setMonitorCollapsed((current) => !current)}>
                <span className="panel-title">日志</span>
                <span id="reviewTimer" className="time-display" style={{ marginLeft: "auto", marginRight: 10 }}>
                  {sessionDetail?.latest_run ? formatDateTime(sessionDetail.latest_run.updated_at) : ""}
                </span>
                <Icon name="chevron-down" className="chevron" />
              </div>
              <div className="workflow-content">
                <div className="workflow-entries" id="monitorContent">
                  {monitorEvents.map((event) => (
                    <div key={`${event.run_id}-${event.seq}`} className="process-item">
                      <div className="api-call-header">
                        <strong>{event.type}</strong>
                        <span className="api-stage-badge">{event.stage || "core"}</span>
                      </div>
                      <div>{summarizeEvent(event)}</div>
                      <ul>
                        <li>{formatDateTime(event.created_at)}</li>
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          </aside>
        </div>
      </div>

      {folderPickerOpen ? (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-content folder-picker-container">
            <div className="modal-header">
              <h3>选择项目文件夹</h3>
              <button type="button" className="icon-btn-small" onClick={() => setFolderPickerOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="modal-body">
              <div className="dc-folder-toolbar">
                <button type="button" className="btn-secondary" onClick={() => {
                  const parent = getParentPath(folderBrowsePath ?? "");
                  if (parent) setFolderBrowsePath(parent);
                }} disabled={!getParentPath(folderBrowsePath ?? "")}>
                  返回上级
                </button>
                <div className="dc-folder-path">{folderListQuery.data?.path ?? folderBrowsePath ?? "..."}</div>
              </div>
              <div className="file-list">
                {folderListQuery.isLoading ? <div className="empty-state compact">正在加载目录...</div> : null}
                {!folderListQuery.isLoading && folderListQuery.data?.children?.length === 0 ? <div className="empty-state compact">当前目录下没有可选择的子目录</div> : null}
                {folderListQuery.data?.children?.map((item) => (
                  <div key={item.path} className="file-list-item">
                    <button type="button" className="dc-folder-item" onClick={() => setFolderBrowsePath(item.path)}>
                      <Icon name="folder" />
                      <span>{item.name}</span>
                    </button>
                    <button type="button" className="btn-primary" onClick={() => {
                      setProjectRoot(item.path);
                      setFolderPickerOpen(false);
                      setStatusText(`已切换项目到 ${item.path}`);
                    }}>
                      选择
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-secondary" onClick={() => setFolderPickerOpen(false)}>
                取消
              </button>
              <button type="button" className="btn-primary" onClick={() => {
                if (folderListQuery.data?.path) {
                  setProjectRoot(folderListQuery.data.path);
                  setFolderPickerOpen(false);
                  setStatusText(`已切换项目到 ${folderListQuery.data.path}`);
                }
              }}>
                使用当前目录
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
