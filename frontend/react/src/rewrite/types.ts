export type ActivePage = "dashboard" | "review" | "diff" | "config" | "rule-growth";
export type LayoutState = "initial" | "reviewing" | "completed";
export type DiffMode = "auto" | "working" | "staged" | "pr" | "commit";
export type ReportViewMode = "report" | "diff";

export type ModelItem = {
  name: string;
  label: string;
  available: boolean;
  reason?: string | null;
  capabilities?: Record<string, unknown>;
};

export type ModelGroup = {
  provider: string;
  label: string;
  is_active: boolean;
  models: ModelItem[];
};

export type ToolOption = {
  name: string;
  description: string;
  default: boolean;
};

export type LegacyProvider = {
  name: string;
  label: string;
  available: boolean;
  error?: string | null;
};

export type ProviderKeyInfo = {
  provider: string;
  label: string;
  configured: boolean;
  masked?: string;
};

export type LegacySessionSummary = {
  session_id: string;
  name: string;
  project_root?: string | null;
  status?: string;
  created_at?: string;
  updated_at?: string;
};

export type LegacySessionDetail = {
  session_id: string;
  metadata: {
    name?: string;
    project_root?: string | null;
    status?: string;
    created_at?: string;
    updated_at?: string;
    tags?: string[];
  };
  messages: Array<{ role: string; content: string; created_at?: string; metadata?: Record<string, unknown> }>;
  workflow_events: Array<Record<string, unknown>>;
  diff_files: Array<Record<string, unknown>>;
  diff_units: Array<Record<string, unknown>>;
  static_scan_linked: Record<string, unknown>;
  latest_run_id?: string | null;
  run_status?: string | null;
};

export type DiffFileItem = {
  path: string;
  display_path?: string;
  language?: string;
  change_type?: string;
  lines_added?: number;
  lines_removed?: number;
  tags?: string[];
};

export type DiffQuickStatus = {
  error?: string | null;
  mode: string;
  files: DiffFileItem[];
  has_staged?: boolean;
  has_working?: boolean;
};

export type ScanIssue = Record<string, unknown> & {
  file?: string;
  path?: string;
  line?: number;
  start_line?: number;
  column?: number;
  severity?: string;
  message?: string;
  rule_id?: string;
  scanner?: string;
};

export type ScanIssuesPage = {
  issues: ScanIssue[];
  offset: number;
  has_more: boolean;
  total?: number;
};

export type GitCommit = {
  hash: string;
  short_hash?: string;
  message: string;
  author?: string;
  date?: string;
  relative_date?: string;
  time_ago?: string;
  is_merge?: boolean;
  refs?: string;
  parents?: string[];
};

export type IntentRecord = {
  found?: boolean;
  project_name?: string;
  content?: string;
  created_at?: string;
  updated_at?: string;
  source?: string;
};

export type RuleGrowthSummaryData = {
  error?: string | null;
  total_conflicts: number;
  by_type: Record<string, number>;
  by_language: Record<string, number>;
  session_conflicts?: number;
};

export type ApplicableRuleData = {
  rule_id: string;
  language: string;
  required_tags: string[];
  suggested_context_level: string;
  confidence?: number;
  sample_count: number;
  consistency: number;
  unique_files: number;
  conflict_type: string;
};

export type ReferenceHintData = {
  language: string;
  tags: string[];
  suggested_context_level: string;
  sample_count: number;
  consistency: number;
  unique_files?: number;
  reason: string;
  conflict_type: string;
  conflicts?: Array<Record<string, unknown>>;
  unmet_conditions?: Record<string, unknown> | Array<Record<string, unknown>>;
};

export type ConfirmDialogOptions = {
  title?: string;
  content: string;
  confirmText?: string;
  cancelText?: string;
  showCloseButton?: boolean;
  showCancel?: boolean;
  onConfirm?: () => void | Promise<void>;
  onCancel?: () => void;
};
