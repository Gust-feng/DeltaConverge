import type {
  DiffFileItem,
  DiffMode,
  DiffQuickStatus,
  GitCommit,
  IntentRecord,
  LegacyProvider,
  LegacySessionDetail,
  LegacySessionSummary,
  ModelGroup,
  ProviderKeyInfo,
  ScanIssuesPage,
} from "../types";
import type { WorkflowEvent } from "../../types";
import { flattenEvent, flattenEvents, readSseStream, type FlatEvent } from "./events";

type Json = Record<string, unknown>;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = "";
    try {
      const text = await response.text();
      try {
        const parsed = JSON.parse(text) as Json;
        detail = String(parsed.detail ?? parsed.error ?? text);
      } catch {
        detail = text;
      }
    } catch {
      detail = "";
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

// ── 系统 / 健康 ───────────────────────────────────────────────

export function getSystemEnv(): Promise<Json> {
  return request<Json>("/api/v2/system/env");
}

export function listDirectory(path?: string | null): Promise<{
  path: string;
  children: Array<{ name: string; path: string; is_dir: boolean }>;
  error?: string | null;
}> {
  return request("/api/v2/system/list-directory", jsonInit("POST", { path: path ?? null }));
}

export function pickFolder(): Promise<{ path?: string | null; error?: string | null }> {
  return request("/api/v2/system/pick-folder", jsonInit("POST", {}));
}

export function getHealth(): Promise<Json> {
  return request<Json>("/api/v2/health");
}

// ── 配置 / 服务商 / 模型 ──────────────────────────────────────

export function getConfig(): Promise<Json> {
  return request<Json>("/api/v2/config");
}

export function updateConfig(updates: Json): Promise<Json> {
  return request<Json>("/api/v2/config", jsonInit("PATCH", { updates, persist: true }));
}

export function getToolsRaw(): Promise<Array<{ name: string; description: string; is_default: boolean }>> {
  return request<{ items: Array<{ name: string; description: string; is_default: boolean }> }>("/api/v2/tools").then((r) => r.items);
}

export type ProviderInfo = {
  id: string;
  label: string;
  available: boolean;
  configured: boolean;
  model_count?: number;
  models: string[];
  model_details?: Array<Record<string, unknown>>;
  api_key_env?: string;
  base_url?: string;
  protocol?: string;
  custom?: boolean;
  added?: boolean;
  disabled?: boolean;
  error?: string | null;
};

export function getProvidersRaw(includeDisabled = false): Promise<ProviderInfo[]> {
  const suffix = includeDisabled ? "?include_disabled=true" : "";
  return request<{ items: ProviderInfo[] }>(`/api/v2/models/providers${suffix}`).then((r) => r.items);
}

export function discoverProviderModels(provider: string, signal?: AbortSignal): Promise<{
  provider: string;
  models: string[];
  base_url?: string;
}> {
  return request(`/api/v2/models/discover`, { ...jsonInit("POST", { provider }), signal });
}

export function createProvider(payload: {
  label: string;
  base_url: string;
  protocol: string;
  api_key?: string;
}): Promise<ProviderInfo> {
  return request<ProviderInfo>("/api/v2/models/providers", jsonInit("POST", payload));
}

export function updateProvider(provider: string, updates: {
  disabled?: boolean;
  base_url?: string;
  protocol?: string;
}): Promise<Json> {
  return request<Json>(
    `/api/v2/models/providers/${encodeURIComponent(provider)}`,
    jsonInit("PATCH", updates)
  );
}

export function setProviderDisabled(provider: string, disabled: boolean): Promise<Json> {
  return updateProvider(provider, { disabled });
}

export function deleteProvider(provider: string): Promise<Json> {
  return request<Json>(`/api/v2/models/providers/${encodeURIComponent(provider)}`, { method: "DELETE" });
}

export async function getProvidersLegacy(): Promise<LegacyProvider[]> {
  const items = await getProvidersRaw();
  return items.map((p) => ({
    name: p.id,
    label: p.label,
    available: Boolean(p.available),
    error: p.error ?? null,
  }));
}

export function isAddedProvider(provider: ProviderInfo): boolean {
  return !provider.disabled && Boolean(provider.added || provider.custom || provider.configured);
}

export function buildModelGroups(providers: ProviderInfo[]): ModelGroup[] {
  return providers.filter((provider) => isAddedProvider(provider) && provider.models.length > 0).map((provider) => ({
    provider: provider.id,
    label: provider.label,
    is_active: Boolean(provider.available && provider.configured),
    models: provider.models.map((model) => {
      const details = provider.model_details?.find((item) => item.id === model);
      const capabilities = details?.capabilities;
      const available = Boolean(provider.available && provider.configured);
      return {
        name: `${provider.id}:${model}`,
        label: model,
        available,
        reason: available ? null : provider.error ?? "请先配置服务凭据",
        capabilities: capabilities && typeof capabilities === "object"
          ? capabilities as Record<string, unknown> : undefined,
      };
    }),
  }));
}

export function getProviderKeys(): Promise<{ providers: ProviderKeyInfo[] }> {
  return request<{ providers: ProviderKeyInfo[] }>("/api/v2/providers/keys");
}

export function setProviderKey(provider: string, value: string): Promise<Json> {
  return request<Json>("/api/v2/providers/keys", jsonInit("POST", { provider, value }));
}

export function addModel(provider: string, modelName: string): Promise<Json> {
  return request<Json>("/api/v2/models/add", jsonInit("POST", { provider, model_name: modelName }));
}

export function deleteModel(provider: string, modelName: string): Promise<Json> {
  return request<Json>("/api/v2/models/delete", jsonInit("POST", { provider, model_name: modelName }));
}

export type ModelMetadataOverrides = {
  limits: Record<string, number>;
  capabilities: Record<string, boolean>;
};

export type ModelMetadataSettings = {
  id: string;
  limits: Record<string, number>;
  capabilities: Record<string, boolean>;
  defaults: ModelMetadataOverrides;
  overrides: ModelMetadataOverrides;
  source?: string;
  catalog?: string;
};

export function getModelMetadataSettings(provider: string, modelName: string, signal?: AbortSignal): Promise<ModelMetadataSettings> {
  const query = new URLSearchParams({ provider, model_name: modelName });
  return request(`/api/v2/models/metadata?${query}`, { signal });
}

export function updateModelMetadataSettings(provider: string, modelName: string, overrides: ModelMetadataOverrides): Promise<ModelMetadataSettings> {
  return request("/api/v2/models/metadata", jsonInit("PATCH", { provider, model_name: modelName, ...overrides }));
}

// ── 会话 ─────────────────────────────────────────────────────

export async function listSessionsLegacy(projectRoot?: string | null, signal?: AbortSignal): Promise<LegacySessionSummary[]> {
  const suffix = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
  const data = await request<{ items: Array<any> }>(`/api/v2/sessions${suffix}`, { signal });
  return (data.items ?? []).map((s) => ({
    session_id: s.id,
    name: s.name,
    project_root: s.project_root,
    status: s.status,
    created_at: s.created_at,
    updated_at: s.updated_at,
  }));
}

export async function getSessionDetailRaw(sessionId: string, signal?: AbortSignal): Promise<any> {
  return request<any>(`/api/v2/sessions/${encodeURIComponent(sessionId)}`, { signal });
}

export async function getMessages(sessionId: string): Promise<Array<any>> {
  const data = await request<{ items: Array<any> }>(`/api/v2/sessions/${encodeURIComponent(sessionId)}/messages?limit=200&offset=0`);
  return data.items ?? [];
}

export async function getEvents(sessionId: string, runId?: string | null): Promise<WorkflowEvent[]> {
  const suffix = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  const data = await request<{ items: WorkflowEvent[] }>(`/api/v2/sessions/${encodeURIComponent(sessionId)}/events${suffix}`);
  return data.items ?? [];
}

export async function getSessionLegacy(sessionId: string): Promise<LegacySessionDetail> {
  const detail = await getSessionDetailRaw(sessionId);
  const runId: string | null = detail?.latest_run?.id ?? detail?.summary?.latest_run_id ?? null;
  const [messages, events, diff, scan] = await Promise.all([
    getMessages(sessionId).catch(() => []),
    runId ? getEvents(sessionId, runId).catch(() => []) : Promise.resolve([]),
    runId ? request<Json>(`/api/v2/reviews/${encodeURIComponent(runId)}/diff`).catch(() => ({})) : Promise.resolve({} as Json),
    runId ? request<Json>(`/api/v2/scans/${encodeURIComponent(runId)}`).catch(() => null) : Promise.resolve(null),
  ]);
  const scanData = scan && !("status" in scan) ? scan : {};
  return {
    session_id: sessionId,
    metadata: {
      name: detail?.summary?.name,
      project_root: detail?.summary?.project_root,
      status: detail?.summary?.status,
      created_at: detail?.summary?.created_at,
      updated_at: detail?.summary?.updated_at,
      tags: detail?.summary?.tags ?? [],
    },
    messages: messages.map((m) => ({
      role: m.role,
      content: m.content,
      created_at: m.created_at,
      metadata: m.metadata,
    })),
    workflow_events: flattenEvents(events) as Array<Record<string, unknown>>,
    diff_files: (diff as any)?.diff_files ?? [],
    diff_units: (diff as any)?.diff_units ?? [],
    static_scan_linked: (scanData as any)?.linked ?? {},
    latest_run_id: runId,
    run_status: detail?.latest_run?.status ?? detail?.summary?.status ?? null,
  };
}

export async function getSessionDiffSnapshot(sessionId: string, signal?: AbortSignal): Promise<Pick<LegacySessionDetail, "metadata" | "diff_files" | "diff_units" | "static_scan_linked" | "latest_run_id">> {
  const detail = await getSessionDetailRaw(sessionId, signal);
  const runId: string | null = detail?.latest_run?.id ?? detail?.summary?.latest_run_id ?? null;
  const [diff, scan] = await Promise.all([
    runId ? request<Json>(`/api/v2/reviews/${encodeURIComponent(runId)}/diff`, { signal }) : Promise.resolve({} as Json),
    runId ? request<any>(`/api/v2/scans/${encodeURIComponent(runId)}`, { signal }).catch((error: unknown) => {
      if (signal?.aborted) throw error;
      return null;
    }) : Promise.resolve(null),
  ]);
  return {
    metadata: { project_root: detail?.summary?.project_root },
    diff_files: (diff as any)?.diff_files ?? [],
    diff_units: (diff as any)?.diff_units ?? [],
    static_scan_linked: scan?.linked ?? {},
    latest_run_id: runId,
  };
}

export async function createSession(payload: { session_id?: string; name?: string; project_root?: string | null }): Promise<Json> {
  return request<Json>("/api/v2/sessions", jsonInit("POST", payload));
}

export async function getSessionStatus(sessionId: string): Promise<{ completed: boolean; status: string }> {
  return request(`/api/v2/sessions/${encodeURIComponent(sessionId)}/status`);
}

export function renameSession(sessionId: string, name: string): Promise<Json> {
  return request<Json>(`/api/v2/sessions/${encodeURIComponent(sessionId)}`, jsonInit("PATCH", { name }));
}

export function deleteSession(sessionId: string): Promise<Json> {
  return request<Json>(`/api/v2/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}

// ── 审查 / 对话 ──────────────────────────────────────────────

export function createReview(payload: Json): Promise<Json> {
  return request<Json>("/api/v2/reviews", jsonInit("POST", payload));
}

export type ReviewStreamHandlers = {
  onEnvelope?: (event: WorkflowEvent) => void;
  onEvent?: (event: FlatEvent) => void;
  onTerminal?: (event: WorkflowEvent) => void;
  onError?: (error: unknown) => void;
};

export async function streamReview(runId: string, handlers: ReviewStreamHandlers, signal?: AbortSignal): Promise<void> {
  try {
    const response = await fetch(`/api/v2/reviews/${encodeURIComponent(runId)}/stream`, { signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    let terminalSeen = false;
    await readSseStream(response, (data) => {
      const event = data as unknown as WorkflowEvent;
      handlers.onEnvelope?.(event);
      for (const flat of flattenEvent(event)) {
        handlers.onEvent?.(flat);
      }
      if (event.type === "review.completed" || event.type === "review.failed") {
        if (!terminalSeen) {
          terminalSeen = true;
          handlers.onTerminal?.(event);
        }
      }
    });
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") return;
    handlers.onError?.(error);
  }
}

export async function sendChat(
  sessionId: string,
  payload: { message: string; model: string; tools: string[]; auto_approve: boolean; project_root?: string | null },
  handlers: ReviewStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  try {
    const response = await fetch(`/api/v2/sessions/${encodeURIComponent(sessionId)}/chat`, {
      ...jsonInit("POST", payload),
      signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await readSseStream(response, (data) => {
      const event = data as unknown as WorkflowEvent;
      handlers.onEnvelope?.(event);
      for (const flat of flattenEvent(event)) handlers.onEvent?.(flat);
      if (event.type === "review.completed" || event.type === "review.failed") handlers.onTerminal?.(event);
    });
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") return;
    handlers.onError?.(error);
  }
}

export function askQuestion(runId: string, question: string, model: string): Promise<{ answer: string }> {
  return request(`/api/v2/reviews/${encodeURIComponent(runId)}/qa`, jsonInit("POST", { question, model }));
}

// ── Diff / Git ───────────────────────────────────────────────

export async function getDiffStatus(projectRoot?: string | null): Promise<Json> {
  const suffix = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
  return request<Json>(`/api/v2/diff/status${suffix}`);
}

export async function getDiffFiles(projectRoot: string | null | undefined, mode: DiffMode | string, signal?: AbortSignal): Promise<{
  files: DiffFileItem[];
  detected_mode?: string;
  error?: string | null;
}> {
  const params = new URLSearchParams();
  if (projectRoot) params.set("project_root", projectRoot);
  params.set("mode", mode);
  return request(`/api/v2/diff/files?${params.toString()}`, { signal });
}

export async function getDiffSummary(projectRoot: string | null | undefined, mode: DiffMode | string): Promise<Json> {
  const params = new URLSearchParams();
  if (projectRoot) params.set("project_root", projectRoot);
  params.set("mode", mode);
  return request<Json>(`/api/v2/diff/summary?${params.toString()}`);
}

export function getDiffQuickStatus(projectRoot: string | null | undefined): Promise<DiffQuickStatus> {
  const suffix = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
  return request<DiffQuickStatus>(`/api/v2/diff/quick-status${suffix}`);
}

export async function analyzeDiff(projectRoot: string | null | undefined, mode: DiffMode | string): Promise<{
  status: Json;
  summary: { error?: string | null; mode?: string; files?: string[] };
  files: DiffFileItem[];
  detected_mode?: string;
  units: unknown[];
}> {
  const [status, files] = await Promise.all([getDiffStatus(projectRoot), getDiffFiles(projectRoot, mode)]);
  return {
    status,
    summary: {
      error: files.error ?? (status.error as string | undefined) ?? null,
      mode: String(status.detected_mode ?? files.detected_mode ?? mode),
      files: (files.files ?? []).map((f) => f.path),
    },
    files: files.files ?? [],
    detected_mode: files.detected_mode ?? (status.detected_mode as string | undefined),
    units: [],
  };
}

export async function getFileDiff(options: {
  filePath: string;
  projectRoot?: string | null;
  mode?: string;
  commitFrom?: string | null;
  commitTo?: string | null;
}): Promise<{ file_path?: string; diff_text?: string; diff_content?: string; error?: string | null }> {
  const params = new URLSearchParams();
  params.set("file_path", options.filePath);
  if (options.projectRoot) params.set("project_root", options.projectRoot);
  if (options.mode) params.set("mode", options.mode);
  if (options.commitFrom) params.set("commit_from", options.commitFrom);
  if (options.commitTo) params.set("commit_to", options.commitTo);
  return request(`/api/v2/diff/file?${params.toString()}`);
}

export async function getCommits(
  projectRoot: string,
  limit = 20,
  skip = 0,
  branch?: string | null
): Promise<{ success?: boolean; commits: GitCommit[]; error?: string | null; skip?: number }> {
  const params = new URLSearchParams({ project_root: projectRoot, limit: String(limit), skip: String(skip) });
  if (branch) params.set("branch", branch);
  const data = await request<any>(`/api/v2/diff/commits?${params.toString()}`);
  return { success: data.success ?? true, commits: data.commits ?? [], error: data.error ?? null, skip: data.skip ?? skip };
}

export async function getCommitRange(
  projectRoot: string,
  commitFrom: string,
  commitTo?: string | null,
  signal?: AbortSignal,
): Promise<any> {
  const params = new URLSearchParams({ project_root: projectRoot, commit_from: commitFrom });
  if (commitTo) params.set("commit_to", commitTo);
  return request<any>(`/api/v2/diff/commit-range?${params.toString()}`, { signal });
}

export async function getGitBranch(projectRoot: string): Promise<string | null> {
  const data = await request<any>(`/api/v2/projects/analyze?project_root=${encodeURIComponent(projectRoot)}`);
  const git = data?.git ?? {};
  return git.current_branch ?? git.branch ?? null;
}

export async function checkGitRepository(path: string): Promise<{ is_git: boolean; git_root?: string | null; error?: string | null }> {
  return request(`/api/v2/git/check`, jsonInit("POST", { path }));
}

// ── 扫描 / 项目 / 意图 / 缓存 ────────────────────────────────

export function getScan(runId: string): Promise<any> {
  return request<any>(`/api/v2/scans/${encodeURIComponent(runId)}`);
}

export function getScanIssues(runId: string, severity: string, offset = 0, limit = 50): Promise<ScanIssuesPage> {
  const params = new URLSearchParams({ severity, offset: String(offset), limit: String(limit) });
  return request<ScanIssuesPage>(`/api/v2/scans/${encodeURIComponent(runId)}/issues?${params.toString()}`);
}

export function getProjectInfo(projectRoot: string): Promise<any> {
  return request<any>(`/api/v2/projects/analyze?project_root=${encodeURIComponent(projectRoot)}`);
}

export function getIntent(projectRoot: string, projectName: string): Promise<IntentRecord> {
  const params = new URLSearchParams({ project_root: projectRoot, project_name: projectName });
  return request<IntentRecord>(`/api/v2/intent?${params.toString()}`);
}

export function updateIntent(projectRoot: string, content: string): Promise<{ success?: boolean; error?: string | null }> {
  return request("/api/v2/intent/update", jsonInit("POST", { project_root: projectRoot, content }));
}

export type IntentStreamHandlers = {
  onThought?: (content: string) => void;
  onChunk?: (content: string) => void;
  onFinal?: (content: string) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
};

export async function analyzeIntentStream(
  projectRoot: string,
  model: string,
  handlers: IntentStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch("/api/v2/intent/analyze-stream", {
    ...jsonInit("POST", { project_root: projectRoot, model, force_refresh: false }),
    signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  await readSseStream(response, (data) => {
    const type = String(data.type ?? "");
    const content = String(data.content ?? "");
    if (type === "thought") handlers.onThought?.(content);
    else if (type === "chunk") handlers.onChunk?.(content);
    else if (type === "final") handlers.onFinal?.(content);
    else if (type === "error") handlers.onError?.(String(data.message ?? "分析失败"));
    else if (type === "done") handlers.onDone?.();
  });
}

export function getCacheStats(): Promise<Json> {
  return request<Json>("/api/v2/cache/stats");
}

export function listIntentCaches(): Promise<Array<Json>> {
  return request<Array<Json>>("/api/v2/cache/intent");
}

export function clearIntentCache(projectName?: string | null): Promise<Json> {
  const suffix = projectName ? `?project_name=${encodeURIComponent(projectName)}` : "";
  return request<Json>(`/api/v2/cache/intent${suffix}`, { method: "DELETE" });
}

// ── 规则成长 ─────────────────────────────────────────────────

export function getRuleGrowthSummary(): Promise<any> {
  return request<any>("/api/v2/rule-growth/summary");
}

export function getRuleGrowthSuggestions(): Promise<any> {
  return request<any>("/api/v2/rule-growth/enhanced-suggestions");
}

export function applyRule(ruleId: string): Promise<any> {
  return request("/api/v2/rule-growth/apply", jsonInit("POST", { rule_id: ruleId }));
}

export function cleanupRuleGrowth(maxAgeDays = 30): Promise<any> {
  return request("/api/v2/rule-growth/cleanup", jsonInit("POST", { max_age_days: maxAgeDays, clear_session: false }));
}

export function promoteHint(payload: Record<string, unknown>): Promise<any> {
  return request("/api/v2/rule-growth/promote-hint", jsonInit("POST", payload));
}
