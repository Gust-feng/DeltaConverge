import { formatLanguageLabel } from "../../lib/html";
import type {
  DecisionStats,
  GroupedFile,
  RuleGrowthConflict,
  RuleGrowthHint,
  TimeDistribution,
  UnmetCondition,
} from "./types";

const TYPE_ICONS: Record<string, string> = {
  rule_high_llm_expand: "trending-up",
  rule_high_llm_skip: "x",
  rule_low_llm_consistent: "lightbulb",
  context_level_mismatch: "alert-triangle",
};

const TYPE_LABELS: Record<string, string> = {
  rule_high_llm_expand: "LLM 要求更多上下文",
  rule_high_llm_skip: "LLM 建议跳过",
  rule_low_llm_consistent: "可提取新规则",
  context_level_mismatch: "上下文级别不匹配",
};

const CONFLICT_TYPE_LABELS: Record<string, string> = {
  rule_high_llm_expand: "规则高/LLM扩展",
  rule_high_llm_skip: "规则高/LLM跳过",
  rule_low_llm_consistent: "规则低/LLM一致",
  context_level_mismatch: "上下文级别不匹配",
};

const SUGGESTION_TYPE_LABELS: Record<string, string> = {
  upgrade_context_level: "提升上下文级别",
  add_noise_detection: "添加噪音检测",
  new_rule: "新增规则",
};

const SUGGESTION_TYPE_BADGE_CLASSES: Record<string, string> = {
  upgrade_context_level: "warning",
  add_noise_detection: "info",
  new_rule: "success",
};

/** rule-growth.js:155-164 */
export function getRuleGrowthTypeIcon(type: string): string {
  return TYPE_ICONS[type] || "rule";
}

/** rule-growth.js:166-174 */
export function getRuleGrowthTypeLabel(type: string): string {
  return TYPE_LABELS[type] || type;
}

/** rule-growth.js:176-184 */
export function getConflictTypeLabel(conflictType: string): string {
  return CONFLICT_TYPE_LABELS[conflictType] || conflictType || "";
}

/** rule-growth.js:186-193 */
export function getSuggestionTypeLabel(type: string): string {
  return SUGGESTION_TYPE_LABELS[type] || type;
}

/** rule-growth.js:195-202 */
export function getSuggestionTypeBadgeClass(type: string): string {
  return SUGGESTION_TYPE_BADGE_CLASSES[type] || "";
}

/** rule-growth.js:550 */
export function getHintLanguageId(language: string): string {
  return `lang-group-${language.replace(/[^a-zA-Z0-9]/g, "-")}`;
}

/** rule-growth.js:517-536 */
export function groupHintsByLanguage(hints: RuleGrowthHint[]): Record<
  string,
  { count: number; hints: RuleGrowthHint[] }
> {
  const groups: Record<string, { count: number; hints: RuleGrowthHint[] }> = {};

  for (const hint of hints) {
    const language = hint.language || "unknown";
    if (!groups[language]) {
      groups[language] = { count: 0, hints: [] };
    }
    groups[language].hints.push(hint);
    groups[language].count++;
  }

  return groups;
}

/** rule-growth.js:483-515 */
export function groupFilesByDirectory(conflicts: RuleGrowthConflict[]): Record<string, GroupedFile[]> {
  const groups: Record<string, GroupedFile[]> = {};

  for (const conflict of conflicts) {
    if (conflict.promoted) continue;

    const filePath = conflict.file_path || conflict.filePath || "";
    const lastSlash = filePath.lastIndexOf("/");
    const directory = lastSlash > 0 ? filePath.substring(0, lastSlash) : "(root)";
    const fileName = lastSlash > 0 ? filePath.substring(lastSlash + 1) : filePath;

    if (!groups[directory]) {
      groups[directory] = [];
    }

    groups[directory].push({
      fileName,
      filePath,
      conflictType: conflict.conflict_type || conflict.conflictType || "",
      timestamp: conflict.timestamp || "",
      language: conflict.language || "unknown",
      llmContext: conflict.llm_context_level || conflict.llmContextLevel || "",
      ruleContext: conflict.rule_context_level || conflict.ruleContextLevel || "",
      ruleConfidence: conflict.rule_confidence ?? conflict.ruleConfidence,
      llmReason: conflict.llm_reason || conflict.llmReason || "",
      ruleNotes: conflict.rule_notes || conflict.ruleNotes || "",
      metrics: conflict.metrics || {},
      tags: conflict.tags || [],
    });
  }

  return groups;
}

/** rule-growth.js:623-636 */
export function calculateDecisionStats(conflicts: RuleGrowthConflict[]): DecisionStats {
  const llmDecisions: Record<string, number> = {};
  const ruleDecisions: Record<string, number> = {};

  for (const conflict of conflicts) {
    const llmLevel = conflict.llm_context_level || conflict.llmContextLevel || "unknown";
    const ruleLevel = conflict.rule_context_level || conflict.ruleContextLevel || "unknown";

    llmDecisions[llmLevel] = (llmDecisions[llmLevel] || 0) + 1;
    ruleDecisions[ruleLevel] = (ruleDecisions[ruleLevel] || 0) + 1;
  }

  return { llmDecisions, ruleDecisions, total: conflicts.length };
}

/** rule-growth.js:677-693 */
export function calculateTimeDistribution(conflicts: RuleGrowthConflict[]): TimeDistribution {
  const timestamps = conflicts
    .map((conflict) => conflict.timestamp)
    .filter((timestamp): timestamp is string => Boolean(timestamp))
    .sort();

  if (timestamps.length === 0) {
    return { timestamps: [], earliest: null, latest: null };
  }

  return {
    timestamps,
    earliest: timestamps[0],
    latest: timestamps[timestamps.length - 1],
    count: timestamps.length,
  };
}

/** rule-growth.js:722-736 */
export function formatUnmetCondition(condition: UnmetCondition): string {
  const name = condition.name || "";
  const current = condition.currentValue;
  const required = condition.requiredValue;

  if (name.includes("一致性") || name.includes("consistency") || name.includes("percent")) {
    const currentPercent = typeof current === "number" ? Math.round(current * 100) : current;
    const requiredPercent = typeof required === "number" ? Math.round(required * 100) : required;
    return `${String(currentPercent)}%/${String(requiredPercent)}%`;
  }
  if (name.includes("次") || name.includes("count") || name.includes("出现")) {
    return `${String(current)}/${String(required)} 次`;
  }
  return `${String(current)}/${String(required)}`;
}

/** rule-growth.js:738-748 */
export function calculateConditionSeverity(condition: UnmetCondition): "close" | "far" {
  const current = condition.currentValue;
  const required = condition.requiredValue;

  if (typeof current !== "number" || typeof required !== "number" || required === 0) {
    return "far";
  }

  const completionRatio = current / required;
  return completionRatio >= 0.7 ? "close" : "far";
}

/** rule-growth.js:424 —— 只接受数组；旧版对对象会直接抛错，这里返回空数组。 */
export function getUnmetConditions(hint: RuleGrowthHint): UnmetCondition[] {
  const value = hint.unmetConditions || hint.unmet_conditions;
  return Array.isArray(value) ? value : [];
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export { formatLanguageLabel };
