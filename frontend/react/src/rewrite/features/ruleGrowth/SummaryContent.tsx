import type { CSSProperties } from "react";

import { Icon } from "../../components/Icon";
import { formatLanguageLabel, getRuleGrowthTypeIcon, getRuleGrowthTypeLabel } from "./helpers";
import type { SummaryState } from "./types";

export function SummaryEmpty({ style }: { style?: CSSProperties }) {
  return (
    <div className="empty-state" id="rg-summary-empty" style={{ flexDirection: "column", padding: "2rem", ...style }}>
      <p style={{ color: "var(--text-muted)" }}>暂无冲突记录</p>
      <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
        系统会自动记录规则与 LLM 决策的差异
      </p>
    </div>
  );
}

/**
 * 1:1 复刻 rule-growth.js:29-91。
 *
 * 旧版在 total === 0 时先显示空态，随后 `summaryContent.innerHTML = ''` 把空态一并移除，
 * 因此最终卡片内容为空（不是显示空态）。这里保留该行为。
 */
export function SummaryContent({ state }: { state: SummaryState }) {
  if (state.status === "error") {
    return <div className="error-text">加载失败: {state.message}</div>;
  }

  if (state.status === "initial") {
    return <SummaryEmpty />;
  }

  const { total, byType, byLanguage } = state.data;
  if (total === 0) {
    return null;
  }

  const typeEntries = Object.entries(byType);
  const languageEntries = Object.entries(byLanguage);

  return (
    <>
      {!state.emptyRemoved && <SummaryEmpty style={{ display: "none" }} />}
      <div
        className="stat-total"
        style={{
          textAlign: "center",
          padding: "1rem 0",
          marginBottom: "1rem",
          background: "#f9fafb",
          borderRadius: "8px",
        }}
      >
        <div style={{ fontSize: "2rem", fontWeight: 700, color: "var(--primary)" }}>{total}</div>
        <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>总冲突数</div>
      </div>

      {typeEntries.length > 0 && (
        <div className="stat-section">
          <h4>按冲突类型</h4>
          <div className="stat-list">
            {typeEntries.map(([type, count], index) => (
              <div className="stat-row" key={`${type}-${index}`}>
                <span className="label">
                  <Icon name={getRuleGrowthTypeIcon(type)} plain className="icon-small" />{" "}
                  {getRuleGrowthTypeLabel(type)}
                </span>
                <span className="value">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {languageEntries.length > 0 && (
        <div className="stat-section">
          <h4>按语言</h4>
          <div className="stat-list">
            {languageEntries.map(([language, count], index) => (
              <div className="stat-row" key={`${language}-${index}`}>
                <span className="label">{formatLanguageLabel(language)}</span>
                <span className="value">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
