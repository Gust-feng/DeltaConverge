export type SessionSummary = {
  id: string;
  name: string;
  project_root?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  tags: string[];
  latest_run_id?: string | null;
  last_error?: string | null;
};

export type ReviewRun = {
  id: string;
  session_id: string;
  prompt: string;
  model: string;
  status: string;
  created_at: string;
  updated_at: string;
  enable_static_scan: boolean;
  diff_mode?: string | null;
  commit_from?: string | null;
  commit_to?: string | null;
  error_message?: string | null;
  final_report_artifact_id?: string | null;
};

export type ArtifactRef = {
  id: string;
  kind: string;
  session_id: string;
  run_id?: string | null;
  rel_path: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type SessionDetail = {
  summary: SessionSummary;
  latest_run?: ReviewRun | null;
  artifacts: ArtifactRef[];
  latest_report_artifact_id?: string | null;
};

export type MessageRecord = {
  id?: number | null;
  session_id: string;
  run_id?: string | null;
  role: string;
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type WorkflowEvent = {
  id?: number | null;
  run_id: string;
  session_id: string;
  seq: number;
  type: string;
  stage?: string | null;
  created_at: string;
  payload: Record<string, unknown>;
};

export type ScanResult = {
  run_id: string;
  session_id: string;
  summary: Record<string, unknown>;
  issues_by_severity: Record<string, unknown[]>;
  linked: Record<string, unknown>;
  created_at: string;
  artifact_id?: string | null;
};

export type ProjectAnalysis = {
  info: Record<string, unknown>;
  tree: Record<string, unknown>;
  readme: Record<string, unknown>;
  dependencies: Record<string, unknown>;
  git: Record<string, unknown>;
};

export type ProviderStatus = {
  id: string;
  label: string;
  available: boolean;
  configured: boolean;
  model_count: number;
  models: string[];
  api_key_env: string;
  base_url: string;
  error?: string | null;
};

export type ScannerInfo = {
  name: string;
  language: string;
  command: string;
  available: boolean;
  enabled: boolean;
  timeout: number;
};

export type ScannerLanguageStatus = {
  language: string;
  available_count: number;
  enabled_count: number;
  total_count: number;
  detected: boolean;
  scanners: ScannerInfo[];
};

export type ScannerStatus = {
  detected_languages: string[];
  languages: ScannerLanguageStatus[];
};

export type DashboardSummary = {
  health: { status: string };
  project_root?: string | null;
  project?: ProjectAnalysis | null;
  diff_status: Record<string, unknown>;
  session_stats: {
    total_sessions: number;
    by_status: Record<string, number>;
    by_project: Record<string, number>;
    total_messages: number;
  };
  providers: ProviderStatus[];
  scanners: ScannerStatus;
};

export type ToolItem = {
  name: string;
  description: string;
  is_builtin: boolean;
  is_default: boolean;
  parameters: Record<string, unknown>;
};

export type DiffSummary = {
  summary: string;
  mode: string;
  base_branch?: string | null;
  files: string[];
  file_count: number;
  unit_count: number;
  lines_added: number;
  lines_removed: number;
  error?: string | null;
};

export type DiffFile = {
  path: string;
  language: string;
  change_type: string;
  lines_added: number;
  lines_removed: number;
  tags: string[];
};

export type FileDiff = {
  file_path: string;
  diff_text: string;
  hunks: Array<Record<string, unknown>>;
  error?: string | null;
  elapsed_ms?: number;
};

export type CommitInfo = {
  hash: string;
  short_hash: string;
  message: string;
  author: string;
  time_ago: string;
};

export type CommitRangeDiff = {
  success: boolean;
  diff_text: string;
  files: Array<{
    path: string;
    source_file?: string | null;
    target_file?: string | null;
    added_lines: number;
    removed_lines: number;
    is_binary: boolean;
  }>;
  file_count: number;
  commit_from: string;
  commit_to: string;
  elapsed_ms?: number;
  parse_error?: string;
  error?: string;
};

export type RuleGrowthSummary = {
  total_conflicts: number;
  by_type: Record<string, number>;
  by_language: Record<string, number>;
  by_rule_notes: Record<string, number>;
  session_conflicts: number;
  trend?: Record<string, unknown>;
  types?: Record<string, unknown>;
  error?: string | null;
};

export type ApplicableRule = {
  rule_id: string;
  language: string;
  required_tags: string[];
  suggested_context_level: string;
  confidence: number;
  sample_count: number;
  consistency: number;
  unique_files: number;
  conflict_type: string;
};

export type ReferenceHint = {
  language: string;
  tags: string[];
  suggested_context_level: string;
  sample_count: number;
  consistency: number;
  reason: string;
  conflict_type: string;
};
