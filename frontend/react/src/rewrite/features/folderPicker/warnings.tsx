import { Icon } from "../../components/Icon";
import { escapeHtml } from "../../lib/html";

function folderNameFromPath(path: string): string {
  return path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || path;
}

/**
 * 1:1 复刻 legacy/ui_v1/static/modules/state.js:305-362 的“非 Git 仓库”内容。
 * showConfirmDialog 以 innerHTML 消费该字符串，因此这里只转义文件夹名。
 */
export function buildNotGitRepoWarning(path: string): string {
  const folderName = folderNameFromPath(path);

  return `
        <div style="padding: 0.25rem 0;">
            <div style="display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.875rem; background: var(--bg-secondary, #f8f9fa); border-radius: 6px; border-left: 3px solid var(--warning, #e6a23c); margin-bottom: 1rem;">
                <svg class="icon" style="width: 20px; height: 20px; flex-shrink: 0; margin-top: 1px; color: var(--warning, #e6a23c);"><use href="#icon-alert-triangle"></use></svg>
                <div style="flex: 1;">
                    <div style="font-size: 0.9rem; color: var(--text-primary, #303133); font-weight: 500; margin-bottom: 0.25rem;">
                        所选目录不是 Git 仓库
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary, #606266); word-break: break-all;">
                        ${escapeHtml(folderName)}
                    </div>
                </div>
            </div>
            
            <p style="margin: 0 0 0.75rem 0; color: var(--text-secondary, #606266); line-height: 1.5; font-size: 0.875rem;">
                本系统依赖 Git 来分析代码变更。继续选择此目录将导致以下功能不可用：
            </p>
            
            <ul style="margin: 0 0 1rem 0; padding-left: 1.5rem; color: var(--text-secondary, #606266); font-size: 0.85rem; line-height: 1.7;">
                <li>代码变更分析（Diff 分析）</li>
                <li>提交历史查看</li>
                <li>基于变更的智能代码审查</li>
            </ul>
            
            <p style="margin: 0; font-size: 0.8rem; color: var(--text-placeholder, #909399);">
                建议选择一个已初始化 Git 的项目目录。
            </p>
        </div>
    `;
}

type GitSubdirWarningDialogProps = {
  path: string;
  gitRoot: string;
  onCancel: () => void;
  onContinue: () => void;
  onUseRoot: () => void;
};

/**
 * 1:1 复刻 legacy/ui_v1/static/modules/state.js:373-477 的自定义三按钮弹窗。
 * 结构、内联样式与文案均与旧版保持一致；点击遮罩等同取消。
 */
export function GitSubdirWarningDialog({
  path,
  gitRoot,
  onCancel,
  onContinue,
  onUseRoot,
}: GitSubdirWarningDialogProps) {
  const folderName = folderNameFromPath(path);
  const rootFolderName = folderNameFromPath(gitRoot);

  return (
    <div
      id="confirmDialog"
      className="modal-overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div className="modal-container confirm-dialog-container" style={{ maxWidth: 440 }}>
        <div className="modal-header">
          <h3>选择了子目录</h3>
          <button
            type="button"
            className="icon-btn modal-close-btn"
            id="subdirDialogCloseBtn"
            onClick={onCancel}
          >
            <Icon name="x" plain />
          </button>
        </div>
        <div className="modal-body">
          <div style={{ padding: "0.25rem 0" }}>
            <div
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "0.75rem",
                padding: "0.75rem",
                background: "var(--bg-secondary, #f8f9fa)",
                borderRadius: 6,
                borderLeft: "3px solid var(--text-secondary, #909399)",
                marginBottom: "0.875rem",
              }}
            >
              <svg
                className="icon"
                style={{
                  width: 18,
                  height: 18,
                  flexShrink: 0,
                  marginTop: 2,
                  color: "var(--text-secondary, #909399)",
                }}
              >
                <use href="#icon-folder" />
              </svg>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--text-placeholder, #909399)",
                    marginBottom: "0.125rem",
                  }}
                >
                  当前选择
                </div>
                <div
                  style={{
                    fontSize: "0.9rem",
                    color: "var(--text-primary, #303133)",
                    fontWeight: 500,
                    wordBreak: "break-all",
                  }}
                >
                  {folderName}
                </div>
              </div>
            </div>

            <p
              style={{
                margin: "0 0 0.75rem 0",
                color: "var(--text-secondary, #606266)",
                lineHeight: 1.5,
                fontSize: "0.875rem",
              }}
            >
              {"您选择的是 Git 仓库的"}
              <strong style={{ color: "var(--warning, #e6a23c)" }}>子目录</strong>
              {"，而不是项目根目录。使用子目录可能导致："}
            </p>

            <ul
              style={{
                margin: "0 0 0.875rem 0",
                paddingLeft: "1.5rem",
                color: "var(--text-secondary, #606266)",
                fontSize: "0.85rem",
                lineHeight: 1.6,
              }}
            >
              <li>部分代码变更无法检测</li>
              <li>提交历史不完整</li>
              <li>项目结构分析不准确</li>
            </ul>

            <div
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "0.75rem",
                padding: "0.75rem",
                background: "var(--bg-secondary, #f8f9fa)",
                borderRadius: 6,
                borderLeft: "3px solid var(--primary, #409eff)",
              }}
            >
              <svg
                className="icon"
                style={{
                  width: 18,
                  height: 18,
                  flexShrink: 0,
                  marginTop: 2,
                  color: "var(--primary, #409eff)",
                }}
              >
                <use href="#icon-folder" />
              </svg>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--primary, #409eff)",
                    marginBottom: "0.125rem",
                  }}
                >
                  建议选择项目根目录
                </div>
                <div
                  style={{
                    fontSize: "0.9rem",
                    color: "var(--text-primary, #303133)",
                    fontWeight: 500,
                    wordBreak: "break-all",
                  }}
                >
                  {rootFolderName}
                </div>
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--text-placeholder, #909399)",
                    marginTop: "0.25rem",
                    wordBreak: "break-all",
                  }}
                >
                  {gitRoot}
                </div>
              </div>
            </div>
          </div>
        </div>
        <div
          className="modal-footer"
          style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}
        >
          <button
            type="button"
            className="btn-secondary"
            id="subdirDialogCancelBtn"
            style={{ flex: 1, minWidth: 70 }}
            onClick={onCancel}
          >
            取消
          </button>
          <button
            type="button"
            className="btn-secondary"
            id="subdirDialogContinueBtn"
            style={{ flex: 1, minWidth: 90 }}
            onClick={onContinue}
          >
            仍用子目录
          </button>
          <button
            type="button"
            className="btn-primary"
            id="subdirDialogUseRootBtn"
            style={{ flex: 1.2, minWidth: 100 }}
            onClick={onUseRoot}
          >
            使用根目录
          </button>
        </div>
      </div>
    </div>
  );
}
