import type {
  ApplicableRule,
  CommitInfo,
  CommitRangeDiff,
  DashboardSummary,
  DiffFile,
  DiffSummary,
  FileDiff,
  MessageRecord,
  ProviderStatus,
  ProjectAnalysis,
  ReferenceHint,
  ReviewRun,
  RuleGrowthSummary,
  ScanResult,
  ScannerStatus,
  SessionDetail,
  SessionSummary,
  ToolItem,
  WorkflowEvent,
} from "./types";

export type ReviewCreateResponse = {
  session: SessionDetail | SessionSummary;
  run: Pick<ReviewRun, "id" | "session_id" | "status">;
};

async function request<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listSessions(): Promise<SessionSummary[]> {
  const data = await request<{ items: SessionSummary[] }>("/api/v2/sessions");
  return data.items;
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/v2/sessions/${encodeURIComponent(sessionId)}`);
}

export async function getMessages(sessionId: string): Promise<MessageRecord[]> {
  const data = await request<{ items: MessageRecord[] }>(`/api/v2/sessions/${encodeURIComponent(sessionId)}/messages`);
  return data.items;
}

export async function getEvents(sessionId: string, runId?: string | null): Promise<WorkflowEvent[]> {
  const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const data = await request<{ items: WorkflowEvent[] }>(`/api/v2/sessions/${encodeURIComponent(sessionId)}/events${suffix}`);
  return data.items;
}

export async function createReview(payload: Record<string, unknown>) {
  return request<ReviewCreateResponse>("/api/v2/reviews", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateSession(sessionId: string, payload: { name?: string; status?: string; tags?: string[] }) {
  return request<SessionSummary>(`/api/v2/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteSession(sessionId: string) {
  return request<{ status: string; session_id: string }>(`/api/v2/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function getDiff(runId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/v2/reviews/${encodeURIComponent(runId)}/diff`);
}

export async function askReviewQuestion(runId: string, question: string, model: string) {
  return request<{ answer: string }>(`/api/v2/reviews/${encodeURIComponent(runId)}/qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, model }),
  });
}

export async function getScan(runId: string): Promise<ScanResult | { status: string }> {
  return request(`/api/v2/scans/${encodeURIComponent(runId)}`);
}

export async function analyzeProject(projectRoot: string): Promise<ProjectAnalysis> {
  return request<ProjectAnalysis>(`/api/v2/projects/analyze?project_root=${encodeURIComponent(projectRoot)}`);
}

export async function getDashboardSummary(projectRoot?: string | null): Promise<DashboardSummary> {
  const suffix = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
  return request<DashboardSummary>(`/api/v2/dashboard/summary${suffix}`);
}

export async function getDiffStatus(projectRoot?: string | null) {
  const suffix = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
  return request<Record<string, unknown>>(`/api/v2/diff/status${suffix}`);
}

export async function getDiffSummary(projectRoot?: string | null, mode = "auto"): Promise<DiffSummary> {
  const params = new URLSearchParams();
  if (projectRoot) params.set("project_root", projectRoot);
  params.set("mode", mode);
  return request<DiffSummary>(`/api/v2/diff/summary?${params.toString()}`);
}

export async function getDiffFiles(projectRoot?: string | null, mode = "auto"): Promise<{ files: DiffFile[]; detected_mode: string; error?: string | null }> {
  const params = new URLSearchParams();
  if (projectRoot) params.set("project_root", projectRoot);
  params.set("mode", mode);
  return request(`/api/v2/diff/files?${params.toString()}`);
}

export async function getFileDiff(options: {
  filePath: string;
  projectRoot?: string | null;
  mode?: string;
  commitFrom?: string | null;
  commitTo?: string | null;
}): Promise<FileDiff> {
  const params = new URLSearchParams();
  params.set("file_path", options.filePath);
  if (options.projectRoot) params.set("project_root", options.projectRoot);
  if (options.mode) params.set("mode", options.mode);
  if (options.commitFrom) params.set("commit_from", options.commitFrom);
  if (options.commitTo) params.set("commit_to", options.commitTo);
  return request<FileDiff>(`/api/v2/diff/file?${params.toString()}`);
}

export async function getCommitHistory(projectRoot: string, limit = 50): Promise<{ commits: CommitInfo[]; count: number }> {
  const params = new URLSearchParams({ project_root: projectRoot, limit: String(limit) });
  return request(`/api/v2/diff/commits?${params.toString()}`);
}

export async function getCommitRangeDiff(projectRoot: string, commitFrom: string, commitTo?: string | null): Promise<CommitRangeDiff> {
  const params = new URLSearchParams({ project_root: projectRoot, commit_from: commitFrom });
  if (commitTo) params.set("commit_to", commitTo);
  return request(`/api/v2/diff/commit-range?${params.toString()}`);
}

export async function getConfig() {
  return request<Record<string, unknown>>("/api/v2/config");
}

export async function updateConfig(updates: Record<string, unknown>) {
  return request<Record<string, unknown>>("/api/v2/config", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates, persist: true }),
  });
}

export async function getTools() {
  return request<{ items: ToolItem[] }>("/api/v2/tools");
}

export async function getProviders() {
  return request<{ items: ProviderStatus[] }>("/api/v2/models/providers");
}

export async function getScannerStatus(projectRoot?: string | null): Promise<ScannerStatus> {
  const summary = await getDashboardSummary(projectRoot);
  return summary.scanners;
}

export async function getRuleGrowthSummary(): Promise<RuleGrowthSummary> {
  return request<RuleGrowthSummary>("/api/v2/rule-growth/summary");
}

export async function getRuleGrowthSuggestions(): Promise<{ applicable_rules: ApplicableRule[]; reference_hints: ReferenceHint[]; error?: string | null }> {
  return request("/api/v2/rule-growth/enhanced-suggestions");
}

export async function applyRule(ruleId: string) {
  return request<{ success: boolean; applied_rule?: Record<string, unknown>; error?: string | null }>("/api/v2/rule-growth/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rule_id: ruleId }),
  });
}

export async function promoteHint(payload: {
  language: string;
  tags: string[];
  suggested_context_level: string;
  sample_count?: number;
  consistency?: number;
  conflict_type?: string;
}) {
  return request<{ success: boolean; applied_rule?: Record<string, unknown>; error?: string | null }>("/api/v2/rule-growth/promote-hint", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function cleanupRuleGrowth(maxAgeDays = 30) {
  return request<{ deleted_count: number; remaining_count: number; error?: string | null }>("/api/v2/rule-growth/cleanup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ max_age_days: maxAgeDays, clear_session: true }),
  });
}

export async function getSystemEnv() {
  return request<{ platform: string; default_project_root: string; cwd: string }>("/api/v2/system/env");
}

export async function listDirectories(path?: string | null) {
  return request<{ path: string; children: Array<{ name: string; path: string; is_dir: boolean }>; error?: string | null }>("/api/v2/system/list-directory", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
}
