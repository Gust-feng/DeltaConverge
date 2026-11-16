import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "../../components/Icon";
import { formatLanguageLabel, formatTimestamp, truncateTextGlobal } from "../../lib/html";
import {
  calculateConditionSeverity,
  calculateDecisionStats,
  calculateTimeDistribution,
  formatUnmetCondition,
  getConflictTypeLabel,
  getHintLanguageId,
  getRuleGrowthTypeLabel,
  getUnmetConditions,
  groupFilesByDirectory,
  groupHintsByLanguage,
} from "./helpers";
import type { DecisionStats, GroupedFile, RuleGrowthHint, TimeDistribution } from "./types";

type PromoteHandler = (hint: RuleGrowthHint) => void;

/** rule-growth.js:466-470 */
function CollapsibleInfoBlock({
  icon,
  title,
  badge,
  badgeClassName,
  children,
}: {
  icon: string;
  title: string;
  badge?: ReactNode;
  badgeClassName?: string;
  children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(true);

  return (
    <div
      className={`collapsible-info-block${collapsed ? " collapsed" : ""}`}
      onClick={() => setCollapsed((value) => !value)}
    >
      <div className="block-header">
        <Icon name={icon} plain className="block-icon" />
        <span className="block-title">{title}</span>
        {badge !== undefined && (
          <span className={`block-badge${badgeClassName ? ` ${badgeClassName}` : ""}`}>{badge}</span>
        )}
        <Icon name="chevron-down" plain className="block-chevron" />
      </div>
      <div className="block-content">
        <div className="block-content-inner">{children}</div>
      </div>
    </div>
  );
}

/** rule-growth.js:570-617 */
function GroupedFileList({ groupedFiles }: { groupedFiles: Record<string, GroupedFile[]> }) {
  const directories = Object.keys(groupedFiles).sort();

  if (directories.length === 0) {
    return (
      <div className="block-empty-state">
        <span className="text-muted">无文件数据</span>
      </div>
    );
  }

  return (
    <div className="grouped-file-list">
      {directories.map((directory) => {
        const files = groupedFiles[directory];
        return (
          <div className="file-group" key={directory}>
            <div className="file-group-header">
              <Icon name="folder" plain className="icon-small" />
              <span className="file-group-name">{directory}</span>
              <span className="file-group-count">{files.length}</span>
            </div>
            <div className="file-group-items">
              {files.map((file, index) => {
                const metrics = file.metrics || {};
                return (
                  <div className="file-item" key={`${file.filePath}-${index}`}>
                    <div className="file-head">
                      <span className="file-name" title={file.filePath}>
                        {file.fileName}
                      </span>
                      {file.conflictType ? (
                        <span className="file-conflict-type">{getConflictTypeLabel(file.conflictType)}</span>
                      ) : null}
                      {file.language ? (
                        <span className="file-lang-badge">{formatLanguageLabel(file.language)}</span>
                      ) : null}
                    </div>
                    <div className="file-meta-row">
                      {file.llmContext ? (
                        <span className="tag-badge tag-muted">LLM: {file.llmContext}</span>
                      ) : null}
                      {file.ruleContext ? <span className="tag-badge">规则: {file.ruleContext}</span> : null}
                      {file.ruleConfidence !== undefined && file.ruleConfidence !== null ? (
                        <span className="tag-badge tag-muted">
                          置信 {Math.round(Number(file.ruleConfidence) * 100)}%
                        </span>
                      ) : null}
                      {file.timestamp ? <span className="file-time">{formatTimestamp(file.timestamp)}</span> : null}
                    </div>
                    {metrics.added_lines || metrics.removed_lines || metrics.hunk_count ? (
                      <div className="file-metrics">
                        +{metrics.added_lines || 0} / -{metrics.removed_lines || 0} · 块 {metrics.hunk_count || 0}
                      </div>
                    ) : null}
                    {file.llmReason ? (
                      <div className="file-reason" title={file.llmReason}>
                        {truncateTextGlobal(file.llmReason, 120)}
                      </div>
                    ) : null}
                    {file.ruleNotes ? (
                      <div className="file-notes" title={file.ruleNotes}>
                        规则提示: {truncateTextGlobal(file.ruleNotes, 120)}
                      </div>
                    ) : null}
                    {file.tags && file.tags.length ? (
                      <div className="file-tags">
                        {file.tags.slice(0, 4).map((tag, tagIndex) => (
                          <span className="tag-badge tag-muted" key={`${tag}-${tagIndex}`}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** rule-growth.js:321-350 */
function ConflictFilesBlock({ hint }: { hint: RuleGrowthHint }) {
  const conflicts = hint.conflicts || [];
  const fileCount = conflicts.length || hint.unique_files || 0;

  return (
    <CollapsibleInfoBlock icon="folder" title="冲突文件" badge={fileCount}>
      {conflicts.length > 0 ? (
        <GroupedFileList groupedFiles={groupFilesByDirectory(conflicts)} />
      ) : (
        <div className="block-empty-state">
          <span className="text-muted">共 {fileCount} 个文件涉及此模式</span>
        </div>
      )}
    </CollapsibleInfoBlock>
  );
}

/** rule-growth.js:638-675 */
function DecisionStatsView({ stats }: { stats: DecisionStats }) {
  return (
    <div className="decision-stats">
      <div className="decision-section">
        <h5>LLM 决策分布</h5>
        <div className="decision-bars">
          {Object.entries(stats.llmDecisions).map(([level, count]) => {
            const percent = Math.round((count / stats.total) * 100);
            return (
              <div className="decision-bar-item" key={level}>
                <span className="bar-label">{level}</span>
                <div className="bar-container">
                  <div className="bar-fill" style={{ width: `${percent}%` }} />
                </div>
                <span className="bar-value">
                  {count} ({percent}%)
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="decision-section">
        <h5>规则决策分布</h5>
        <div className="decision-bars">
          {Object.entries(stats.ruleDecisions).map(([level, count]) => {
            const percent = Math.round((count / stats.total) * 100);
            return (
              <div className="decision-bar-item" key={level}>
                <span className="bar-label">{level}</span>
                <div className="bar-container">
                  <div className="bar-fill bar-fill-rule" style={{ width: `${percent}%` }} />
                </div>
                <span className="bar-value">
                  {count} ({percent}%)
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** rule-growth.js:352-392 */
function DecisionCompareBlock({ hint }: { hint: RuleGrowthHint }) {
  const conflicts = hint.conflicts || [];

  return (
    <CollapsibleInfoBlock icon="review" title="决策对比">
      {conflicts.length > 0 ? (
        <DecisionStatsView stats={calculateDecisionStats(conflicts)} />
      ) : (
        <div className="decision-compare-summary">
          <div className="decision-item">
            <span className="decision-label">建议上下文级别:</span>
            <span className="decision-value">{hint.suggested_context_level || ""}</span>
          </div>
          <div className="decision-item">
            <span className="decision-label">一致性:</span>
            <span className="decision-value">{Math.round((hint.consistency || 0) * 100)}%</span>
          </div>
          <div className="decision-item">
            <span className="decision-label">冲突类型:</span>
            <span className="decision-value">{getRuleGrowthTypeLabel(hint.conflict_type || "")}</span>
          </div>
        </div>
      )}
    </CollapsibleInfoBlock>
  );
}

/** rule-growth.js:695-716 */
function TimeStatsView({ stats }: { stats: TimeDistribution }) {
  if (!stats.earliest) {
    return (
      <div className="block-empty-state">
        <span className="text-muted">无时间数据</span>
      </div>
    );
  }

  return (
    <div className="time-stats">
      <div className="time-stat-item">
        <span className="time-label">最早记录:</span>
        <span className="time-value">{formatTimestamp(stats.earliest)}</span>
      </div>
      <div className="time-stat-item">
        <span className="time-label">最近记录:</span>
        <span className="time-value">{formatTimestamp(stats.latest)}</span>
      </div>
      <div className="time-stat-item">
        <span className="time-label">记录总数:</span>
        <span className="time-value">{stats.count}</span>
      </div>
    </div>
  );
}

/** rule-growth.js:394-421 */
function TimeDistributionBlock({ hint }: { hint: RuleGrowthHint }) {
  const conflicts = hint.conflicts || [];

  return (
    <CollapsibleInfoBlock icon="clock" title="时间分布">
      {conflicts.length > 0 ? (
        <TimeStatsView stats={calculateTimeDistribution(conflicts)} />
      ) : (
        <div className="block-empty-state">
          <span className="text-muted">详细时间分布需要加载完整冲突数据</span>
        </div>
      )}
    </CollapsibleInfoBlock>
  );
}

/** rule-growth.js:423-460 */
function UnmetConditionsBlock({ hint }: { hint: RuleGrowthHint }) {
  const unmetConditions = getUnmetConditions(hint);

  if (unmetConditions.length === 0) {
    return null;
  }

  return (
    <CollapsibleInfoBlock
      icon="alert-triangle"
      title="未满足条件"
      badge={unmetConditions.length}
      badgeClassName="severity-indicator"
    >
      <div className="unmet-conditions-list">
        {unmetConditions.map((condition, index) => {
          const severity = calculateConditionSeverity(condition);
          const formattedValue = formatUnmetCondition(condition);
          const conditionName = condition.name || condition.condition_name || "未知条件";

          return (
            <div className={`unmet-condition-item severity-${severity}`} key={`${conditionName}-${index}`}>
              <span className="condition-name">{conditionName}</span>
              <span className="condition-values">{formattedValue}</span>
            </div>
          );
        })}
      </div>
    </CollapsibleInfoBlock>
  );
}

/** rule-growth.js:248-315 */
function ReferenceHintCard({
  hint,
  onPromote,
  promoting,
}: {
  hint: RuleGrowthHint;
  onPromote: PromoteHandler;
  promoting: boolean;
}) {
  const tags = hint.tags || [];
  const consistencyPercent = Math.round((hint.consistency || 0) * 100);

  return (
    <div className="reference-hint-card" data-hint-id={hint.hintId ?? ""}>
      <div className="hint-summary">
        <div className="hint-summary-row">
          <span className="hint-language-badge">{hint.language ?? ""}</span>
          <span className="hint-tags">
            {tags.map((tag, index) => (
              <span className="tag-badge tag-muted" key={`${tag}-${index}`}>
                {tag}
              </span>
            ))}
          </span>
        </div>
        <div className="hint-summary-row">
          <span className="hint-suggestion-text">
            <Icon name="zap" plain className="icon-small" />
            建议: {hint.suggested_context_level ?? ""}
          </span>
        </div>
        <div className="hint-summary-row hint-metrics">
          <span className="hint-metric">
            <span className="metric-value">{hint.sample_count}</span> 次出现
          </span>
          <span className="hint-metric">
            <span className="metric-value">{consistencyPercent}%</span> 一致性
          </span>
          <span className="hint-metric">
            <span className="metric-value">{hint.unique_files || 0}</span> 文件
          </span>
        </div>
      </div>

      <div className="hint-info-blocks">
        <ConflictFilesBlock hint={hint} />
        <DecisionCompareBlock hint={hint} />
        <TimeDistributionBlock hint={hint} />
        <UnmetConditionsBlock hint={hint} />
      </div>

      <div className="hint-reason-section">
        <Icon name="alert-triangle" plain className="icon-small" />
        <span className="reason-text">{hint.reason || ""}</span>
      </div>

      <div className="hint-actions">
        <button
          className={`btn-secondary btn-small hint-promote-btn${promoting ? " loading" : ""}`}
          type="button"
          title="手动提升为规则"
          onClick={() => onPromote(hint)}
        >
          <Icon name="trending-up" plain />
          提升为规则
        </button>
      </div>
    </div>
  );
}

type ReferenceHintsProps = {
  hints: RuleGrowthHint[];
  onPromote: PromoteHandler;
  promotingHintId: string | null;
};

/**
 * rule-growth.js:538-568。
 * 语言组默认折叠；数据重新加载时旧版通过 innerHTML 重建，同样恢复全折叠。
 */
export function ReferenceHints({ hints, onPromote, promotingHintId }: ReferenceHintsProps) {
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setExpandedGroups({});
  }, [hints]);

  if (!hints || hints.length === 0) {
    return (
      <div className="empty-state">
        <span className="text-muted">暂无参考提示</span>
      </div>
    );
  }

  const groupedHints = groupHintsByLanguage(hints);
  const languages = Object.keys(groupedHints).sort();

  return (
    <div className="language-grouped-hints">
      {languages.map((language, groupIndex) => {
        const group = groupedHints[language];
        const languageId = getHintLanguageId(language);
        const expanded = Boolean(expandedGroups[languageId]);

        return (
          <div
            className={`language-group${expanded ? "" : " collapsed"}`}
            data-language={language}
            id={languageId}
            key={`${languageId}-${groupIndex}`}
          >
            <div
              className="language-group-header"
              onClick={() =>
                setExpandedGroups((current) => ({ ...current, [languageId]: !current[languageId] }))
              }
            >
              <Icon name="chevron-down" plain className="language-chevron" />
              <span className="language-name">{language}</span>
              <span className="language-count-badge">{group.count}</span>
            </div>
            <div className="language-group-content">
              {group.hints.map((hint, hintIndex) => (
                <ReferenceHintCard
                  hint={hint}
                  onPromote={onPromote}
                  promoting={promotingHintId !== null && promotingHintId === (hint.hintId ?? "")}
                  key={hint.hintId ?? `${languageId}-${hintIndex}`}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
