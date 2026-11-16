import type { CSSProperties } from "react";

import { Icon } from "../../components/Icon";
import type { ApplicableRule } from "./types";

export function ApplicableEmpty({ style }: { style?: CSSProperties }) {
  return (
    <div className="empty-state" id="rg-applicable-empty" style={{ flexDirection: "column", padding: "2rem", ...style }}>
      <p style={{ color: "var(--text-muted)" }}>暂无可应用规则</p>
      <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
        需要满足：5+ 次出现、90%+ 一致性、2+ 标签、2+ 文件
      </p>
    </div>
  );
}

/** rule-growth.js:208-242 */
export function ApplicableRuleCard({ rule, onApply }: { rule: ApplicableRule; onApply: (ruleId: string) => void }) {
  const tags = rule.required_tags || [];
  const ruleId = rule.rule_id ?? "";

  return (
    <div className="applicable-rule-card" data-rule-id={ruleId}>
      <div className="rule-header">
        <span className="rule-language">{rule.language ?? ""}</span>
        <span className="rule-tags">
          {tags.map((tag, index) => (
            <span className="tag-badge" key={`${tag}-${index}`}>
              {tag}
            </span>
          ))}
        </span>
      </div>
      <div className="rule-body">
        <div className="rule-suggestion">
          <Icon name="zap" plain />
          建议上下文级别: <strong>{rule.suggested_context_level ?? ""}</strong>
        </div>
        <div className="rule-stats">
          <span title="样本数量">{rule.sample_count} 次</span>
          <span title="一致性">{Math.round(Number(rule.consistency) * 100)}% 一致</span>
          <span title="不同文件数">{rule.unique_files} 文件</span>
        </div>
      </div>
      <div className="rule-warning">
        <Icon name="alert-triangle" plain />
        <span>此规则将全局生效，影响所有匹配的代码变更</span>
      </div>
      <div className="rule-actions">
        <button className="btn-primary btn-small" type="button" onClick={() => onApply(ruleId)}>
          <Icon name="check" plain />
          确认并应用
        </button>
      </div>
    </div>
  );
}

type ApplicableRulesProps = {
  rules: ApplicableRule[];
  error: string | null;
  onApply: (ruleId: string) => void;
};

/**
 * rule-growth.js:118-127 + :143-148。
 * 失败时旧版直接把 #rg-applicable-content 整体替换为 error-text（空态与列表一起消失）。
 */
export function ApplicableRules({ rules, error, onApply }: ApplicableRulesProps) {
  if (error) {
    return <div className="error-text">加载失败: {error}</div>;
  }

  const hasRules = rules.length > 0;

  return (
    <>
      <ApplicableEmpty style={hasRules ? { display: "none" } : undefined} />
      <div
        id="rg-applicable-list"
        className="applicable-rules-list"
        style={{ display: hasRules ? "block" : "none" }}
      >
        {rules.map((rule, index) => (
          <ApplicableRuleCard rule={rule} onApply={onApply} key={`${rule.rule_id ?? "rule"}-${index}`} />
        ))}
      </div>
    </>
  );
}
