/**
 * 1:1 移植 legacy/ui_v1/static/modules/diff.js 的
 * updateDiffStatusHint(:93-154) 与 updateReviewModeBadge(:156-202)。
 *
 * 文本与配色必须逐字/逐色一致；hint 一旦更新就把 display 设为 flex
 * （初始由 JSX 渲染为 none）。
 */

const HINT_GRAY_BG = "rgba(156, 163, 175, 0.1)";
const HINT_GRAY_BORDER = "1px solid rgba(156, 163, 175, 0.2)";

export function updateDiffStatusHint(mode: string, fileCount: number, hasSelectedCommitFrom: boolean): void {
  const hintBox = document.getElementById("diff-status-hint");
  const hintText = document.getElementById("diff-status-text");
  if (!hintBox || !hintText) return;

  hintBox.style.display = "flex";

  let msg = "";

  // 特殊处理：commit模式但未选择提交范围
  if (mode === "commit" && !hasSelectedCommitFrom) {
    msg = "请选择历史提交范围";
    hintBox.style.background = HINT_GRAY_BG;
    hintBox.style.border = HINT_GRAY_BORDER;
    hintText.textContent = msg;
    updateReviewModeBadge(mode);
    return;
  }

  if (fileCount === 0) {
    if (mode === "commit") {
      msg = "所选提交范围无文件变更";
    } else if (mode === "pr") {
      msg = "当前仓库无 PR 变更";
    } else if (mode === "staged") {
      msg = "暂存区无文件变更";
    } else if (mode === "working") {
      msg = "工作区无未暂存变更";
    } else {
      msg = "当前无变更，无需审查";
    }
    hintBox.style.background = HINT_GRAY_BG;
    hintBox.style.border = HINT_GRAY_BORDER;
  } else {
    if (mode === "staged") {
      msg = `暂存区 ${fileCount} 个文件，建议审查后提交`;
      hintBox.style.background = "rgba(16, 185, 129, 0.1)";
      hintBox.style.border = "1px solid rgba(16, 185, 129, 0.2)";
    } else if (mode === "working") {
      msg = `工作区 ${fileCount} 个文件未暂存`;
      hintBox.style.background = "rgba(245, 158, 11, 0.1)";
      hintBox.style.border = "1px solid rgba(245, 158, 11, 0.2)";
    } else if (mode === "commit") {
      msg = `历史提交包含 ${fileCount} 个文件变更`;
      hintBox.style.background = "rgba(59, 130, 246, 0.1)";
      hintBox.style.border = "1px solid rgba(59, 130, 246, 0.2)";
    } else if (mode === "pr") {
      msg = `PR 包含 ${fileCount} 个文件变更`;
      hintBox.style.background = "rgba(168, 85, 247, 0.1)";
      hintBox.style.border = "1px solid rgba(168, 85, 247, 0.2)";
    } else {
      msg = `检测到 ${fileCount} 个文件变更`;
      hintBox.style.background = "rgba(59, 130, 246, 0.1)";
      hintBox.style.border = "1px solid rgba(59, 130, 246, 0.2)";
    }
  }

  hintText.textContent = msg;

  // Also update the header badge
  updateReviewModeBadge(mode);
}

export function updateReviewModeBadge(mode: string): void {
  const dropdown = document.getElementById("headerModeDropdown");
  const trigger = document.getElementById("headerModeTrigger");
  const textSpan = document.getElementById("headerModeText");

  if (dropdown && trigger && textSpan) {
    dropdown.style.display = "inline-flex";

    const modeNames: Record<string, string> = {
      auto: "自动检测",
      working: "工作区模式",
      staged: "暂存区模式",
      pr: "PR 模式",
      commit: "历史提交模式",
    };
    const text = modeNames[mode] || "自动检测";
    textSpan.textContent = text;

    // Reset classes
    trigger.className = "dropdown-trigger mode-badge";

    // Add specific mode class
    if (mode === "staged") {
      trigger.classList.add("mode-staged");
    } else if (mode === "working") {
      trigger.classList.add("mode-working");
    } else if (mode === "commit") {
      trigger.classList.add("mode-commit");
    } else if (mode === "pr") {
      trigger.classList.add("mode-pr");
    } else if (mode === "loading") {
      trigger.classList.add("mode-loading");
      textSpan.textContent = "检测中...";
    } else {
      trigger.classList.add("mode-default");
    }

    // Highlight selected item in menu
    const menu = document.getElementById("headerModeMenu");
    if (menu) {
      menu.querySelectorAll(".dropdown-item").forEach((item) => {
        const element = item as HTMLElement;
        if (element.dataset.mode === mode) element.classList.add("selected");
        else element.classList.remove("selected");
      });
    }
  }
}
