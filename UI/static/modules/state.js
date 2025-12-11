/**
 * state.js - 全局状态管理模块
 */

// --- Global State ---
window.currentSessionId = null;
window.currentProjectRoot = null;
window.currentDiffMode = 'auto';
window.currentModelValue = "";  // 将由 loadOptions 自动设置为第一个可用模型
window.availableGroups = [];

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

// --- 项目路径更新 ---
function updateProjectPath(path) {
    window.currentProjectRoot = path || null;

    const projectRootInput = document.getElementById('projectRoot');
    if (projectRootInput) projectRootInput.value = path || '';

    const pathLabel = document.getElementById('currentPathLabel');
    if (pathLabel) pathLabel.textContent = path || '请选择文件夹...';

    const dashPath = document.getElementById('dash-project-path');
    if (dashPath) dashPath.textContent = path || '未选择';

    const reviewPath = document.getElementById('reviewProjectPath');
    if (reviewPath) reviewPath.textContent = path || '--';

    // 选择项目后自动加载意图分析
    if (path) {
        if (typeof loadIntentData === 'function') {
            loadIntentData();
        }
        // 刷新扫描器状态（根据项目语言）
        if (typeof loadScannerStatus === 'function') {
            loadScannerStatus();
        }
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
