import { useCallback, useState } from "react";

import { getRuleGrowthSuggestions, getRuleGrowthSummary } from "../../lib/api";
import { showToast } from "../../lib/toast";
import { errorMessage } from "./helpers";
import type { ApplicableRule, RuleGrowthHint, SummaryState } from "./types";

type RuleGrowthData = {
  summary: SummaryState;
  applicableRules: ApplicableRule[];
  referenceHints: RuleGrowthHint[];
  suggestionsError: string | null;
  applicableCount: number;
  hintsCount: number;
  loadAll: () => Promise<void>;
};

function readArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/**
 * 数据流 1:1 对齐 rule-growth.js:17-149：
 * - summary / suggestions 并行加载；
 * - 两个子加载器各自吞掉异常并写入内容区，外层 Promise.all 的 toast 实际不会触发；
 * - 失败时 shell 不清空旧数据，仅把对应内容区替换成 error-text（参考提示区旧版完全不动）。
 */
export function useRuleGrowthData(): RuleGrowthData {
  const [summary, setSummary] = useState<SummaryState>({ status: "initial" });
  const [applicableRules, setApplicableRules] = useState<ApplicableRule[]>([]);
  const [referenceHints, setReferenceHints] = useState<RuleGrowthHint[]>([]);
  const [suggestionsError, setSuggestionsError] = useState<string | null>(null);
  const [applicableCount, setApplicableCount] = useState(0);
  const [hintsCount, setHintsCount] = useState(0);

  const loadSummary = useCallback(async () => {
    try {
      const data = await getRuleGrowthSummary();
      if (data?.error) throw new Error(String(data.error));

      const total = Number(data?.total_conflicts) || 0;

      setSummary((previous) => ({
        status: "ready",
        data: {
          total,
          byType:
            data?.by_type && typeof data.by_type === "object"
              ? (data.by_type as Record<string, number>)
              : {},
          byLanguage:
            data?.by_language && typeof data.by_language === "object"
              ? (data.by_language as Record<string, number>)
              : {},
        },
        // 旧版 total === 0 时 `innerHTML = ''` 会永久移除空态节点；后续再有数据也不会重建它。
        emptyRemoved:
          total === 0 || (previous.status === "ready" && previous.emptyRemoved === true),
      }));
    } catch (error) {
      setSummary({ status: "error", message: errorMessage(error) });
    }
  }, []);

  const loadSuggestions = useCallback(async () => {
    try {
      const data = await getRuleGrowthSuggestions();
      if (data?.error) throw new Error(String(data.error));

      const applicable = readArray<ApplicableRule>(data?.applicable_rules);
      const rawHints = readArray<RuleGrowthHint>(data?.reference_hints);
      const stamp = Date.now();
      const hints = rawHints.map((hint) => ({
        ...hint,
        hintId: `hint-${hint?.language}-${(hint?.tags || []).join("-")}-${stamp}`,
      }));

      setApplicableRules(applicable);
      setReferenceHints(hints);
      setApplicableCount(applicable.length);
      setHintsCount(hints.length);
      // 旧版失败时 `applicableContent.innerHTML = error` 会永久移除空态与列表节点；
      // 即使后续请求成功，成功分支也只更新已脱离 DOM 的旧引用，错误文案会一直保留。
      // 这里保留 suggestionsError，不在此清除。
    } catch (error) {
      setSuggestionsError(errorMessage(error));
    }
  }, []);

  const loadAll = useCallback(async () => {
    try {
      await Promise.all([loadSummary(), loadSuggestions()]);
    } catch (error) {
      showToast("加载规则数据失败: " + errorMessage(error), "error");
    }
  }, [loadSuggestions, loadSummary]);

  return {
    summary,
    applicableRules,
    referenceHints,
    suggestionsError,
    applicableCount,
    hintsCount,
    loadAll,
  };
}
