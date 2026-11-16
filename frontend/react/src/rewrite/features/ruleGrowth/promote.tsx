import { promoteHint } from "../../lib/api";
import { showConfirmDialog } from "../../lib/dialogs";
import { escapeHtml } from "../../lib/html";
import { showToast } from "../../lib/toast";
import { errorMessage } from "./helpers";
import type { RuleGrowthHint } from "./types";

/**
 * 提升弹窗的 content HTML（rule-growth.js:838-877）。
 */
export function buildPromoteHintDialogContent(hint: RuleGrowthHint): string {
  const tagsHtml = (hint.tags || [])
    .map((tag) => `<span class="tag-badge">${escapeHtml(tag)}</span>`)
    .join(" ");

  const consistencyPercent = Math.round((hint.consistency || 0) * 100);

  return `
    <div class="promote-hint-dialog">
      <div class="dialog-section">
        <h4>规则详情</h4>
        <div class="rule-detail-grid">
          <div class="detail-row">
            <span class="detail-label">语言:</span>
            <span class="detail-value">${escapeHtml(hint.language || "")}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">标签:</span>
            <span class="detail-value">${tagsHtml || "无"}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">建议上下文级别:</span>
            <span class="detail-value">${escapeHtml(hint.suggested_context_level || hint.suggestedContextLevel || "")}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">样本数量:</span>
            <span class="detail-value">${hint.sample_count || hint.sampleCount || 0} 次</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">一致性:</span>
            <span class="detail-value">${consistencyPercent}%</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">涉及文件:</span>
            <span class="detail-value">${hint.unique_files || hint.uniqueFiles || 0} 个</span>
          </div>
        </div>
      </div>
      <div class="dialog-section warning-section">
        <svg class="icon"><use href="#icon-alert-triangle"></use></svg>
        <div class="warning-text">
          <strong>注意:</strong> 此提示未满足自动应用条件。手动提升后，规则将应用到全局配置。
          <div class="reason-detail">${escapeHtml(hint.reason || "")}</div>
        </div>
      </div>
    </div>
  `;
}

/**
 * rule-growth.js:822-886。
 * 保留 hintData 可为 JSON 字符串的旧签名；解析失败 toast 文案与旧版一致。
 */
export function showPromoteHintDialog(
  hintData: RuleGrowthHint | string,
  onConfirm: (hint: RuleGrowthHint) => void
): void {
  let hint: RuleGrowthHint;
  try {
    hint = typeof hintData === "string" ? (JSON.parse(hintData) as RuleGrowthHint) : hintData;
  } catch (error) {
    console.error("Failed to parse hint data:", error);
    showToast("无法解析提示数据", "error");
    return;
  }

  showConfirmDialog({
    title: "提升为规则",
    content: buildPromoteHintDialogContent(hint),
    confirmText: "确认提升",
    cancelText: "取消",
    onConfirm: () => onConfirm(hint),
  });
}

/** rule-growth.js:972-1015 */
export async function promoteHintToRule(hint: RuleGrowthHint, reload: () => Promise<void>): Promise<void> {
  try {
    const fallbackConflict = (hint.conflicts && hint.conflicts[0]) || null;
    const language = hint.language || (fallbackConflict && fallbackConflict.language) || "unknown";
    const tags = Array.isArray(hint.tags) ? hint.tags : (fallbackConflict && fallbackConflict.tags) || [];

    const data = await promoteHint({
      language,
      tags,
      suggested_context_level: hint.suggested_context_level || hint.suggestedContextLevel,
      sample_count: hint.sample_count || hint.sampleCount,
      consistency: hint.consistency,
      conflict_type: hint.conflict_type || hint.conflictType,
    });

    if (data?.error) {
      throw new Error(String(data.error));
    }

    showToast("提示已成功提升为规则", "success");
    await reload();
  } catch (error) {
    console.error("Promote hint error:", error);
    showToast("提升失败: " + errorMessage(error), "error");
  }
}
