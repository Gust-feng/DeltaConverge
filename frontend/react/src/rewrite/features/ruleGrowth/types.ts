/**
 * 规则优化页内部数据类型。
 * 字段命名同时保留旧版 snake_case 与少数 camelCase 兼容读取，
 * 与 legacy/ui_v1/static/modules/rule-growth.js 的读取顺序一致。
 */

export type RuleGrowthMetrics = {
  added_lines?: number;
  removed_lines?: number;
  hunk_count?: number;
};

export type RuleGrowthConflict = {
  promoted?: boolean;
  file_path?: string;
  filePath?: string;
  conflict_type?: string;
  conflictType?: string;
  timestamp?: string;
  language?: string;
  llm_context_level?: string;
  llmContextLevel?: string;
  rule_context_level?: string;
  ruleContextLevel?: string;
  rule_confidence?: number | null;
  ruleConfidence?: number | null;
  llm_reason?: string;
  llmReason?: string;
  rule_notes?: string;
  ruleNotes?: string;
  metrics?: RuleGrowthMetrics;
  tags?: string[];
};

export type UnmetCondition = {
  name?: string;
  condition_name?: string;
  currentValue?: unknown;
  requiredValue?: unknown;
};

export type ApplicableRule = {
  rule_id?: string;
  language?: string;
  required_tags?: string[];
  suggested_context_level?: string;
  confidence?: number;
  sample_count?: number;
  consistency?: number;
  unique_files?: number;
  conflict_type?: string;
};

export type RuleGrowthHint = {
  language?: string;
  tags?: string[];
  suggested_context_level?: string;
  suggestedContextLevel?: string;
  sample_count?: number;
  sampleCount?: number;
  consistency?: number;
  unique_files?: number;
  uniqueFiles?: number;
  reason?: string;
  conflict_type?: string;
  conflictType?: string;
  conflicts?: RuleGrowthConflict[];
  unmetConditions?: UnmetCondition[];
  unmet_conditions?: UnmetCondition[] | Record<string, unknown>;
  /** 渲染时一次性生成的 DOM id，等价于旧版 renderReferenceHint 内的 Date.now()。 */
  hintId?: string;
};

export type RuleGrowthSummaryData = {
  total: number;
  byType: Record<string, number>;
  byLanguage: Record<string, number>;
};

export type SummaryState =
  | { status: "initial" }
  | { status: "ready"; data: RuleGrowthSummaryData; emptyRemoved?: boolean }
  | { status: "error"; message: string };

export type GroupedFile = {
  fileName: string;
  filePath: string;
  conflictType: string;
  timestamp: string;
  language: string;
  llmContext: string;
  ruleContext: string;
  ruleConfidence?: number | null;
  llmReason: string;
  ruleNotes: string;
  metrics: RuleGrowthMetrics;
  tags: string[];
};

export type DecisionStats = {
  llmDecisions: Record<string, number>;
  ruleDecisions: Record<string, number>;
  total: number;
};

export type TimeDistribution = {
  timestamps: string[];
  earliest: string | null;
  latest: string | null;
  count?: number;
};
