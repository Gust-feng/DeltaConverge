import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";

import { applyRule as applyRuleApi, cleanupRuleGrowth } from "../lib/api";
import { closeHelpDialog, showHelpDialog } from "../lib/dialogs";
import { showToast } from "../lib/toast";
import { ApplicableRules } from "../features/ruleGrowth/ApplicableRules";
import { HINTS_HELP_CONTENT } from "../features/ruleGrowth/helpContent";
import { HintsHelpButton } from "../features/ruleGrowth/HintsHelpButton";
import { errorMessage } from "../features/ruleGrowth/helpers";
import { promoteHintToRule, showPromoteHintDialog } from "../features/ruleGrowth/promote";
import { ReferenceHints } from "../features/ruleGrowth/ReferenceHints";
import { SummaryContent } from "../features/ruleGrowth/SummaryContent";
import type { RuleGrowthHint } from "../features/ruleGrowth/types";
import { useRuleGrowthData } from "../features/ruleGrowth/useRuleGrowthData";

export function RuleGrowthPage({ active }: { active: boolean }) {
  const {
    summary,
    applicableRules,
    referenceHints,
    suggestionsError,
    applicableCount,
    hintsCount,
    loadAll,
  } = useRuleGrowthData();

  const [promotingHintId, setPromotingHintId] = useState<string | null>(null);
  const wasActiveRef = useRef(false);

  // 旧版 switchPage('rule-growth') 每次进入都会重新加载；React 中只在 false -> true 时触发。
  useEffect(() => {
    if (active && !wasActiveRef.current) {
      void loadAll();
    }
    wasActiveRef.current = active;
  }, [active, loadAll]);

  useEffect(() => {
    const handler = (event: Event) => {
      if ((event as CustomEvent).detail === "rule-growth") void loadAll();
    };
    window.addEventListener("dc:reload-page", handler);
    return () => window.removeEventListener("dc:reload-page", handler);
  }, [loadAll]);

  async function handleApplyRule(ruleId: string) {
    if (!window.confirm("确定要应用此规则吗？此操作将影响全局规则配置。")) {
      return;
    }

    try {
      const data = await applyRuleApi(ruleId);
      if (data?.error) {
        throw new Error(String(data.error));
      }

      showToast("规则已成功应用", "success");
      await loadAll();
    } catch (error) {
      console.error("Apply rule error:", error);
      showToast("应用规则失败: " + errorMessage(error), "error");
    }
  }

  async function handleCleanup() {
    if (!window.confirm("确定要清理 30 天前的冲突记录吗？")) {
      return;
    }

    try {
      const data = await cleanupRuleGrowth(30);
      if (data?.error) {
        throw new Error(String(data.error));
      }

      const deleted = data.deleted_count || 0;
      const remaining = data.remaining_count || 0;

      showToast(`已清理 ${deleted} 条记录，剩余 ${remaining} 条`, "success");
      await loadAll();
    } catch (error) {
      console.error("Rule growth cleanup error:", error);
      showToast("清理失败: " + errorMessage(error), "error");
    }
  }

  function handlePromoteHint(hint: RuleGrowthHint) {
    showPromoteHintDialog(hint, (targetHint) => {
      setPromotingHintId(targetHint.hintId ?? null);
      void (async () => {
        try {
          await promoteHintToRule(targetHint, loadAll);
        } finally {
          setPromotingHintId(null);
        }
      })();
    });
  }

  function openHintsHelpDialog() {
    showHelpDialog("参考提示", HINTS_HELP_CONTENT);

    // 共享 showHelpDialog 的遮罩委托会跳过 .dialog-box 内的所有点击，
    // 导致旧版可用的关闭 X / “知了” 失效。这里在页面侧恢复旧版行为，不动共享层。
    const overlay = document.getElementById("help-dialog-overlay");
    overlay?.querySelectorAll<HTMLElement>(".dialog-close-btn, .dialog-footer button").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        closeHelpDialog();
      });
    });
  }

  function handleHelpClick(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    openHintsHelpDialog();
  }

  const hasHints = referenceHints.length > 0;

  return (
    <div id="page-rule-growth" className="page-view" style={{ display: active ? "block" : "none" }}>
      <div className="page-header">
        <h2>规则优化</h2>
        <span className="page-subtitle">规则与 LLM 决策冲突分析</span>
        <div className="header-actions" style={{ marginLeft: "auto" }}>
          <button className="btn-secondary" type="button" onClick={handleCleanup}>
            清理旧记录
          </button>
        </div>
      </div>

      <div className="rule-growth-content">
        <div className="card">
          <div className="card-header">
            <h3>冲突统计</h3>
          </div>
          <div className="card-body" id="rg-summary-content">
            <SummaryContent state={summary} />
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3>
              <svg className="icon" style={{ marginRight: "0.5rem" }}>
                <use href="#icon-rule" />
              </svg>
              可应用规则
            </h3>
            <span id="rg-applicable-badge" className="badge success">
              {applicableCount}
            </span>
          </div>
          <div className="card-body" id="rg-applicable-content">
            <ApplicableRules rules={applicableRules} error={suggestionsError} onApply={handleApplyRule} />
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3 style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <svg className="icon">
                <use href="#icon-lightbulb" />
              </svg>
              参考提示
              <HintsHelpButton onClick={handleHelpClick} />
            </h3>
            <span id="rg-hints-badge" className="badge">
              {hintsCount}
            </span>
          </div>
          <div className="card-body" id="rg-hints-content">
            <div
              className="empty-state"
              id="rg-hints-empty"
              style={{
                flexDirection: "column",
                padding: "2rem",
                ...(hasHints ? { display: "none" } : {}),
              }}
            >
              <p style={{ color: "var(--text-muted)" }}>暂无参考提示</p>
              <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                不满足自动应用条件的模式将显示在此
              </p>
            </div>
            <div
              id="rg-hints-list"
              className="reference-hints-list"
              style={{ display: hasHints ? "block" : "none" }}
            >
              {hasHints && (
                <ReferenceHints
                  hints={referenceHints}
                  onPromote={handlePromoteHint}
                  promotingHintId={promotingHintId}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
