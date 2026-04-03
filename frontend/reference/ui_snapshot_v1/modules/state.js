/**
 * state.js - 全局状态管理模块
 */

// --- Global State ---
window.currentSessionId = null;
window.currentProjectRoot = null;
window.currentDiffMode = 'auto';
window.currentModelValue = "";  // 将由 loadOptions 自动设置为第一个可用模型
window.availableGroups = [];

const PROJECT_ROOT_STORAGE_KEY = 'selectedProjectRoot';

let projectPrefetchTimerId = null;
let lastPrefetchProjectRoot = null;

function scheduleProjectPrefetch(projectRoot) {
    if (!projectRoot) return;

    // Avoid re-prefetching the same project repeatedly
    if (lastPrefetchProjectRoot === projectRoot) return;

    if (projectPrefetchTimerId) {
        clearTimeout(projectPrefetchTimerId);
    }

    projectPrefetchTimerId = setTimeout(async () => {
        // Ensure user didn't switch projects during debounce
        if (window.currentProjectRoot !== projectRoot) return;
        lastPrefetchProjectRoot = projectRoot;

        // Prefetch data needed by other pages so later navigation is instant.
        // These functions already have their own caching/throttling logic.
        try {
            if (typeof loadDashboardData === 'function') {
                loadDashboardData().catch(() => { });
            }
        } catch (_) { }

        try {
            if (typeof refreshDiffAnalysis === 'function') {
                refreshDiffAnalysis().catch(() => { });
            }
        } catch (_) { }
    }, 150);
}

// 会话状态管理
const SessionState = {
    runningSessionId: null,
    runningUISnapshot: {
        workflowHTML: '',
        monitorHTML: '',
        reportHTML: ''
    },
    isViewingHistory: false,
    pollTimerId: null,
    reviewStreamActive: false
};

// 布局状态常量
const LayoutState = {
    INITIAL: 'initial',
    REVIEWING: 'reviewing',
    COMPLETED: 'completed'
};

let currentLayoutState = LayoutState.INITIAL;

// --- 阶段折叠切换 ---
window.toggleStageSection = function (headerEl) {
    const section = headerEl.closest('.workflow-stage-section');
    if (section) {
        section.classList.toggle('collapsed');
        const sectionId = section.id;
        if (sectionId && typeof UserInteractionState !== 'undefined') {
            UserInteractionState.manualExpandStates.set(sectionId, !section.classList.contains('collapsed'));
        }
    }
};

// --- 会话状态函数 ---
function isReviewRunning() {
    return SessionState.runningSessionId !== null;
}

function getRunningSessionId() {
    return SessionState.runningSessionId;
}

function startReviewTask(sessionId) {
    SessionState.runningSessionId = sessionId;
    SessionState.isViewingHistory = false;
    SessionState.runningUISnapshot = { workflowHTML: '', monitorHTML: '', reportHTML: '' };
    if (typeof stopSessionPolling === 'function') stopSessionPolling();
    if (typeof loadSessions === 'function') loadSessions();
    updateBackgroundTaskIndicator();
}

function endReviewTask() {
    SessionState.runningSessionId = null;
    SessionState.reviewStreamActive = false;
    if (typeof stopSessionPolling === 'function') stopSessionPolling();
    if (typeof loadSessions === 'function') loadSessions();
    updateBackgroundTaskIndicator();
}

function saveRunningUISnapshot() {
    const workflowEntries = document.getElementById('workflowEntries');
    const monitorContent = document.getElementById('monitorContent');
    const reportContainer = document.getElementById('reportContainer');

    SessionState.runningUISnapshot = {
        workflowHTML: workflowEntries ? workflowEntries.innerHTML : '',
        monitorHTML: monitorContent ? monitorContent.innerHTML : '',
        reportHTML: reportContainer ? reportContainer.innerHTML : ''
    };
}

function restoreRunningUISnapshot() {
    const workflowEntries = document.getElementById('workflowEntries');
    const monitorContent = document.getElementById('monitorContent');
    const reportContainer = document.getElementById('reportContainer');

    if (workflowEntries && SessionState.runningUISnapshot.workflowHTML) {
        workflowEntries.innerHTML = SessionState.runningUISnapshot.workflowHTML;
    }
    if (monitorContent && SessionState.runningUISnapshot.monitorHTML) {
        monitorContent.innerHTML = SessionState.runningUISnapshot.monitorHTML;
    }
    if (reportContainer && SessionState.runningUISnapshot.reportHTML) {
        reportContainer.innerHTML = SessionState.runningUISnapshot.reportHTML;
    }
}

function setViewingHistory(isViewing) {
    SessionState.isViewingHistory = isViewing;

    const historyBackBtn = document.getElementById('historyBackBtn');
    const backgroundTaskBtn = document.getElementById('backgroundTaskBtn');

    if (historyBackBtn) {
        historyBackBtn.style.display = isViewing ? 'flex' : 'none';
    }

    updateBackgroundTaskIndicator();
}

function isViewingHistory() {
    return SessionState.isViewingHistory;
}

function updateBackgroundTaskIndicator() {
    const backgroundTaskBtn = document.getElementById('backgroundTaskBtn');
    if (!backgroundTaskBtn) return;

    const runningSessionId = getRunningSessionId();
    const isViewingHistoryMode = isViewingHistory();
    const isCurrentSessionRunning = window.currentSessionId === runningSessionId;

    if (runningSessionId && !isViewingHistoryMode && !isCurrentSessionRunning) {
        backgroundTaskBtn.style.display = 'flex';
    } else {
        backgroundTaskBtn.style.display = 'none';
    }
}

// --- 布局状态函数 ---
function getLayoutState() {
    return currentLayoutState;
}

function setLayoutState(newState) {
    const workbench = document.getElementById('page-review');
    if (!workbench) return;

    const validStates = Object.values(LayoutState);
    if (!validStates.includes(newState)) return;

    currentLayoutState = newState;
    workbench.dataset.layoutState = newState;

    const appContainer = document.querySelector('.app-container');
    if (appContainer) {
        appContainer.dataset.layoutState = newState;
    }
}

// --- Git 仓库检查 ---
// 缓存检查结果，避免重复请求
const gitRepoCheckCache = new Map();
const GIT_CHECK_CACHE_TTL_MS = 30 * 1000; // 30 秒缓存

/**
 * 检查指定路径是否为 Git 仓库（带缓存）
 * @param {string} path - 项目路径
 * @param {Object} options - 选项
 * @param {boolean} options.force - 是否强制刷新缓存
 * @returns {Promise<{isGit: boolean, isRoot: boolean, gitRoot: string|null, error: string|null}>}
 */
async function checkGitRepository(path, options = {}) {
    if (!path) {
        return { isGit: false, isRoot: false, gitRoot: null, error: 'No path provided' };
    }

    const force = !!(options && options.force);
    const now = Date.now();
    const cacheKey = path.toLowerCase().replace(/[\\/]+$/, ''); // 规范化路径

    // 检查缓存
    if (!force) {
        const cached = gitRepoCheckCache.get(cacheKey);
        if (cached && (now - cached.ts) < GIT_CHECK_CACHE_TTL_MS) {
            return cached.result;
        }
    }

    let timeoutId = null;
    try {
        const controller = new AbortController();
        timeoutId = setTimeout(() => controller.abort(), 5000); // 5 秒超时

        // 使用新的轻量级 Git 检测 API
        const res = await fetch('/api/git/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path }),
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        timeoutId = null;

        if (!res.ok) {
            const result = { isGit: false, isRoot: false, gitRoot: null, error: `HTTP ${res.status}` };
            gitRepoCheckCache.set(cacheKey, { ts: now, result });
            return result;
        }
        const data = await res.json();

        let result;
        if (data.error && !data.is_git) {
            // 有错误且不是 Git 仓库
            result = { isGit: false, isRoot: false, gitRoot: null, error: data.error };
        } else if (!data.is_git) {
            // 不是 Git 仓库
            result = { isGit: false, isRoot: false, gitRoot: null, error: null };
        } else {
            // 是 Git 仓库，检查是否是根目录
            const gitRoot = data.git_root || null;
            let isRoot = false;

            if (gitRoot) {
                // 规范化路径进行比较（处理大小写和路径分隔符差异）
                const normalizedPath = path.replace(/[\\/]+$/, '').toLowerCase().replace(/\\/g, '/');
                const normalizedGitRoot = gitRoot.replace(/[\\/]+$/, '').toLowerCase().replace(/\\/g, '/');
                isRoot = (normalizedPath === normalizedGitRoot);
            }

            result = { isGit: true, isRoot: isRoot, gitRoot: gitRoot, error: data.error || null };
        }

        gitRepoCheckCache.set(cacheKey, { ts: now, result });
        return result;
    } catch (e) {
        // 确保清理定时器
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
        console.error('[checkGitRepository] Error:', e);
        const result = { isGit: false, isRoot: false, gitRoot: null, error: e.message || 'Unknown error' };
        // 错误缓存时间更短（5秒），便于用户修复后快速重试
        const errorCacheTTL = 5000;
        gitRepoCheckCache.set(cacheKey, { ts: now - GIT_CHECK_CACHE_TTL_MS + errorCacheTTL, result });
        return result;
    }
}


/**
 * 预检查目录是否为 Git 仓库（静默异步，不阻塞 UI）
 * @param {string} path - 项目路径
 */
function prefetchGitCheck(path) {
    if (!path) return;
    const cacheKey = path.toLowerCase().replace(/[\\/]+$/, '');
    const cached = gitRepoCheckCache.get(cacheKey);
    const now = Date.now();

    // 如果缓存有效，无需预检查
    if (cached && (now - cached.ts) < GIT_CHECK_CACHE_TTL_MS) {
        return;
    }

    // 静默检查，不阻塞
    checkGitRepository(path).catch(() => { });
}


/**
 * 显示非 Git 仓库警告对话框
 * @param {string} path - 项目路径
 * @param {Function} onContinue - 用户选择继续时的回调
 * @param {Function} onCancel - 用户选择取消时的回调
 */
function showNotGitRepoWarning(path, onContinue, onCancel) {
    const folderName = path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path;

    const warningContent = `
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


    if (typeof showConfirmDialog === 'function') {
        showConfirmDialog({
            title: '非 Git 仓库',
            content: warningContent,
            confirmText: '仍然选择',
            cancelText: '重新选择',
            showCloseButton: true,
            onConfirm: () => {
                if (typeof onContinue === 'function') onContinue();
            },
            onCancel: () => {
                if (typeof onCancel === 'function') onCancel();
            }
        });
    } else {
        // Fallback: 使用 confirm
        const userChoice = confirm(`所选目录 "${folderName}" 不是一个 Git 仓库。\n\n本系统依赖 Git 来分析代码变更，部分功能将不可用。\n\n是否仍然选择此目录？`);
        if (userChoice) {
            if (typeof onContinue === 'function') onContinue();
        } else {
            if (typeof onCancel === 'function') onCancel();
        }
    }
}


/**
 * 显示 Git 子目录警告对话框
 * @param {string} path - 用户选择的路径
 * @param {string} gitRoot - Git 仓库根目录
 * @param {Function} onUseRoot - 用户选择使用根目录时的回调
 * @param {Function} onContinue - 用户选择继续使用子目录时的回调
 * @param {Function} onCancel - 用户选择取消时的回调
 */
function showGitSubdirWarning(path, gitRoot, onUseRoot, onContinue, onCancel) {
    const folderName = path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path;
    const rootFolderName = gitRoot.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || gitRoot;

    const warningContent = `
        <div style="padding: 0.25rem 0;">
            <div style="display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.75rem; background: var(--bg-secondary, #f8f9fa); border-radius: 6px; border-left: 3px solid var(--text-secondary, #909399); margin-bottom: 0.875rem;">
                <svg class="icon" style="width: 18px; height: 18px; flex-shrink: 0; margin-top: 2px; color: var(--text-secondary, #909399);"><use href="#icon-folder"></use></svg>
                <div style="flex: 1; min-width: 0;">
                    <div style="font-size: 0.75rem; color: var(--text-placeholder, #909399); margin-bottom: 0.125rem;">当前选择</div>
                    <div style="font-size: 0.9rem; color: var(--text-primary, #303133); font-weight: 500; word-break: break-all;">${escapeHtml(folderName)}</div>
                </div>
            </div>
            
            <p style="margin: 0 0 0.75rem 0; color: var(--text-secondary, #606266); line-height: 1.5; font-size: 0.875rem;">
                您选择的是 Git 仓库的<strong style="color: var(--warning, #e6a23c);">子目录</strong>，而不是项目根目录。使用子目录可能导致：
            </p>
            
            <ul style="margin: 0 0 0.875rem 0; padding-left: 1.5rem; color: var(--text-secondary, #606266); font-size: 0.85rem; line-height: 1.6;">
                <li>部分代码变更无法检测</li>
                <li>提交历史不完整</li>
                <li>项目结构分析不准确</li>
            </ul>
            
            <div style="display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.75rem; background: var(--bg-secondary, #f8f9fa); border-radius: 6px; border-left: 3px solid var(--primary, #409eff);">
                <svg class="icon" style="width: 18px; height: 18px; flex-shrink: 0; margin-top: 2px; color: var(--primary, #409eff);"><use href="#icon-folder"></use></svg>
                <div style="flex: 1; min-width: 0;">
                    <div style="font-size: 0.75rem; color: var(--primary, #409eff); margin-bottom: 0.125rem;">建议选择项目根目录</div>
                    <div style="font-size: 0.9rem; color: var(--text-primary, #303133); font-weight: 500; word-break: break-all;">${escapeHtml(rootFolderName)}</div>
                    <div style="font-size: 0.75rem; color: var(--text-placeholder, #909399); margin-top: 0.25rem; word-break: break-all;">${escapeHtml(gitRoot)}</div>
                </div>
            </div>
        </div>
    `;


    if (typeof showConfirmDialog === 'function') {
        // 创建自定义三按钮对话框
        const existingDialog = document.getElementById('confirmDialog');
        if (existingDialog) existingDialog.remove();

        const dialog = document.createElement('div');
        dialog.id = 'confirmDialog';
        dialog.className = 'modal-overlay';
        dialog.innerHTML = `
            <div class="modal-container confirm-dialog-container" style="max-width: 440px;">
                <div class="modal-header">
                    <h3>选择了子目录</h3>
                    <button class="icon-btn modal-close-btn" id="subdirDialogCloseBtn">
                        <svg class="icon"><use href="#icon-x"></use></svg>
                    </button>
                </div>
                <div class="modal-body">
                    ${warningContent}
                </div>
                <div class="modal-footer" style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                    <button class="btn-secondary" id="subdirDialogCancelBtn" style="flex: 1; min-width: 70px;">取消</button>
                    <button class="btn-secondary" id="subdirDialogContinueBtn" style="flex: 1; min-width: 90px;">仍用子目录</button>
                    <button class="btn-primary" id="subdirDialogUseRootBtn" style="flex: 1.2; min-width: 100px;">使用根目录</button>
                </div>
            </div>
        `;

        document.body.appendChild(dialog);

        const closeDialog = () => dialog.remove();

        // 绑定事件
        document.getElementById('subdirDialogCloseBtn').onclick = () => {
            closeDialog();
            if (typeof onCancel === 'function') onCancel();
        };

        document.getElementById('subdirDialogCancelBtn').onclick = () => {
            closeDialog();
            if (typeof onCancel === 'function') onCancel();
        };

        document.getElementById('subdirDialogContinueBtn').onclick = () => {
            closeDialog();
            if (typeof onContinue === 'function') onContinue();
        };

        document.getElementById('subdirDialogUseRootBtn').onclick = () => {
            closeDialog();
            if (typeof onUseRoot === 'function') onUseRoot();
        };

        // 点击遮罩关闭
        dialog.onclick = (e) => {
            if (e.target === dialog) {
                closeDialog();
                if (typeof onCancel === 'function') onCancel();
            }
        };
    } else {
        // Fallback: 使用 confirm
        const userChoice = confirm(`您选择的 "${folderName}" 是 Git 仓库的子目录。\n\n建议选择项目根目录：${gitRoot}\n\n点击"确定"使用根目录，点击"取消"保持当前选择。`);
        if (userChoice) {
            if (typeof onUseRoot === 'function') onUseRoot();
        } else {
            if (typeof onContinue === 'function') onContinue();
        }
    }
}


// --- 项目路径更新 ---

function updateProjectPath(path) {
    window.currentProjectRoot = path || null;

    try {
        if (path) {
            localStorage.setItem(PROJECT_ROOT_STORAGE_KEY, path);
        } else {
            localStorage.removeItem(PROJECT_ROOT_STORAGE_KEY);
        }
    } catch (_) { }

    const projectRootInput = document.getElementById('projectRoot');
    if (projectRootInput) projectRootInput.value = path || '';

    const pathLabel = document.getElementById('currentPathLabel');
    if (pathLabel) pathLabel.textContent = path || '请选择文件夹...';

    const dashPath = document.getElementById('dash-project-path');
    if (dashPath) dashPath.textContent = path || '未选择';

    const reviewPath = document.getElementById('reviewProjectPath');
    if (reviewPath) reviewPath.textContent = path || '--';

    try {
        if (typeof window.resetDiffState === 'function') {
            window.resetDiffState();
        }
    } catch (_) { }

    try {
        const dashboardPage = document.getElementById('page-dashboard');
        const isDashboardVisible = dashboardPage && dashboardPage.style.display !== 'none';
        if (isDashboardVisible && typeof window.GitHistory !== 'undefined' && window.GitHistory && typeof window.GitHistory.init === 'function') {
            window.GitHistory.init(path || null).catch(() => { });
        }
    } catch (_) { }

    // 选择项目后自动加载意图分析
    if (path) {
        if (typeof loadIntentData === 'function') {
            loadIntentData();
        }
        // 刷新扫描器状态（根据项目语言）
        if (typeof loadScannerStatus === 'function') {
            loadScannerStatus();
        }

        scheduleProjectPrefetch(path);
    }
}

// Export to window
window.SessionState = SessionState;
window.LayoutState = LayoutState;
window.currentLayoutState = currentLayoutState;

window.isReviewRunning = isReviewRunning;
window.getRunningSessionId = getRunningSessionId;
window.startReviewTask = startReviewTask;
window.endReviewTask = endReviewTask;
window.saveRunningUISnapshot = saveRunningUISnapshot;
window.restoreRunningUISnapshot = restoreRunningUISnapshot;
window.setViewingHistory = setViewingHistory;
window.isViewingHistory = isViewingHistory;
window.updateBackgroundTaskIndicator = updateBackgroundTaskIndicator;
window.getLayoutState = getLayoutState;
window.setLayoutState = setLayoutState;
window.updateProjectPath = updateProjectPath;
window.checkGitRepository = checkGitRepository;
window.prefetchGitCheck = prefetchGitCheck;
window.showNotGitRepoWarning = showNotGitRepoWarning;
window.showGitSubdirWarning = showGitSubdirWarning;
