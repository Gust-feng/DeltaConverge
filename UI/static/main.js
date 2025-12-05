// --- Icons Helper ---
function getIcon(name) {
    return `<svg class="icon icon-${name}"><use href="#icon-${name}"></use></svg>`;
}

// --- Global State ---
let currentSessionId = null;
let currentProjectRoot = null;
let currentDiffMode = 'auto';
let currentModelValue = "auto";
let availableGroups = [];

// 会话状态管理（简化设计）
const SessionState = {
    // 正在运行审查任务的会话ID（如果有的话）
    runningSessionId: null,
    // 运行中任务的UI快照
    runningUISnapshot: {
        workflowHTML: '',
        monitorHTML: '',
        reportHTML: ''
    },
    // 当前是否在查看历史会话（只读模式）
    isViewingHistory: false,
    pollTimerId: null,
    reviewStreamActive: false
};

// --- 全局工具函数 ---
// 阶段折叠切换函数（需要全局可用，因为在 onclick 中调用）
window.toggleStageSection = function(headerEl) {
    const section = headerEl.closest('.workflow-stage-section');
    if (section) {
        section.classList.toggle('collapsed');
    }
};

// --- Timer Logic ---
let reviewStartTime = null;
let reviewTimerInterval = null;

function startReviewTimer() {
    if (reviewTimerInterval) clearInterval(reviewTimerInterval);
    reviewStartTime = Date.now();
    const timerEl = document.getElementById('reviewTimer');
    if (timerEl) timerEl.textContent = '00:00';
    
    reviewTimerInterval = setInterval(() => {
        if (!reviewStartTime) return;
        const elapsed = Date.now() - reviewStartTime;
        const seconds = Math.floor(elapsed / 1000);
        const m = Math.floor(seconds / 60).toString().padStart(2, '0');
        const s = (seconds % 60).toString().padStart(2, '0');
        if (timerEl) timerEl.textContent = `${m}:${s}`;
    }, 1000);
}

window.addEventListener('beforeunload', () => {
    stopReviewTimer();
    if (typeof stopSessionPolling === 'function') stopSessionPolling();
    try { if (thoughtTimerInterval) { clearInterval(thoughtTimerInterval); thoughtTimerInterval = null; } } catch (e) {}
});

function stopReviewTimer() {
    if (reviewTimerInterval) {
        clearInterval(reviewTimerInterval);
        reviewTimerInterval = null;
    }
    
    // Ensure final time is displayed
    if (reviewStartTime) {
        const elapsed = Date.now() - reviewStartTime;
        const seconds = Math.floor(elapsed / 1000);
        const m = Math.floor(seconds / 60).toString().padStart(2, '0');
        const s = (seconds % 60).toString().padStart(2, '0');
        const timerEl = document.getElementById('reviewTimer');
        if (timerEl) timerEl.textContent = `总用时 ${m}:${s}`;
    }
}

function getLastSessionId() {
    try { return localStorage.getItem('lastSessionId') || null; } catch (e) { return null; }
}

function setLastSessionId(sid) {
    try { if (sid) localStorage.setItem('lastSessionId', sid); } catch (e) {}
}

function clearLastSessionId() {
    try { localStorage.removeItem('lastSessionId'); } catch (e) {}
}

// --- 会话状态管理 ---

/**
 * 检查是否有正在运行的审查任务
 */
function isReviewRunning() {
    return SessionState.runningSessionId !== null;
}

/**
 * 获取正在运行审查任务的会话ID
 */
function getRunningSessionId() {
    return SessionState.runningSessionId;
}

/**
 * 开始审查任务 - 标记会话为运行状态
 */
function startReviewTask(sessionId) {
    SessionState.runningSessionId = sessionId;
    SessionState.isViewingHistory = false;
    SessionState.runningUISnapshot = { workflowHTML: '', monitorHTML: '', reportHTML: '' };
    stopSessionPolling();
    // 刷新会话列表以显示"进行中"状态
    loadSessions();
    updateBackgroundTaskIndicator();
}

/**
 * 结束审查任务 - 清除运行状态
 */
function endReviewTask() {
    SessionState.runningSessionId = null;
    SessionState.runningUISnapshot = { workflowHTML: '', monitorHTML: '', reportHTML: '' };
    stopSessionPolling();
    // 刷新会话列表
    loadSessions();
    updateBackgroundTaskIndicator();
}

/**
 * 保存运行中任务的UI快照
 */
function saveRunningUISnapshot() {
    if (!isReviewRunning()) return;
    
    const workflowEntries = document.getElementById('workflowEntries');
    const monitorContent = document.getElementById('monitorContent');
    const reportContainer = document.getElementById('reportContainer');
    
    if (workflowEntries) SessionState.runningUISnapshot.workflowHTML = workflowEntries.innerHTML;
    if (monitorContent) SessionState.runningUISnapshot.monitorHTML = monitorContent.innerHTML;
    if (reportContainer) SessionState.runningUISnapshot.reportHTML = reportContainer.innerHTML;
}

/**
 * 恢复运行中任务的UI快照
 */
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

/**
 * 设置历史浏览模式
 */
function setViewingHistory(isViewing) {
    SessionState.isViewingHistory = isViewing;
    
    // 显示/隐藏只读标识
    const historyBackBtn = document.getElementById('historyBackBtn');
    const historyModeLabel = document.getElementById('historyModeLabel');
    const pickFolderBtn = document.getElementById('pickFolderBtn');
    const startReviewBtn = document.getElementById('startReviewBtn');
    
    if (historyBackBtn) historyBackBtn.style.display = isViewing ? 'flex' : 'none';
    if (historyModeLabel) historyModeLabel.style.display = isViewing ? 'inline-flex' : 'none';
    
    // 历史模式下禁用操作按钮
    if (pickFolderBtn) {
        pickFolderBtn.disabled = isViewing;
        pickFolderBtn.style.opacity = isViewing ? '0.5' : '1';
        pickFolderBtn.style.pointerEvents = isViewing ? 'none' : 'auto';
    }
    if (startReviewBtn) {
        startReviewBtn.disabled = isViewing;
        startReviewBtn.style.opacity = isViewing ? '0.5' : '1';
        startReviewBtn.style.pointerEvents = isViewing ? 'none' : 'auto';
    }
    
    // 更新后台任务按钮显示
    updateBackgroundTaskIndicator();
}

/**
 * 更新后台任务指示器
 */
function updateBackgroundTaskIndicator() {
    const backgroundTaskBtn = document.getElementById('backgroundTaskBtn');
    if (!backgroundTaskBtn) return;
    
    const runningSessionId = getRunningSessionId();
    const isViewingHistoryMode = isViewingHistory();
    const isCurrentSessionRunning = currentSessionId === runningSessionId;
    
    // 只有当：1) 有任务在后台运行，2) 不在查看历史，3) 当前会话不是运行中的会话时，才显示后台任务按钮
    if (runningSessionId && !isViewingHistoryMode && !isCurrentSessionRunning) {
        backgroundTaskBtn.style.display = 'flex';
    } else {
        backgroundTaskBtn.style.display = 'none';
    }
}

/**
 * 检查是否在浏览历史
 */
function isViewingHistory() {
    return SessionState.isViewingHistory;
}

// --- Layout State Management ---
// Layout state constants for review page
const LayoutState = {
    INITIAL: 'initial',      // 单一画布 - 初始状态
    REVIEWING: 'reviewing',  // 分栏视图 - 审查中
    COMPLETED: 'completed'   // 分栏视图 - 报告展示
};

// Current layout state
let currentLayoutState = LayoutState.INITIAL;

/**
 * Get the current layout state.
 * @returns {string} Current layout state (initial, reviewing, or completed)
 */
function getLayoutState() {
    return currentLayoutState;
}

/**
 * Set the layout state for the review page.
 * Updates the data-layout-state attribute on the workbench element
 * which triggers CSS transitions for panel visibility.
 * 
 * @param {string} newState - The new layout state (use LayoutState constants)
 */
function setLayoutState(newState) {
    const workbench = document.getElementById('page-review');
    if (!workbench) {
        console.warn('setLayoutState: page-review element not found');
        return;
    }
    
    // Validate state
    const validStates = Object.values(LayoutState);
    if (!validStates.includes(newState)) {
        console.warn(`setLayoutState: Invalid state "${newState}". Valid states: ${validStates.join(', ')}`);
        return;
    }
    
    // Update state
    const previousState = currentLayoutState;
    currentLayoutState = newState;
    workbench.dataset.layoutState = newState;
    
    // Sync state to app-container for global layout control (Sidebar etc.)
    const appContainer = document.querySelector('.app-container');
    if (appContainer) {
        appContainer.dataset.layoutState = newState;
    }
    
}

/**
 * 更新项目路径（全局状态和UI）
 * @param {string} path - 新的项目路径
 */
function updateProjectPath(path) {
    currentProjectRoot = path || null;
    
    const displayPath = path || '请选择文件夹...';
    
    if (projectRootInput) projectRootInput.value = path || '';
    if (currentPathLabel) currentPathLabel.textContent = displayPath;
    if (dashProjectPath) dashProjectPath.textContent = displayPath;
    
    // 更新进度面板右侧的路径显示
    const reviewProjectPath = document.getElementById('reviewProjectPath');
    if (reviewProjectPath) {
        reviewProjectPath.textContent = path || '--';
        reviewProjectPath.title = path || '';
    }
}

// --- DOM Elements ---
// Nav
const navBtns = document.querySelectorAll('.nav-btn');
const pageViews = document.querySelectorAll('.page-view, .workbench');

// Dashboard
const healthStatusBadge = document.getElementById('health-status-badge');
const healthMetricsDiv = document.getElementById('health-metrics');
const dashProjectPath = document.getElementById('dash-project-path');
const dashDiffStatus = document.getElementById('dash-diff-status');

// Diff
const diffFileList = document.getElementById('diff-file-list');
const diffContentArea = document.getElementById('diff-content-area');

// Config
const configFormContainer = document.getElementById('config-form-container');

// Debug
const cacheStatsDiv = document.getElementById('cache-stats');
const intentCacheListDiv = document.getElementById('intent-cache-list');

// Chat/Review (Existing)
const sessionListEl = document.getElementById('sessionList');
const historyToggleBtn = document.getElementById('historyToggleBtn');
const closeHistoryBtn = document.getElementById('closeHistoryBtn');
const historyDrawer = document.getElementById('historyDrawer');
// const currentSessionTitle = document.getElementById('currentSessionTitle'); // REMOVED: Not present in new HTML
const messageContainer = document.getElementById('messageContainer');
const promptInput = document.getElementById('prompt');
const sendBtn = document.getElementById('sendBtn');
const projectRootInput = document.getElementById('projectRoot');
const pickFolderBtn = document.getElementById('pickFolderBtn');
const currentPathLabel = document.getElementById('currentPathLabel');
const autoApproveInput = document.getElementById('autoApprove');
const toolListContainer = document.getElementById('toolListContainer');
const startReviewBtn = document.getElementById('startReviewBtn');
const modelDropdown = document.getElementById('modelDropdown');
const modelDropdownTrigger = document.getElementById('modelDropdownTrigger');
const modelDropdownMenu = document.getElementById('modelDropdownMenu');
const selectedModelText = document.getElementById('selectedModelText');
const reportContainer = document.getElementById('reportContainer');
const workbenchEl = document.querySelector('.workbench');

// Last session reminder helpers
const LAST_SESSION_REMINDER_ID = 'lastSessionReminderCard';

function removeLastSessionReminder() {
    const card = document.getElementById(LAST_SESSION_REMINDER_ID);
    if (card) card.remove();
}

function renderLastSessionReminder(sessionData) {
    if (!messageContainer) return;
    removeLastSessionReminder();

    const meta = sessionData.metadata || {};
    const sessionId = sessionData.session_id;
    const name = meta.name || sessionId;
    let updatedText = '';
    if (meta.updated_at) {
        try {
            updatedText = new Date(meta.updated_at).toLocaleString('zh-CN', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (_) {
            updatedText = meta.updated_at;
        }
    }

    const card = document.createElement('div');
    card.id = LAST_SESSION_REMINDER_ID;
    card.className = 'session-reminder-card';
    card.innerHTML = `
        <div class="reminder-icon">${getIcon('clock')}</div>
        <div class="reminder-info">
            <div class="reminder-title">检测到上次未完成的审查</div>
            <div class="reminder-meta">${escapeHtml(name)}${updatedText ? ` · ${escapeHtml(updatedText)}` : ''}</div>
        </div>
        <div class="reminder-actions">
            <button class="btn-primary btn-small reminder-continue">继续</button>
            <button class="btn-secondary btn-small reminder-dismiss">忽略</button>
        </div>
    `;

    const continueBtn = card.querySelector('.reminder-continue');
    if (continueBtn) {
        continueBtn.onclick = () => {
            loadSession(sessionId);
        };
    }
    const dismissBtn = card.querySelector('.reminder-dismiss');
    if (dismissBtn) {
        dismissBtn.onclick = () => {
            removeLastSessionReminder();
            clearLastSessionId(); // 清除记录，不再提醒
        };
    }

    messageContainer.prepend(card);
}

async function showLastSessionReminder() {
    if (currentSessionId) return; // 已经打开会话
    const lastSid = getLastSessionId();
    if (!lastSid) return;
    if (document.getElementById(LAST_SESSION_REMINDER_ID)) return;
    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(lastSid)}`);
        if (!res.ok) throw new Error('not found');
        const data = await res.json();
        
        // 检查会话时间 - 超过48小时的不再提醒（改为48小时更合理）
        const meta = data.metadata || {};
        if (meta.updated_at) {
            const updatedTime = new Date(meta.updated_at).getTime();
            const now = Date.now();
            const hoursElapsed = (now - updatedTime) / (1000 * 60 * 60);
            if (hoursElapsed > 48) {
                clearLastSessionId();
                return;
            }
        }
        
        // 检查是否有最终报告（assistant 消息）
        const messages = data.messages || [];
        const hasReport = messages.some(m => m.role === 'assistant' && m.content);
        
        // 只有没有最终报告的会话才提醒
        if (hasReport) {
            // 已完成的会话，清除记录
            clearLastSessionId();
            return;
        }
        
        // 检查是否有实际的工作流事件（说明审查确实开始了）
        // 如果有工作流事件才提醒，避免提醒空会话
        const events = data.workflow_events || [];
        if (events.length === 0) {
            // 没有任何事件，可能只是创建了会话但没开始，不提醒但暂时保留记录
            return;
        }
        
        renderLastSessionReminder(data);
    } catch (e) {
        console.warn('Failed to fetch last session reminder:', e);
        clearLastSessionId();
    }
}

// --- Initialization ---

async function init() {
    try {
        // Bind global events
        bindEvents();
        
        // Initialize layout state to initial (single canvas) - 只设置一次
        setLayoutState(LayoutState.INITIAL);
        currentSessionId = null;  // 确保没有当前会话
        
        // Default page
        switchPage('review');
        
        // Initial loads (don't fail if these error)
        try {
            await loadOptions();
        } catch (e) {
            console.error("Failed to load options:", e);
        }
        
        try {
            // 只加载会话列表，但不自动打开任何会话
            // 用户需要手动点击历史记录才会加载会话
            await loadSessions();
        } catch (e) {
            console.error("Failed to load sessions:", e);
        }
        
        // 初始化后台任务指示器
        updateBackgroundTaskIndicator();
        
        // Start loop for health check
        setInterval(updateHealthStatus, 30000);
    } catch (e) {
        console.error("App Initialization Failed:", e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Ensure DOM is ready (though script is at end of body, this is safer)
    init();
});


function bindEvents() {
    // Navigation handled inline in HTML for simplicity, or bind here if preferred
    
    // Sidebar Toggles
    if(historyToggleBtn) historyToggleBtn.onclick = toggleHistoryDrawer;
    if(closeHistoryBtn) closeHistoryBtn.onclick = toggleHistoryDrawer;
    
    // 历史模式返回按钮
    const historyBackBtn = document.getElementById('historyBackBtn');
    if(historyBackBtn) historyBackBtn.onclick = returnToNewWorkspace;
    
    // 后台任务按钮
    const backgroundTaskBtn = document.getElementById('backgroundTaskBtn');
    if(backgroundTaskBtn) {
        backgroundTaskBtn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const runningSessionId = getRunningSessionId();
            if (runningSessionId) {
                loadSession(runningSessionId);
            } else {
                showToast('没有正在运行的任务', 'info');
            }
        };
    }
    
    // Chat Inputs
    if(pickFolderBtn) pickFolderBtn.onclick = pickFolder;
    if(startReviewBtn) startReviewBtn.onclick = startReview;
    if(sendBtn) sendBtn.onclick = sendMessage; // Legacy/Hidden
    if(promptInput) {
        promptInput.onkeydown = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(); // Or startReview depending on context
            }
        };
    }

    // Model Dropdown
    if(modelDropdownTrigger) {
        modelDropdownTrigger.onclick = toggleModelDropdown;
        document.addEventListener('click', (e) => {
            if (modelDropdown && !modelDropdown.contains(e.target)) {
                modelDropdown.classList.remove('open');
            }
        });
    }

    // Report Panel Actions
    // Use event delegation for robustness
    document.addEventListener('click', (e) => {
        // Check if clicked element is the back button or contained within it
        const btn = e.target.closest('#reportBackBtn');
        if (btn) {
            e.preventDefault();
            e.stopPropagation();
            reportGoBack();
        }
    });
}

// --- Navigation Logic ---

function switchPage(pageId) {
    // Update Nav State
    // Use local query if global is not trusted, but global should be fine if init runs after DOM
    const btns = document.querySelectorAll('.nav-btn'); 
    btns.forEach(btn => {
        if (btn.id === `nav-${pageId}`) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Update View State
    const views = document.querySelectorAll('.page-view, .workbench');
    views.forEach(view => {
        if (view.id === `page-${pageId}`) {
            view.style.display = (pageId === 'review') ? 'flex' : 'block';
        } else {
            view.style.display = 'none';
        }
    });

    // Update Document Title
    const titles = {
        'dashboard': '仪表盘 - Code Review Agent',
        'review': '代码审查 - Code Review Agent',
        'diff': '代码变更 - Code Review Agent',
        'config': '设置 - Code Review Agent',
        'debug': '调试 - Code Review Agent'
    };
    document.title = titles[pageId] || 'Code Review Agent';

    // Trigger Loaders
    if (pageId === 'dashboard') loadDashboardData();
    if (pageId === 'diff') refreshDiffAnalysis();
    if (pageId === 'config') loadConfig();
    if (pageId === 'debug') loadDebugInfo();
}

// --- Dashboard Logic ---

async function updateHealthStatus() {
    try {
        const res = await fetch('/api/health/simple');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        if (healthStatusBadge) {
            healthStatusBadge.textContent = data.healthy ? 'Healthy' : 'Unhealthy';
            healthStatusBadge.className = `badge ${data.healthy ? 'success' : 'error'}`;
        }
    } catch (e) {
        console.error("Health check failed", e);
        if (healthStatusBadge) {
            healthStatusBadge.textContent = 'Error';
            healthStatusBadge.className = 'badge error';
        }
    }
}

async function loadDashboardData() {
    if (healthMetricsDiv) {
        // Optional: Add a subtle loading indicator if data takes time, 
        // but keep old data visible or use a spinner if preferred.
        // For now, we'll just let it update.
    }

    updateHealthStatus();
    
    // Load Metrics
    try {
        const res = await fetch('/api/metrics');
        if (res.ok) {
            const metrics = await res.json();
            if (healthMetricsDiv) {
                const uptime = metrics.uptime_seconds ? Math.floor(metrics.uptime_seconds / 60) : 0;
                const memory = metrics.memory_usage_mb ? metrics.memory_usage_mb.toFixed(1) : '0';
                const threads = metrics.thread_count || 0;
                healthMetricsDiv.innerHTML = `
                    <div class="stat-row"><span class="label">Uptime:</span><span class="value">${uptime} min</span></div>
                    <div class="stat-row"><span class="label">Memory:</span><span class="value">${memory} MB</span></div>
                    <div class="stat-row"><span class="label">Threads:</span><span class="value">${threads}</span></div>
                `;
            }
        }
    } catch (e) {
        console.error("Load metrics error:", e);
        if (healthMetricsDiv) {
            healthMetricsDiv.innerHTML = `<div class="error-text">Failed to load metrics</div>`;
        }
    }

    // Project Info
    if (currentProjectRoot) {
        if (dashProjectPath) dashProjectPath.textContent = currentProjectRoot;
        
        // Show checking status
        if (dashDiffStatus) dashDiffStatus.textContent = "Checking...";
        
        try {
            const res = await fetch(`/api/diff/status?project_root=${encodeURIComponent(currentProjectRoot)}`);
            if (res.ok) {
                const status = await res.json();
                if (dashDiffStatus) {
                    dashDiffStatus.textContent = status.has_working_changes || status.has_staged_changes 
                        ? `Has Changes (${status.detected_mode || 'unknown'})` 
                        : "Clean";
                }
            }
        } catch (e) {
            if (dashDiffStatus) dashDiffStatus.textContent = "Error checking diff";
        }
    } else {
        if (dashProjectPath) dashProjectPath.textContent = "未选择";
        if (dashDiffStatus) dashDiffStatus.textContent = "-";
    }
    
    // Load Intent Data
    loadIntentData();
}

async function loadIntentData() {
    const contentDiv = document.getElementById('intent-content');
    const emptyState = document.getElementById('intent-empty');
    const viewMode = document.getElementById('intent-view');
    const thoughtContainer = document.getElementById('intent-thought-container');
    
    if (!currentProjectRoot) {
        if (emptyState) emptyState.style.display = 'flex';
        if (contentDiv) contentDiv.innerHTML = '';
        if (viewMode) viewMode.style.display = 'block';
        if (thoughtContainer) thoughtContainer.style.display = 'none';
        if (typeof intentContent !== 'undefined') intentContent = "";
        return;
    }

    // Extract project name
    const projectName = currentProjectRoot.replace(/[\\/]$/, '').split(/[\\/]/).pop();
    
    try {
        const res = await fetch(`/api/cache/intent/${encodeURIComponent(projectName)}`);
        if (res.ok) {
            const data = await res.json();
            // 支持 response.content 路径
            let content = data.content || "";
            if (!content && data.response && typeof data.response.content === 'string') {
                content = data.response.content;
            }
            if (content) {
                if (typeof intentContent !== 'undefined') intentContent = content;
                if (emptyState) emptyState.style.display = 'none';
                if (viewMode) viewMode.style.display = 'block';
                if (contentDiv) {
                    contentDiv.innerHTML = marked.parse(content);
                }
                if (thoughtContainer) thoughtContainer.style.display = 'none';
            } else {
                 if (emptyState) emptyState.style.display = 'flex';
                 if (contentDiv) contentDiv.innerHTML = '';
                 if (typeof intentContent !== 'undefined') intentContent = "";
            }
        } else {
            // Not found
            if (emptyState) emptyState.style.display = 'flex';
            if (contentDiv) contentDiv.innerHTML = '';
            if (typeof intentContent !== 'undefined') intentContent = "";
        }
    } catch (e) {
        console.error("Load intent error:", e);
        if (emptyState) emptyState.style.display = 'flex';
    }
}

// --- Diff Analysis Logic ---

async function refreshDiffAnalysis() {
    if (!diffFileList) return;
    
    if (!currentProjectRoot) {
        diffFileList.innerHTML = '<div class="empty-state">请先在仪表盘或审查页面选择项目</div>';
        return;
    }

    diffFileList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);">Loading diff...</div>';
    
    try {
        const res = await fetch(`/api/diff/analyze`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ project_root: currentProjectRoot, mode: 'auto' })
        });
        
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        
        const data = await res.json();
        
        if (data.detected_mode) {
            currentDiffMode = data.detected_mode;
        }
        
        renderDiffFileList(data.files || []);
    } catch (e) {
        console.error("Refresh diff error:", e);
        diffFileList.innerHTML = `<div style="padding:1rem;color:red;">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function renderDiffFileList(files) {
    if (!diffFileList) return;
    
    if (!files || files.length === 0) {
        diffFileList.innerHTML = '<div class="empty-state">无文件变更</div>';
        return;
    }

    diffFileList.innerHTML = '';
    files.forEach(file => {
        const div = document.createElement('div');
        div.className = 'file-list-item';
        
        // Handle both string (legacy) and object (new API) formats
        const filePath = typeof file === 'string' ? file : (file.path || "Unknown File");
        const changeType = typeof file === 'object' ? file.change_type : "modify";
        
        // Icon mapping
        let icon = getIcon('file');
        let statusClass = 'status-modify';
        if (changeType === 'add') { icon = getIcon('plus'); statusClass = 'status-add'; }
        else if (changeType === 'delete') { icon = getIcon('trash'); statusClass = 'status-delete'; }
        else if (changeType === 'rename') { icon = getIcon('edit'); statusClass = 'status-rename'; }
        
        // Truncate path for display
        const fileName = filePath.split('/').pop();
        const dirPath = filePath.substring(0, filePath.lastIndexOf('/'));
        
        div.innerHTML = `
            <div class="file-item-row">
                <span class="file-icon ${statusClass}">${icon}</span>
                <div class="file-info">
                    <div class="file-name" title="${escapeHtml(filePath)}">${escapeHtml(fileName)}</div>
                    <div class="file-path" title="${escapeHtml(dirPath)}">${escapeHtml(dirPath)}</div>
                </div>
            </div>
        `;
        
        div.dataset.path = filePath;
        div.onclick = () => loadFileDiff(filePath);
        diffFileList.appendChild(div);
    });
}

async function loadFileDiff(filePath) {
    if (!diffContentArea) return;
    
    if (!currentProjectRoot) {
        diffContentArea.innerHTML = '<div style="padding:1rem;color:red;">请先选择项目文件夹</div>';
        return;
    }
    
    diffContentArea.innerHTML = '<div class="empty-state">Loading...</div>';
    
    // Highlight active item using data attribute
    if (diffFileList) {
        const items = diffFileList.querySelectorAll('.file-list-item');
        items.forEach(i => {
            if (i.dataset.path === filePath) i.classList.add('active');
            else i.classList.remove('active');
        });
    }

    try {
        const res = await fetch(`/api/diff/file/${encodeURIComponent(filePath)}?project_root=${encodeURIComponent(currentProjectRoot)}&mode=${currentDiffMode}`);
        
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        
        const data = await res.json();
        
        if (data.error) {
             diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">${escapeHtml(data.error)}</div>`;
             return;
        }

        const diffText = data.diff_text || data.diff_content || "";
        
        // Use Diff2Html if available
        if (window.Diff2HtmlUI && diffText.trim()) {
            // 保持用户选择的视图模式，默认为 side-by-side
            const currentViewMode = window.currentDiffViewMode || 'side-by-side';
            const isUnified = currentViewMode === 'line-by-line';
            const isSplit = currentViewMode === 'side-by-side';
            
            diffContentArea.innerHTML = `
                <div class="diff-header">
                    <h3 title="${escapeHtml(filePath)}">${escapeHtml(filePath)}</h3>
                    <div class="diff-controls">
                        <label class="${isUnified ? 'active' : ''}">
                            <input type="radio" name="diff-view" value="line-by-line" ${isUnified ? 'checked' : ''} onclick="toggleDiffView('line-by-line')">
                            <span class="view-option">
                                <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
                                    <line x1="3" y1="6" x2="21" y2="6"></line>
                                    <line x1="3" y1="12" x2="21" y2="12"></line>
                                    <line x1="3" y1="18" x2="21" y2="18"></line>
                                </svg>
                                Unified
                            </span>
                        </label>
                        <label class="${isSplit ? 'active' : ''}">
                            <input type="radio" name="diff-view" value="side-by-side" ${isSplit ? 'checked' : ''} onclick="toggleDiffView('side-by-side')">
                            <span class="view-option">
                                <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="3" y="3" width="7" height="18" rx="1"></rect>
                                    <rect x="14" y="3" width="7" height="18" rx="1"></rect>
                                </svg>
                                Split
                            </span>
                        </label>
                    </div>
                </div>
                <div id="diff-ui-container" style="padding: 0;"></div>
            `;
            
            window.currentDiffText = diffText; // Store for toggling
            renderDiff2Html(diffText, currentViewMode);
            
        } else {
            const formattedDiff = diffText ? diffText.replace(/\r\n/g, '\n') : "No content";
            diffContentArea.innerHTML = `
                <div style="padding:1rem;">
                    <h3>${escapeHtml(filePath)}</h3>
                    <pre style="background:var(--bg-secondary);padding:1rem;overflow:auto;color:var(--text-primary);"><code>${escapeHtml(formattedDiff)}</code></pre>
                </div>
            `;
        }

    } catch (e) {
        console.error("Load file diff error:", e);
        diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">Error loading file: ${escapeHtml(e.message)}</div>`;
    }
}

function renderDiff2Html(diffText, outputFormat) {
    const targetElement = document.getElementById('diff-ui-container');
    if (!targetElement) return;
    
    const configuration = {
        drawFileList: false,
        fileListToggle: false,
        fileListStartVisible: false,
        fileContentToggle: false,
        matching: 'lines',
        outputFormat: outputFormat,
        synchronisedScroll: true, // Enable JS sync scroll
        highlight: true,
        renderNothingWhenEmpty: false,
    };
    
    const diff2htmlUi = new Diff2HtmlUI(targetElement, diffText, configuration);
    diff2htmlUi.draw();
    diff2htmlUi.highlightCode();
}

function toggleDiffView(mode) {
    // 保存用户选择的视图模式
    window.currentDiffViewMode = mode;
    
    // 更新按钮激活状态
    const controls = document.querySelector('.diff-controls');
    if (controls) {
        controls.querySelectorAll('label').forEach(label => {
            const input = label.querySelector('input');
            if (input && input.value === mode) {
                label.classList.add('active');
            } else {
                label.classList.remove('active');
            }
        });
    }
    
    if (window.currentDiffText) {
        renderDiff2Html(window.currentDiffText, mode);
    }
}

function escapeHtml(text) {
  if (text == null) return '';
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}


// --- Config Logic ---

async function loadConfig() {
    if (!configFormContainer) return;
    configFormContainer.innerHTML = 'Loading...';
    try {
        const res = await fetch('/api/config');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const config = await res.json();
        renderConfigForm(config);
    } catch (e) {
        console.error("Load config error:", e);
        configFormContainer.innerHTML = '<div class="empty-state">Error loading config</div>';
    }
}

const CONFIG_LABELS = {
    "llm.call_timeout": "调用超时 (秒)",
    "llm.planner_timeout": "规划器超时 (秒)",
    "llm.max_retries": "最大重试次数",
    "llm.retry_delay": "重试延迟 (秒)",
    "context.max_context_chars": "最大上下文长度 (字符)",
    "context.full_file_max_lines": "全文件读取限制 (行)",
    "context.callers_max_hits": "调用者分析深度",
    "context.file_cache_ttl": "文件缓存时间 (秒)",
    "review.max_files": "最大审查文件数",
    "review.auto_approve": "自动批准",
    "fusion.similarity_threshold": "相似度阈值"
};

function renderConfigForm(config) {
    // Flatten or categorize config
    // For simplicity, we'll just dump JSON for now or simple key-values
    // A better implementation would allow editing specific fields
    
    let html = '';
    
    // Config Form
    if (config.llm) {
        html += `<div class="config-section">
            <div class="section-header" style="display:flex;justify-content:space-between;align-items:center;">
                <h3>LLM 配置</h3>
                <button class="btn-secondary" onclick="openManageModelsModal()">管理模型</button>
            </div>`;
        for (const [key, val] of Object.entries(config.llm)) {
             // Skip complex objects if any
             if (typeof val === 'object' && val !== null) continue;
             const label = CONFIG_LABELS[`llm.${key}`] || key;
             html += createConfigInput(`llm.${key}`, label, val);
        }
        html += `</div>`;
    }

    // Context Config Section
    if (config.context) {
        html += `<div class="config-section"><h3>上下文配置</h3>`;
        for (const [key, val] of Object.entries(config.context)) {
             if (typeof val === 'object' && val !== null) continue;
             const label = CONFIG_LABELS[`context.${key}`] || key;
             html += createConfigInput(`context.${key}`, label, val);
        }
        html += `</div>`;
    }

    if (!html) {
        html = '<div class="empty-state">无可用配置项</div>';
    }
    
    configFormContainer.innerHTML = html;
}

function createConfigInput(fullKey, label, value) {
    const isBool = typeof value === 'boolean';
    const type = isBool ? 'checkbox' : (typeof value === 'number' ? 'number' : 'text');
    const checked = isBool && value ? 'checked' : '';
    const valueAttr = isBool ? '' : `value="${escapeHtml(value)}"`;
    
    return `
        <div class="form-group">
            <label>${escapeHtml(label)}</label>
            <input type="${type}" data-key="${escapeHtml(fullKey)}" ${valueAttr} ${checked}>
        </div>
    `;
}

async function saveConfig() {
    if (!configFormContainer) return;
    
    const inputs = configFormContainer.querySelectorAll('input');
    const updates = {};
    
    inputs.forEach(input => {
        const key = input.dataset.key;
        if (!key) return;
        
        const parts = key.split('.');
        if (parts.length < 2) return;
        
        const section = parts[0];
        const field = parts[1];
        
        if (!updates[section]) updates[section] = {};
        
        if (input.type === 'checkbox') {
            updates[section][field] = input.checked;
        } else if (input.type === 'number') {
            updates[section][field] = Number(input.value) || 0;
        } else {
            updates[section][field] = input.value;
        }
    });
    
    try {
        const res = await fetch('/api/config', {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ updates: updates, persist: true })
        });
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        showToast('配置已保存！', 'success');
    } catch (e) {
        console.error("Save config error:", e);
        showToast('保存失败: ' + e.message, 'error');
    }
}

// --- Debug Logic ---

async function loadDebugInfo() {
    try {
        const resStats = await fetch('/api/cache/stats');
        if (resStats.ok && cacheStatsDiv) {
            const stats = await resStats.json();
            const intentSize = stats.intent_cache_size || 0;
            const diffSize = stats.diff_cache_size || 0;
            cacheStatsDiv.innerHTML = `
                <div class="stat-row"><span class="label">Intent Cache Size:</span><span class="value">${intentSize} items</span></div>
                <div class="stat-row"><span class="label">Diff Cache Size:</span><span class="value">${diffSize} items</span></div>
            `;
        }
        
        const resIntents = await fetch('/api/cache/intent');
        if (resIntents.ok && intentCacheListDiv) {
            const intents = await resIntents.json();
            
            if (!intents || intents.length === 0) {
                intentCacheListDiv.innerHTML = '<div class="empty-state">No intent caches</div>';
            } else {
                intentCacheListDiv.innerHTML = intents.map(i => {
                    const project = escapeHtml(i.project_name || 'Unknown');
                    const timestamp = i.created_at ? new Date(i.created_at).toLocaleString() : '';
                    return `
                        <div class="file-list-item" style="cursor:default;">
                            <strong>${project}</strong>
                            <br>
                            <small class="text-muted">${timestamp}</small>
                        </div>
                    `;
                }).join('');
            }
        }
    } catch (e) {
        console.error("Load debug info error:", e);
    }
}

async function clearCache() {
    if(confirm('确定要清除所有意图缓存吗？')) {
        try {
            const res = await fetch('/api/cache/intent', { method: 'DELETE' });
            if (res.ok) {
                showToast('缓存已清除', 'success');
                loadDebugInfo();
            } else {
                showToast('清除缓存失败', 'error');
            }
        } catch (e) {
            console.error("Clear cache error:", e);
            showToast('清除缓存失败: ' + e.message, 'error');
        }
    }
}

// --- Existing Review/Chat Logic (Simplified & Integrated) ---

async function pickFolder() {
    try {
        const res = await fetch("/api/system/pick-folder", { method: "POST" });
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        
        if (data.error) {
            addSystemMessage("选择文件夹失败: " + escapeHtml(data.error));
            return;
        }
        
        if (data.path) {
            updateProjectPath(data.path);
            
            // Auto refresh dashboard if active
            const dashboardPage = document.getElementById('page-dashboard');
            if (dashboardPage && dashboardPage.style.display !== 'none') {
                loadDashboardData();
            }
            
            addSystemMessage(`已选择项目路径: ${escapeHtml(data.path)}`);
        }
    } catch (e) {
        console.error("Pick folder error:", e);
        addSystemMessage("选择文件夹失败: " + escapeHtml(e.message));
    }
}


// --- Progress Panel Logic ---
/**
 * Set the status of a progress step in the timeline.
 * Supports three states: pending (default), active, and completed.
 * 
 * @param {string} stepName - The step identifier (e.g., 'init', 'analysis', 'planning', 'reviewing', 'reporting')
 * @param {string} status - The status to set: 'pending', 'active', or 'completed'
 * @param {Object} data - Optional cumulative data to display under the step
 * @param {number} data.filesScanned - Number of files scanned
 * @param {number} data.issuesFound - Number of issues found
 * @param {number} data.duration - Duration in milliseconds
 */
function setProgressStep(stepName, status = 'active', data = null) {
    const panel = document.getElementById('progressPanel');
    if (!panel) return;
    
    const step = panel.querySelector(`.step-item[data-step="${stepName}"]`);
    if (step) {
        // Remove all status classes and add the new one
        step.classList.remove('pending', 'active', 'completed');
        step.classList.add(status);
        
        // Update cumulative data if provided
        if (data) {
            updateStepData(step, data);
        }
    }
}

/**
 * 重置所有进度步骤到初始状态
 */
function resetProgressSteps() {
    const steps = ['init', 'analysis', 'planning', 'reviewing', 'reporting'];
    steps.forEach(step => setProgressStep(step, 'pending'));
}

/**
 * Update the cumulative data display for a progress step.
 * 
 * @param {HTMLElement} stepElement - The step element to update
 * @param {Object} data - The data to display
 */
function updateStepData(stepElement, data) {
    let dataContainer = stepElement.querySelector('.step-data');
    
    // Create data container if it doesn't exist
    if (!dataContainer) {
        dataContainer = document.createElement('div');
        dataContainer.className = 'step-data';
        const stepInfo = stepElement.querySelector('.step-info');
        if (stepInfo) {
            stepInfo.appendChild(dataContainer);
        }
    }
    
    // Build data items HTML
    let dataHtml = '';
    
    if (data.filesScanned !== undefined) {
        dataHtml += `<div class="step-data-item">
            <span class="data-label">已扫描:</span>
            <span class="data-value">${data.filesScanned} 个文件</span>
        </div>`;
    }
    
    if (data.issuesFound !== undefined) {
        dataHtml += `<div class="step-data-item">
            <span class="data-label">发现问题:</span>
            <span class="data-value">${data.issuesFound} 个</span>
        </div>`;
    }
    
    if (data.duration !== undefined) {
        const seconds = (data.duration / 1000).toFixed(1);
        dataHtml += `<div class="step-data-item">
            <span class="data-label">耗时:</span>
            <span class="data-value">${seconds}s</span>
        </div>`;
    }
    
    dataContainer.innerHTML = dataHtml;
}

/**
 * Reset all progress steps to pending state.
 * Sets the first step (init) to active.
 */
function resetProgress() {
    const steps = document.querySelectorAll('.step-item');
    steps.forEach(step => {
        step.classList.remove('active', 'completed');
        step.classList.add('pending');
        
        // Clear any cumulative data
        const dataContainer = step.querySelector('.step-data');
        if (dataContainer) {
            dataContainer.innerHTML = '';
        }
    });
    setProgressStep('init', 'active');
}

function toggleProgressPanel(show) {
    const progressPanel = document.getElementById('progressPanel');
    const reportPanel = document.getElementById('reportPanel');
    const workbench = document.getElementById('page-review');
    
    if (show) {
        if (progressPanel) progressPanel.style.display = 'flex';
        if (reportPanel) reportPanel.style.display = 'none';
        if (workbench) workbench.classList.add('split-view');
    } else {
        if (progressPanel) progressPanel.style.display = 'none';
        // reportPanel visibility is handled separately or by switching to report mode
    }
}

/**
 * Toggle the log summary panel collapsed state.
 */
function toggleLogSummary() {
    const workflowPanel = document.getElementById('workflowPanel');
    if (workflowPanel) {
        workflowPanel.classList.toggle('collapsed');
    }
}

function toggleMonitorPanel() {
    const monitorPanel = document.getElementById('monitorPanel');
    if (monitorPanel) {
        monitorPanel.classList.toggle('collapsed');
    }
}

function toggleToolsPanel() {
    const inputArea = document.querySelector('.input-area');
    if (!inputArea) return;
    inputArea.classList.toggle('collapsed');
}

/**
 * Trigger the completion transition animation sequence.
 * This function orchestrates the transition from reviewing state to completed state:
 * 1. Marks all progress nodes as completed in sequence
 * 2. Shrinks the right panel
 * 3. Expands the left report panel
 * 
 * @param {string} reportContent - The final report content to display
 * @param {number} score - Optional score to display with animation (0-100)
 * 
 * Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
 */
async function triggerCompletionTransition(reportContent, score = null, alreadySwitched = false) {
    const steps = ['init', 'analysis', 'planning', 'reviewing', 'reporting'];
    
    // Step 1: Mark all nodes as completed
    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        setProgressStep(step, 'completed');
        if (!alreadySwitched) await new Promise(resolve => setTimeout(resolve, 50));
    }
    
    if (!alreadySwitched) {
        await new Promise(resolve => setTimeout(resolve, 200));
    }
    
    // Step 3: Update report panel content (if not already updated via stream)
    if (reportContainer && reportContent) {
        reportContainer.innerHTML = marked.parse(reportContent);
    }
    
    // Add score display if provided (Requirement 4.6)
    if (reportContainer && score !== null && !document.getElementById('scoreValue')) {
        const scoreHtml = `
            <div class="report-score">
                <span class="score-value" id="scoreValue">0</span>
                <span class="score-label">/ 100 分</span>
            </div>
        `;
        reportContainer.insertAdjacentHTML('afterbegin', scoreHtml);
        
        // Trigger score animation after a short delay
        setTimeout(() => {
            animateScore(score);
        }, 300);
    }
    
    // Step 4: Transition to completed layout state (Requirement 4.3, 4.4, 4.5)
    if (!alreadySwitched) {
        setLayoutState(LayoutState.COMPLETED);
    }
    
    console.log('Completion transition triggered');
}

/**
 * Mark all progress steps as completed.
 * Used for immediate completion without animation.
 */
function markAllStepsCompleted() {
    const steps = ['init', 'analysis', 'planning', 'reviewing', 'reporting'];
    steps.forEach(step => {
        setProgressStep(step, 'completed');
    });
}

/**
 * Animate a score value from 0 to the target score.
 * Uses requestAnimationFrame for smooth 60fps animation.
 * 
 * @param {number} targetScore - The final score to animate to (0-100)
 * @param {number} duration - Animation duration in milliseconds (default: 1000ms)
 * 
 * Requirements: 4.6
 */
function animateScore(targetScore, duration = 1000) {
    const scoreElement = document.getElementById('scoreValue');
    if (!scoreElement) return;
    
    // Check for reduced motion preference
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) {
        // Skip animation, show final value immediately
        scoreElement.textContent = Math.round(targetScore);
        return;
    }
    
    const startTime = performance.now();
    const startValue = 0;
    const endValue = Math.min(100, Math.max(0, targetScore)); // Clamp to 0-100
    
    scoreElement.classList.add('animating');
    
    function updateScore(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        // Use easeOutQuart for a satisfying deceleration effect
        const easeProgress = 1 - Math.pow(1 - progress, 4);
        
        const currentValue = Math.round(startValue + (endValue - startValue) * easeProgress);
        scoreElement.textContent = currentValue;
        
        if (progress < 1) {
            requestAnimationFrame(updateScore);
        } else {
            // Animation complete
            scoreElement.classList.remove('animating');
            scoreElement.textContent = Math.round(endValue);
        }
    }
    
    requestAnimationFrame(updateScore);
}

async function startReview() {
    if (!currentProjectRoot) {
        showToast("请先选择项目文件夹！", "error");
        return;
    }

    // Switch to review tab
    switchPage('review');
    
    // UI State
    if (startReviewBtn) {
        startReviewBtn.disabled = true;
        startReviewBtn.innerHTML = `<span class="spinner"></span>`;
    }

    // Update Project Info Header in Right Panel
    const reviewProjectPath = document.getElementById('reviewProjectPath');
    if (reviewProjectPath) {
        reviewProjectPath.textContent = currentProjectRoot;
        reviewProjectPath.title = currentProjectRoot; // Add tooltip for long paths
    }

    // 直接切换到完成布局（左侧报告、右侧进度与工作流）
    setLayoutState(LayoutState.COMPLETED);
    if (reportContainer) {
        reportContainer.innerHTML = `<div class="empty-state"><p>正在生成审查报告，大约需要 3-5 分钟</p></div>`;
    }
    
    // 清空右侧工作流面板（避免显示历史会话内容）
    const workflowEntries = document.getElementById('workflowEntries');
    if (workflowEntries) {
        workflowEntries.innerHTML = '';
    }
    
    // Reset and initialize progress steps
    resetProgress();
    setProgressStep('init', 'completed');
    setProgressStep('analysis', 'active');

    startReviewTimer();

    if (!currentSessionId) {
        currentSessionId = generateSessionId();
        setLastSessionId(currentSessionId);
    }
    
    // 标记任务开始 - 必须在发起请求之前设置，这样会话列表才能立即显示运行状态
    startReviewTask(currentSessionId);
    // 标记流正在活动
    SessionState.reviewStreamActive = true;

    const tools = Array.from(document.querySelectorAll('#toolListContainer input:checked')).map(cb => cb.value);
    const agents = null; 
    const autoApprove = autoApproveInput ? autoApproveInput.checked : false;
    
    try {
        const response = await fetch("/api/review/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                project_root: currentProjectRoot,
                model: currentModelValue,
                tools: tools,
                agents: agents,
                autoApprove: autoApprove,
                session_id: currentSessionId
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        await handleSSEResponse(response, currentSessionId);

    } catch (e) {
        console.error("Start review error:", e);
        addSystemMessage("启动审查失败: " + escapeHtml(e.message));
        
        // Reset layout state on error
        setLayoutState(LayoutState.INITIAL);
        
        // 清理运行状态
        SessionState.reviewStreamActive = false;
        endReviewTask();
        
        if (startReviewBtn) {
            startReviewBtn.disabled = false;
            startReviewBtn.innerHTML = `${getIcon('send')}`;
        }
    }
}

async function sendMessage() {
    if (!promptInput) return;
    const text = promptInput.value.trim();
    if (!text) return;
    
    promptInput.value = "";
    addMessage("user", escapeHtml(text));

    // Ensure session
    if (!currentSessionId) {
        currentSessionId = generateSessionId();
        setLastSessionId(currentSessionId);
    }

    const tools = Array.from(document.querySelectorAll('#toolListContainer input:checked')).map(cb => cb.value);
    const autoApprove = autoApproveInput ? autoApproveInput.checked : false;

    try {
        const response = await fetch("/api/chat/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: currentSessionId,
                message: text,
                project_root: currentProjectRoot,
                model: currentModelValue,
                tools: tools,
                autoApprove: autoApprove
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        await handleSSEResponse(response, currentSessionId);

    } catch (e) {
        console.error("Send message error:", e);
        addMessage("system", `<p>发送失败: ${escapeHtml(e.message)}</p>`);
    }
}

/**
 * Route SSE event to the workflow panel.
 * All events (intent, planner, review) are displayed in the right workflow panel.
 * Only final report goes to the left report panel.
 * 
 * @param {Object} evt - The SSE event object
 * @returns {string} - Always 'workflow' for streaming events
 */
function routeEvent(evt) {
    // 简化设计：所有流式事件统一路由到右侧工作流面板
    // 只有 final 类型事件会渲染到左侧报告面板
    return 'workflow';
}

async function handleSSEResponse(response, expectedSessionId = null) {
    if (!response.body) {
        console.error("Response body is null");
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // Right panel workflow container - 所有流式信息展示区
    const workflowContent = document.querySelector('#workflowPanel .workflow-content');
    const workflowEntries = document.getElementById('workflowEntries') || workflowContent;
    if (workflowEntries) {
        workflowEntries.innerHTML = '';
    }
    const monitorContainer = document.querySelector('#monitorPanel .workflow-content');
    const monitorEntries = document.getElementById('monitorContent') || monitorContainer;
    if (monitorEntries) monitorEntries.innerHTML = '';
    
    // Left panel - Report Canvas container (仅用于最终报告)
    const reportCanvasContainer = document.getElementById('reportContainer');

    // Track accumulated content for final report
    let finalReportContent = '';
    let pendingChunkContent = '';  // 待确认的 review 阶段 chunk（可能是工具调用解释）
    let streamEnded = false;
    const sid = expectedSessionId || currentSessionId;
    stopSessionPolling();
    SessionState.reviewStreamActive = true;
    
    // 当前阶段追踪，用于分组显示
    let currentStage = null;
    let fallbackSeen = false;

    function createFoldItem(container, iconName, titleText, collapsed) {
        const item = document.createElement('div');
        item.className = 'fold-item' + (collapsed ? ' collapsed' : '');
        const header = document.createElement('div');
        header.className = 'fold-header';
        header.innerHTML = `<div class="title">${getIcon(iconName)}${titleText ? `<span>${escapeHtml(titleText)}</span>` : ''}</div><svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>`;
        const body = document.createElement('div');
        body.className = 'fold-body';
        item.appendChild(header);
        item.appendChild(body);
        header.onclick = () => { item.classList.toggle('collapsed'); };
        container.appendChild(item);
        return body;
    }

    // 当前阶段的流式内容元素
    let currentChunkEl = null;
    // 当前阶段的思考流元素
    let currentThoughtEl = null;
    
    /**
     * 获取阶段的显示信息
     */
    function getStageInfo(stage) {
        const stageMap = {
            'intent': { title: '意图分析', icon: 'bot', color: '#6366f1' },
            'planner': { title: '审查规划', icon: 'plan', color: '#8b5cf6' },
            'review': { title: '代码审查', icon: 'review', color: '#10b981' },
            'default': { title: '处理中', icon: 'settings', color: '#64748b' }
        };
        return stageMap[stage] || stageMap['default'];
    }
    
    /**
     * 创建可折叠的阶段分隔标题
     */
    function createStageHeader(stage) {
        const info = getStageInfo(stage);
        const header = document.createElement('div');
        header.className = 'workflow-stage-section';
        header.dataset.stage = stage;
        header.innerHTML = `
            <div class="stage-header collapsible" onclick="toggleStageSection(this)">
                <div class="stage-indicator" style="--stage-color: ${info.color}">
                    ${getIcon(info.icon)}
                    <span>${info.title}</span>
                </div>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="stage-content"></div>
        `;
        return header;
    }

    /**
     * 获取当前阶段的内容容器
     */
    function getCurrentStageContent() {
        const sections = workflowEntries.querySelectorAll('.workflow-stage-section');
        const lastSection = sections[sections.length - 1];
        return lastSection ? lastSection.querySelector('.stage-content') : workflowEntries;
    }
    
    // 思考过程计时器相关
    let thoughtStartTime = null;
    let thoughtTimerInterval = null;
    
    function startThoughtTimer(timerEl) {
        thoughtStartTime = Date.now();
        if (thoughtTimerInterval) clearInterval(thoughtTimerInterval);
        thoughtTimerInterval = setInterval(() => {
            if (timerEl && thoughtStartTime) {
                const elapsed = Math.floor((Date.now() - thoughtStartTime) / 1000);
                const mins = Math.floor(elapsed / 60);
                const secs = elapsed % 60;
                timerEl.textContent = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
            }
        }, 1000);
    }
    
    function stopThoughtTimer() {
        if (thoughtTimerInterval) {
            clearInterval(thoughtTimerInterval);
            thoughtTimerInterval = null;
        }
    }

    /**
     * 统一的工作流内容追加函数
     * - review 阶段的报告内容同时输出到左侧报告面板
     * - 其他阶段的信息显示在右侧工作流面板（可折叠）
     */
    function appendToWorkflow(evt) {
        if (!workflowEntries) return;
        
        const stage = evt.stage || 'review';
        
        // 阶段切换时添加分隔标题
        if (stage !== currentStage) {
            currentStage = stage;
            currentChunkEl = null;
            currentThoughtEl = null;
            stopThoughtTimer(); // 阶段切换时停止计时器
            workflowEntries.appendChild(createStageHeader(stage));
        }
        
        // 获取当前阶段的内容容器
        const stageContent = getCurrentStageContent();
        
        // 处理思考过程
        if (evt.type === 'thought') {
            const thoughtText = (evt.content || '').trim();
            if (!thoughtText) {
                return;
            }
            if (!currentThoughtEl) {
                currentThoughtEl = document.createElement('div');
                currentThoughtEl.className = 'workflow-thought collapsed';
                currentThoughtEl.innerHTML = `
                    <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                        ${getIcon('bot')}
                        <span>思考过程</span>
                        <span class="thought-timer">0s</span>
                        <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                    </div>
                    <div class="thought-body"><pre class="thought-text"></pre></div>
                `;
                stageContent.appendChild(currentThoughtEl);
                // 启动计时器
                const timerEl = currentThoughtEl.querySelector('.thought-timer');
                startThoughtTimer(timerEl);
            }
            const textEl = currentThoughtEl.querySelector('.thought-text');
            textEl.textContent = (textEl.textContent || '') + thoughtText;
            workflowEntries.scrollTop = workflowEntries.scrollHeight;
            return;
        }

        // 处理流式内容输出
        if (evt.type === 'chunk') {
            // 停止思考计时器（chunk 表示思考结束）
            stopThoughtTimer();
            
            // Review 阶段的 chunk 需要特殊处理
            // 策略：先累积，不直接显示在右侧
            // - 如果之后收到工具调用，将累积内容作为"工具解释"显示在右侧
            // - 如果审查结束，将累积内容作为"最终报告"只显示在左侧
            if (stage === 'review') {
                // 确保切换到 completed 布局
                if (getLayoutState() !== LayoutState.COMPLETED) {
                    setLayoutState(LayoutState.COMPLETED);
                    setProgressStep('analysis', 'completed');
                    setProgressStep('planning', 'completed');
                    setProgressStep('reviewing', 'active');
                }
                
                const chunkContent = evt.content || '';
                
                // 只累积到待确认区域，不在右侧显示
                // 等待后续事件来决定这些内容的用途
                pendingChunkContent += chunkContent;
                
                // 实时预览到左侧（但这些内容可能会在工具调用时被撤销）
                if (reportCanvasContainer) {
                    reportCanvasContainer.innerHTML = marked.parse(finalReportContent + pendingChunkContent);
                    reportCanvasContainer.scrollTop = reportCanvasContainer.scrollHeight;
                }
                return;
            }
            
            // 非 review 阶段的 chunk 显示在可折叠的内容块中（planner 阶段显示为“上下文决策”）
            if (!currentChunkEl) {
                const wrapper = document.createElement('div');
                wrapper.className = 'workflow-chunk-wrapper collapsed';
                const chunkTitle = stage === 'planner' ? '上下文决策' : '输出内容';
                wrapper.innerHTML = `
                    <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                        ${getIcon('folder')}
                        <span>${chunkTitle}</span>
                        <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                    </div>
                    <div class="chunk-body">
                        <div class="workflow-chunk markdown-body"></div>
                    </div>
                `;
                stageContent.appendChild(wrapper);
                currentChunkEl = wrapper.querySelector('.workflow-chunk');
                currentChunkEl.dataset.fullText = '';
            }
            
            currentChunkEl.dataset.fullText += (evt.content || '');
            currentChunkEl.innerHTML = marked.parse(currentChunkEl.dataset.fullText);
            workflowEntries.scrollTop = workflowEntries.scrollHeight;
            return;
        }

        // 重置流式元素（非流式事件到来时）
        currentChunkEl = null;
        stopThoughtTimer();

        // 处理工具调用
        if (evt.type === 'tool_start' || evt.type === 'tool_call_start') {
            currentThoughtEl = null; // 工具调用后重置思考元素
            currentChunkEl = null; // 重置 chunk 元素
            
            // 工具调用发生，说明之前的 pendingChunkContent 是工具调用解释
            // 将其作为工具解释显示在右侧，与工具调用串联
            if (stage === 'review' && pendingChunkContent) {
                // 撤销左侧的预览，恢复到只显示已确认的报告内容
                if (reportCanvasContainer) {
                    reportCanvasContainer.innerHTML = finalReportContent 
                        ? marked.parse(finalReportContent) 
                        : '<div class="waiting-state"><p>等待审查结果...</p></div>';
                }
                
                // 只有当有实际内容时才显示解释块
                const trimmedContent = pendingChunkContent.trim();
                if (trimmedContent) {
                    const explanationEl = document.createElement('div');
                    explanationEl.className = 'workflow-tool-explanation';
                    explanationEl.innerHTML = `
                        <div class="tool-explanation-content markdown-body">
                            ${marked.parse(trimmedContent)}
                        </div>
                    `;
                    stageContent.appendChild(explanationEl);
                }
                
                // 清空待确认内容
                pendingChunkContent = '';
            }
            
            const toolEl = document.createElement('div');
            toolEl.className = 'workflow-tool';
            const argsText = evt.detail ? String(evt.detail) : '';
            toolEl.innerHTML = `
                <div class="tool-info">
                    ${getIcon('settings')}
                    <span class="tool-name">${escapeHtml(evt.tool || evt.tool_name || '未知工具')}</span>
                    ${argsText ? `<span class="tool-args">${escapeHtml(argsText)}</span>` : ''}
                </div>
            `;
            stageContent.appendChild(toolEl);
            workflowEntries.scrollTop = workflowEntries.scrollHeight;
            return;
        }
        
        // 处理其他类型的内容
        if (evt.content) {
            const block = document.createElement('div');
            block.className = 'workflow-block markdown-body';
            block.innerHTML = marked.parse(evt.content);
            stageContent.appendChild(block);
            workflowEntries.scrollTop = workflowEntries.scrollHeight;
        }
    }

    // 定期保存UI状态的节流计时器
    let saveStateTimer = null;
    const SAVE_STATE_INTERVAL = 500; // 每500ms保存一次
    
    function scheduleSaveState() {
        if (saveStateTimer) return;
        saveStateTimer = setTimeout(() => {
            saveRunningUISnapshot();
            saveStateTimer = null;
        }, SAVE_STATE_INTERVAL);
    }
    
    /**
     * 处理 SSE 事件
     * 简化设计：所有流式信息统一路由到右侧工作流面板
     */
    const processEvent = (evt) => {
        // 定期保存UI状态，便于切换后恢复
        scheduleSaveState();
        
        const stage = evt.stage || 'review';

        // 更新进度指示器
        if (evt.type === 'thought' || evt.type === 'tool_start' || evt.type === 'chunk') {
            if (stage === 'intent') {
                setProgressStep('analysis', 'active');
            } else if (stage === 'review') {
                setProgressStep('analysis', 'completed');
                setProgressStep('planning', 'completed');
                setProgressStep('reviewing', 'active');
                // 当 review 阶段开始时，切换到 completed 布局以显示左侧报告面板
                if (getLayoutState() !== LayoutState.COMPLETED) {
                    setLayoutState(LayoutState.COMPLETED);
                }
            } else if (stage === 'planner') {
                setProgressStep('analysis', 'completed');
                setProgressStep('planning', 'active');
            }
        }

        // 处理管道阶段开始/结束事件
        if (evt.type === 'pipeline_stage_start') {
            const pipelineStage = evt.stage;
            
            // 根据 pipeline 阶段更新进度
            if (pipelineStage === 'intent_analysis') {
                setProgressStep('analysis', 'active');
            } else if (pipelineStage === 'planner') {
                setProgressStep('analysis', 'completed');
                setProgressStep('planning', 'active');
            } else if (pipelineStage === 'fusion' || pipelineStage === 'context_provider' || pipelineStage === 'reviewer') {
                setProgressStep('analysis', 'completed');
                setProgressStep('planning', 'completed');
                setProgressStep('reviewing', 'active');
                // 切换到 completed 布局以显示左侧报告面板
                if (getLayoutState() !== LayoutState.COMPLETED) {
                    setLayoutState(LayoutState.COMPLETED);
                }
            }
            return;
        }
        
        if (evt.type === 'pipeline_stage_end') {
            const pipelineStage = evt.stage;
            
            // 阶段完成后更新进度
            if (pipelineStage === 'intent_analysis') {
                setProgressStep('analysis', 'completed');
            } else if (pipelineStage === 'planner') {
                setProgressStep('planning', 'completed');
            } else if (pipelineStage === 'reviewer') {
                setProgressStep('reviewing', 'completed');
                setProgressStep('reporting', 'active');
            }
            return;
        }
        
        // 忽略 bundle_item 事件（仅用于内部跟踪）
        if (evt.type === 'bundle_item') {
            return;
        }

        // 统一路由到工作流面板
        if (evt.type === 'thought' || evt.type === 'tool_start' || evt.type === 'chunk' || evt.type === 'workflow_chunk' || evt.type === 'tool_call_start') {
            appendToWorkflow(evt);
            return;
        }

        if (evt.type === 'delta') {
            const stageContent = getCurrentStageContent();
            const reasoning = (evt.reasoning_delta || '').trim();
            const contentDelta = evt.content_delta || '';
            const callsRaw = evt.tool_calls_delta;
            const calls = Array.isArray(callsRaw) ? callsRaw : (callsRaw ? [callsRaw] : []);

            if (calls.length) {
                // 工具调用发生，说明之前的 pendingChunkContent 是工具调用解释
                if (stage === 'review' && pendingChunkContent) {
                    // 撤销左侧的预览，恢复到只显示已确认的报告内容
                    if (reportCanvasContainer) {
                        reportCanvasContainer.innerHTML = finalReportContent 
                            ? marked.parse(finalReportContent) 
                            : '<div class="waiting-state"><p>等待审查结果...</p></div>';
                    }
                    
                    // 只有当有实际内容时才显示解释块
                    const trimmedContent = pendingChunkContent.trim();
                    if (trimmedContent) {
                        const explanationEl = document.createElement('div');
                        explanationEl.className = 'workflow-tool-explanation';
                        explanationEl.innerHTML = `
                            <div class="tool-explanation-content markdown-body">
                                ${marked.parse(trimmedContent)}
                            </div>
                        `;
                        stageContent.appendChild(explanationEl);
                    }
                    
                    // 清空待确认内容
                    pendingChunkContent = '';
                }
                
                // 重置 chunk 元素
                currentChunkEl = null;
                
                for (const call of calls) {
                    const fn = (typeof call.function === 'object') ? call.function : {};
                    const name = fn.name || call.name || '未知工具';
                    const argText = fn.arguments || '';
                    let detail = '';
                    try {
                        const j = JSON.parse(argText);
                        if (j && typeof j === 'object') {
                            const keys = Object.keys(j).slice(0, 3);
                            detail = keys.map(k => `${k}=${String(j[k]).slice(0, 80)}`).join(', ');
                        } else {
                            detail = String(j).slice(0, 200);
                        }
                    } catch {
                        detail = String(argText).slice(0, 200);
                    }
                    const toolEl = document.createElement('div');
                    toolEl.className = 'workflow-tool';
                    toolEl.innerHTML = `
                        <div class="tool-info">
                            ${getIcon('settings')}
                            <span class="tool-name">${escapeHtml(name)}</span>
                            ${detail ? `<span class="tool-args">${escapeHtml(detail)}</span>` : ''}
                        </div>
                    `;
                    stageContent.appendChild(toolEl);
                }
            }

            if (reasoning) {
                if (!currentThoughtEl) {
                    currentThoughtEl = document.createElement('div');
                    currentThoughtEl.className = 'workflow-thought collapsed';
                    currentThoughtEl.innerHTML = `
                        <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                            ${getIcon('bot')}
                            <span>思考过程</span>
                            <span class="thought-timer">0s</span>
                            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                        </div>
                        <div class="thought-body"><pre class="thought-text"></pre></div>
                    `;
                    stageContent.appendChild(currentThoughtEl);
                    const timerEl = currentThoughtEl.querySelector('.thought-timer');
                    startThoughtTimer(timerEl);
                }
                const textEl = currentThoughtEl.querySelector('.thought-text');
                textEl.textContent = (textEl.textContent || '') + reasoning;
            }

            if (contentDelta) {
                if (stage === 'review') {
                    if (getLayoutState() !== LayoutState.COMPLETED) {
                        setLayoutState(LayoutState.COMPLETED);
                        setProgressStep('analysis', 'completed');
                        setProgressStep('planning', 'completed');
                        setProgressStep('reviewing', 'active');
                    }
                    
                    // 只累积到待确认区域，不在右侧显示
                    // 策略：等待后续事件来决定这些内容的用途
                    // - 如果之后收到工具调用，将累积内容作为"工具解释"显示在右侧
                    // - 如果审查结束，将累积内容作为"最终报告"只显示在左侧
                    pendingChunkContent += contentDelta;
                    
                    // 实时预览到左侧（但这些内容可能会在工具调用时被撤销）
                    if (reportCanvasContainer) {
                        reportCanvasContainer.innerHTML = marked.parse(finalReportContent + pendingChunkContent);
                        reportCanvasContainer.scrollTop = reportCanvasContainer.scrollHeight;
                    }
                } else {
                    if (!currentChunkEl) {
                        const wrapper = document.createElement('div');
                        wrapper.className = 'workflow-chunk-wrapper collapsed';
                        wrapper.innerHTML = `
                            <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                                ${getIcon('folder')}
                                <span>输出内容</span>
                                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                            </div>
                            <div class="chunk-body">
                                <div class="workflow-chunk markdown-body"></div>
                            </div>
                        `;
                        stageContent.appendChild(wrapper);
                        currentChunkEl = wrapper.querySelector('.workflow-chunk');
                        currentChunkEl.dataset.fullText = '';
                    }
                    currentChunkEl.dataset.fullText += contentDelta;
                    currentChunkEl.innerHTML = marked.parse(currentChunkEl.dataset.fullText);
                }
            }

            workflowEntries.scrollTop = workflowEntries.scrollHeight;
            return;
        }

        if (evt.type === 'warning' && monitorEntries) {
            // **Feature: review-workflow-display, Requirement 2.3: 回退监控展示**
            // Uses warning/info color scheme for fallback statistics
            const s = evt.fallback_summary || {};
            const container = document.createElement('div');
            container.className = 'fallback-summary';
            
            const total = s.total || 0;
            const byKey = s.by_key || {};
            const byPriority = s.by_priority || {};
            const byCategory = s.by_category || {};
            
            let html = `
                <div class="summary-header">
                    ${getIcon('clock')}
                    <span>回退统计</span>
                </div>
                <div class="summary-stat">
                    <span class="stat-label">总回退次数</span>
                    <span class="stat-value">${total}</span>
                </div>
            `;
            
            // By Key statistics with badges
            if (Object.keys(byKey).length) {
                html += '<div class="summary-stat"><span class="stat-label">按键统计</span></div>';
                html += '<div style="padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                for (const [k, v] of Object.entries(byKey)) {
                    html += `<span class="fallback-badge warning">${escapeHtml(k)}: ${v}</span>`;
                }
                html += '</div>';
            }
            
            // By Priority statistics with color-coded badges
            if (Object.keys(byPriority).length) {
                html += '<div class="summary-stat"><span class="stat-label">按优先级</span></div>';
                html += '<div style="padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                for (const [k, v] of Object.entries(byPriority)) {
                    const badgeClass = k.toLowerCase().includes('high') ? 'error' : 
                                       k.toLowerCase().includes('low') ? 'info' : 'warning';
                    html += `<span class="fallback-badge ${badgeClass}">${escapeHtml(k)}: ${v}</span>`;
                }
                html += '</div>';
            }
            
            // By Category statistics
            if (Object.keys(byCategory).length) {
                html += '<div class="summary-stat"><span class="stat-label">按分类</span></div>';
                html += '<div style="padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                for (const [k, v] of Object.entries(byCategory)) {
                    html += `<span class="fallback-badge info">${escapeHtml(k)}: ${v}</span>`;
                }
                html += '</div>';
            }
            
            container.innerHTML = html;
            monitorEntries.appendChild(container);
            
            const monitorPanel = document.getElementById('monitorPanel');
            fallbackSeen = true;
            if (monitorPanel) {
                monitorPanel.classList.remove('ok');
                const titleEl = monitorPanel.querySelector('.panel-title');
                if (titleEl) titleEl.textContent = '日志';
                if (monitorPanel.classList.contains('collapsed')) {
                    monitorPanel.classList.remove('collapsed');
                }
            }
            
            return;
        }

        if (evt.type === 'usage_summary' && monitorEntries) {
            const call = evt.call_usage || {};
            const totals = evt.session_usage || {};
            const stageText = evt.usage_stage || '';
            const callIndex = evt.call_index;
            const item = document.createElement('div');
            item.className = 'process-item';
            const idx = (callIndex !== undefined && callIndex !== null) ? `#${callIndex}` : '';
            item.innerHTML = `
                <div><strong>API调用 ${idx}</strong>${stageText ? ` · ${escapeHtml(stageText)}` : ''}</div>
                <ul>
                    <li>本次 tokens: 总计 ${call.total ?? '-'}（入 ${call.in ?? '-'}，出 ${call.out ?? '-'})</li>
                    <li>会话累计: 总计 ${totals.total ?? '-'}（入 ${totals.in ?? '-'}，出 ${totals.out ?? '-'})</li>
                </ul>
            `;
            monitorEntries.appendChild(item);
            return;
        }

        if (evt.type === 'final') {
            setProgressStep('reviewing', 'completed');
            setProgressStep('reporting', 'active');
            
            // 将待确认的内容加入最终报告（因为没有工具调用，这些就是报告内容）
            if (pendingChunkContent) {
                finalReportContent += pendingChunkContent;
                pendingChunkContent = '';
            }
            
            // Use final content or accumulated content
            const finalContent = evt.content || finalReportContent;
            
            // Render final report to report panel
            if (reportCanvasContainer) {
                reportCanvasContainer.innerHTML = marked.parse(finalContent);
            }
            
            let score = null;
            const scoreMatch = finalContent.match(/(?:评分|Score|分数)[:\s]*(\d+)/i);
            if (scoreMatch) score = parseInt(scoreMatch[1], 10);
            triggerCompletionTransition(null, score, true);
            const monitorPanel = document.getElementById('monitorPanel');
            if (monitorPanel && !fallbackSeen) {
                monitorPanel.classList.add('ok');
                const titleEl = monitorPanel.querySelector('.panel-title');
                if (titleEl) titleEl.textContent = '日志 · 运行正常';
            }
            stopReviewTimer();
            streamEnded = true;
            return;
        }

        if (evt.type === 'error') {
            // 在工作流面板显示错误
            if (workflowEntries) {
                const errorEl = document.createElement('div');
                errorEl.className = 'workflow-error';
                errorEl.innerHTML = `
                    <div class="error-icon">${getIcon('x')}</div>
                    <div class="error-content">
                        <strong>发生错误</strong>
                        <p>${escapeHtml(evt.message || '未知错误')}</p>
                    </div>
                `;
                workflowEntries.appendChild(errorEl);
            }
            stopReviewTimer();
            streamEnded = true;
            // 错误时也要标记任务结束
            SessionState.reviewStreamActive = false;
            endReviewTask();
            return;
        }

        if (evt.type === 'done') {
            stopReviewTimer();
            streamEnded = true;
            setProgressStep('reporting', 'completed');
            // 标记流结束和任务完成
            SessionState.reviewStreamActive = false;
            endReviewTask();
            loadSessions(); // 刷新会话列表，移除运行状态
            return;
        }
    };

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop() || '';
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const evt = JSON.parse(line.slice(6));
                        if (currentSessionId !== sid) { streamEnded = true; break; }
                        processEvent(evt);
                        if (streamEnded) break;
                    } catch (e) {
                        console.error('SSE Parse Error', e, line);
                    }
                }
            }
            if (streamEnded) break;
        }

        if (buffer && buffer.startsWith('data: ')) {
            try {
                const evt = JSON.parse(buffer.slice(6));
                processEvent(evt);
            } catch (e) {
                // ignore
            }
        }
    } catch (e) {
        console.error('SSE Stream Error', e);
        // 在工作流面板显示连接错误
        if (workflowEntries) {
            const errorEl = document.createElement('div');
            errorEl.className = 'workflow-error';
            errorEl.innerHTML = `
                <div class="error-icon">${getIcon('x')}</div>
                <div class="error-content">
                    <strong>连接中断</strong>
                    <p>${escapeHtml(e.message)}</p>
                    <button class="retry-btn" onclick="startReview()">重试</button>
                </div>
            `;
            workflowEntries.appendChild(errorEl);
        }
        // 重置布局状态
        setLayoutState(LayoutState.INITIAL);
        stopReviewTimer();
    }

    if (startReviewBtn) {
        SessionState.reviewStreamActive = false;
        startReviewBtn.disabled = false;
        startReviewBtn.innerHTML = `${getIcon('send')}`;
    }
    
    // 标记任务结束
    endReviewTask();
}

// --- UI Helpers ---

function addMessage(role, content, id=null) {
    if (!messageContainer) return;
    
    const div = document.createElement("div");
    div.className = `message ${role}-message`;
    if(id) div.id = id;
    
    const icon = role === 'user' ? 'user' : 'bot';
    
    div.innerHTML = `
        <div class="avatar">${getIcon(icon)}</div>
        <div class="message-body">
            <div class="content">${content}</div>
        </div>
    `;
    messageContainer.appendChild(div);
    messageContainer.scrollTop = messageContainer.scrollHeight;
}

function addSystemMessage(text) {
    // 注意：text 可能包含已转义的 HTML，这里不再转义
    // 调用者需要确保 text 是安全的
    addMessage("system", `<p>${text}</p>`);
}

function toggleHistoryDrawer() {
    if (historyDrawer) {
        const isOpening = !historyDrawer.classList.contains("open");
        historyDrawer.classList.toggle("open");
        // 打开时自动刷新会话列表
        if (isOpening) {
            loadSessions();
        }
    }
}

function toggleModelDropdown(e) {
    e.stopPropagation();
    if (modelDropdown) modelDropdown.classList.toggle('open');
}

// --- Session Management ---

async function loadSessions() {
    try {
        const res = await fetch("/api/sessions/list");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const sessions = data.sessions || [];
        const lastSid = getLastSessionId();
        
        if(sessionListEl) {
            sessionListEl.innerHTML = "";
            if (sessions.length === 0) {
                sessionListEl.innerHTML = '<div class="empty-state" style="padding:1rem;font-size:0.85rem;">暂无历史会话</div>';
                return;
            }
            
            sessions.forEach(s => {
                const div = document.createElement("div");
                const isActive = s.session_id === currentSessionId;
                const isLast = s.session_id === lastSid;
                // 修复：运行状态应该基于 SessionState.runningSessionId，而不是后端返回的 status
                // 只有前端正在执行 SSE 流的会话才算真正的运行中
                const isRunning = s.session_id === getRunningSessionId();
                const classes = ['session-item'];
                if (isActive) classes.push('active');
                // 只有当不是运行中且不是当前活动会话时，才显示“上次”标签
                if (isLast && !isRunning && !isActive) classes.push('recent');
                if (isRunning) classes.push('running');
                div.className = classes.join(' ');
                div.dataset.sessionId = s.session_id;
                
                // 格式化日期显示
                const dateStr = s.updated_at ? new Date(s.updated_at).toLocaleString('zh-CN', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                }) : '';
                
                // 生成显示名称：优先使用 name，否则使用简化的 session_id
                const displayName = s.name || (s.session_id ? s.session_id.replace('sess_', '会话 ') : '未命名会话');
                
                // 生成状态徽章 - 优先级：运行中 > 当前活动 > 上次访问
                let badgeHTML = '';
                if (isRunning) {
                    badgeHTML = '<span class="session-badge running">进行中</span>';
                } else if (isActive) {
                    badgeHTML = '<span class="session-badge active">当前</span>';
                } else if (isLast) {
                    badgeHTML = '<span class="session-badge">上次</span>';
                }
                
                div.innerHTML = `
                    <div class="session-icon">${isRunning ? '<div class="spinner-small" style="width:20px;height:20px;border-width:2px;"></div>' : getIcon('clock')}</div>
                    <div class="session-info">
                        <span class="session-title" title="${escapeHtml(s.name || s.session_id)}">${escapeHtml(displayName)}${badgeHTML}</span>
                        <span class="session-date">${dateStr || '刚刚'}</span>
                    </div>
                    <div class="session-actions">
                        <button class="icon-btn-small rename-btn" title="重命名" onclick="event.stopPropagation(); renameSession('${s.session_id}', '${escapeHtml(s.name || '')}')">
                            ${getIcon('edit')}
                        </button>
                        <button class="icon-btn-small delete-btn" title="删除" onclick="event.stopPropagation(); deleteSession('${s.session_id}')">
                            ${getIcon('trash')}
                        </button>
                    </div>
                `;
                div.onclick = () => loadSession(s.session_id);
                sessionListEl.appendChild(div);
            });
            // 不再自动打开任何历史会话——页面初始应为无状态（用户需要手动点击历史记录以加载）
            // 保持 currentSessionId 不变（通常为 null），仅展示会话列表供用户选择
            await showLastSessionReminder();
        }
    } catch (e) { 
        console.error("Load sessions error:", e); 
        if(sessionListEl) {
            sessionListEl.innerHTML = `
                <div class="error-state" style="padding:1rem;text-align:center;">
                    <p style="color:#dc2626;margin-bottom:0.5rem;">加载失败</p>
                    <button class="btn-secondary btn-small" onclick="loadSessions()">重试</button>
                </div>
            `;
        }
    }
}

async function loadSession(sid) {
    // 情况1: 点击正在运行的任务会话 -> 恢复显示
    if (isReviewRunning() && getRunningSessionId() === sid) {
        currentSessionId = sid;
        setViewingHistory(false);
        updateSessionActiveState(sid);
        switchPage('review');
        setLayoutState(LayoutState.COMPLETED);
        restoreRunningUISnapshot();
        showToast("已返回正在进行的审查任务", "info");
        startSessionPolling(sid);
        return;
    }
    
    // 情况2: 有任务在运行，但切换到其他会话 -> 先保存快照
    if (isReviewRunning() && getRunningSessionId() !== sid) {
        saveRunningUISnapshot();
        showToast("后台任务继续在后台运行", "info");
    }
    
    // 切换到目标会话 - 先更新状态，避免后续操作触发不必要的逻辑
    currentSessionId = sid;
    setLastSessionId(sid);
    removeLastSessionReminder();
    
    // 进入历史查看模式（只读）
    setViewingHistory(true);
    updateSessionActiveState(sid);

    try {
        const res = await fetch(`/api/sessions/${sid}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        // 先分析数据，确定最终布局，避免多次DOM操作
        const messages = data.messages || [];
        const workflowEvents = data.workflow_events || [];
        const metadata = data.metadata || {};
        const sessionStatus = metadata.status || 'active';
        const hasWorkflowEvents = workflowEvents.length > 0;
        const isActiveSession = sessionStatus === 'active' || sessionStatus === 'reviewing';
        
        // 查找最后一个 assistant 消息（审查报告）
        let lastAssistantMessage = null;
        for (let i = messages.length - 1; i >= 0; i--) {
            if (messages[i].role === 'assistant' && messages[i].content) {
                lastAssistantMessage = messages[i];
                break;
            }
        }
        
        // 判断是否应该显示"审查进行中"布局
        // 条件：没有最终报告 && 有工作流事件（表示审查已经开始）
        // 注意：空会话（无工作流事件）不应该显示为"审查进行中"
        const shouldShowReviewingLayout = !lastAssistantMessage && hasWorkflowEvents;
        
        // 只在确定布局后才开始操作DOM
        messageContainer.innerHTML = "";

        // 如果有审查报告，切换到 COMPLETED 布局并显示报告
        if (lastAssistantMessage) {
            // 一次性切换到目标状态
            switchPage('review');
            setLayoutState(LayoutState.COMPLETED);
            
            // 在左侧报告面板显示报告内容
            const reportContainer = document.getElementById('reportContainer');
            if (reportContainer) {
                reportContainer.innerHTML = marked.parse(lastAssistantMessage.content);
            }
            
            // 在右侧工作流面板回放工作流事件
            const workflowEntries = document.getElementById('workflowEntries');
            
            if (workflowEntries) {
                workflowEntries.innerHTML = '';
                
                if (workflowEvents.length > 0) {
                    // 有工作流事件，回放显示
                    replayWorkflowEvents(workflowEntries, workflowEvents);
                } else {
                    // 没有工作流事件（旧会话），显示提示信息
                    const projectRoot = data.metadata?.project_root || '未知项目';
                    const projectName = projectRoot.split(/[/\\]/).pop() || projectRoot;
                    
                    workflowEntries.innerHTML = `
                        <div class="history-session-info">
                            <div class="history-header">
                                ${getIcon('clock')}
                                <span>历史审查记录</span>
                            </div>
                            <div class="history-details">
                                <div class="history-item">
                                    <span class="history-label">项目</span>
                                    <span class="history-value">${escapeHtml(projectName)}</span>
                                </div>
                                <div class="history-item">
                                    <span class="history-label">会话ID</span>
                                    <span class="history-value">${escapeHtml(sid)}</span>
                                </div>
                            </div>
                            <div class="history-note">
                                <p>这是一个旧版本的审查会话。</p>
                                <p>工作流详情未被记录。新的审查会话将保存完整的工作流信息。</p>
                            </div>
                        </div>
                    `;
                }
            }
            
            // 回放监控日志事件
            const monitorContent = document.getElementById('monitorContent');
            if (monitorContent && workflowEvents.length > 0) {
                monitorContent.innerHTML = '';
                replayMonitorEvents(monitorContent, workflowEvents);
            }
            
            // 标记所有进度步骤为完成
            setProgressStep('init', 'completed');
            setProgressStep('analysis', 'completed');
            setProgressStep('planning', 'completed');
            setProgressStep('reviewing', 'completed');
            setProgressStep('reporting', 'completed');
            
            // 更新项目路径
            if (data.metadata && data.metadata.project_root) {
                updateProjectPath(data.metadata.project_root);
            }
            return;
        }

        // 没有审查报告
        // 过滤掉 user 消息（历史残留），只显示 system 和 assistant 消息
        const displayMessages = messages.filter(msg => msg.role !== 'user');
        if (displayMessages.length > 0) {
            displayMessages.forEach(msg => {
                addMessage(msg.role, marked.parse(msg.content || ""));
            });
        }
        // 注意：空会话不再需要特殊处理，因为用户无法手动创建空会话

        const workflowEntries = document.getElementById('workflowEntries');
        if (shouldShowReviewingLayout) {
            // 切换到 COMPLETED 布局以显示左右两个面板
            // 左侧显示"进行中"提示，右侧显示已有的工作流事件
            setLayoutState(LayoutState.COMPLETED);
            if (reportContainer) {
                const updatedText = metadata.updated_at ? new Date(metadata.updated_at).toLocaleString('zh-CN', {
                    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                }) : '';
                reportContainer.innerHTML = `
                    <div class="empty-state" style="text-align:center; padding: 3rem;">
                        <div style="margin-bottom:1.5rem;">${getIcon('clock')}</div>
                        <h3 style="margin-bottom:0.5rem; color:var(--text-primary);">审查进行中</h3>
                        <p style="color:var(--text-secondary);">该审查尚未完成${updatedText ? `（上次更新 ${escapeHtml(updatedText)}）` : ''}。</p>
                        <p style="color:var(--text-secondary); font-size:0.85rem;">当审查完成后，报告将自动显示在此处。</p>
                    </div>
                `;
            }
            if (workflowEntries) {
                workflowEntries.innerHTML = '';
                if (hasWorkflowEvents) {
                    replayWorkflowEvents(workflowEntries, workflowEvents);
                } else {
                    workflowEntries.innerHTML = `
                        <div class="history-session-info">
                            <div class="history-header">
                                ${getIcon('clock')}
                                <span>审查进行中</span>
                            </div>
                            <div class="history-note">
                                <p>审查已启动，但尚未收到工作流事件。稍后再来查看。</p>
                            </div>
                        </div>
                    `;
                }
            }
            
            // 回放监控日志事件
            const monitorContent = document.getElementById('monitorContent');
            if (monitorContent && hasWorkflowEvents) {
                monitorContent.innerHTML = '';
                replayMonitorEvents(monitorContent, workflowEvents);
            }
            
            resetProgress();
            setProgressStep('init', 'completed');
            setProgressStep('analysis', hasWorkflowEvents ? 'completed' : 'active');
            if (hasWorkflowEvents) {
                setProgressStep('planning', 'active');
            }
            
            // 更新项目路径
            if (metadata.project_root) {
                currentProjectRoot = metadata.project_root;
                if (projectRootInput) projectRootInput.value = currentProjectRoot;
                if (currentPathLabel) currentPathLabel.textContent = currentProjectRoot;
                if (dashProjectPath) dashProjectPath.textContent = currentProjectRoot;
            }
            
            // 切换到审查页面
            switchPage('review');
            startSessionPolling(sid);
            return;
        } else {
            // 设置为初始布局状态
            setLayoutState(LayoutState.INITIAL);
        }
        
        // Update Project Root if saved in session
        if (data.metadata && data.metadata.project_root) {
            currentProjectRoot = data.metadata.project_root;
            if (projectRootInput) projectRootInput.value = currentProjectRoot;
            if (currentPathLabel) currentPathLabel.textContent = currentProjectRoot;
            if (dashProjectPath) dashProjectPath.textContent = currentProjectRoot;
        }

        // 切换到审查页面
        switchPage('review');
        
    } catch(e) { 
        console.error("Load session error:", e);
        addSystemMessage("加载会话失败: " + e.message);
    }
}

function stopSessionPolling() {
    if (SessionState.pollTimerId) {
        clearInterval(SessionState.pollTimerId);
        SessionState.pollTimerId = null;
    }
}

function startSessionPolling(sid) {
    stopSessionPolling();
    // 不在这里设置 runningSessionId，应该在任务真正开始时设置
    // SessionState.runningSessionId = sid;
    loadSessions();
    const pollOnce = async () => {
        // 如果流正在活动，或者当前会话已切换，停止轮询
        if (SessionState.reviewStreamActive || currentSessionId !== sid) return;
        try {
            const res = await fetch(`/api/sessions/${sid}`);
            if (!res.ok) return;
            const data = await res.json();
            const messages = data.messages || [];
            let lastAssistantMessage = null;
            for (let i = messages.length - 1; i >= 0; i--) {
                const m = messages[i];
                if (m.role === 'assistant' && m.content) { lastAssistantMessage = m; break; }
            }
            const workflowEvents = data.workflow_events || [];
            const metadata = data.metadata || {};
            const workflowEntries = document.getElementById('workflowEntries');
            const reportContainer = document.getElementById('reportContainer');
            const monitorContent = document.getElementById('monitorContent');
            if (lastAssistantMessage) {
                setLayoutState(LayoutState.COMPLETED);
                if (reportContainer) { reportContainer.innerHTML = marked.parse(lastAssistantMessage.content); }
                if (workflowEntries) { workflowEntries.innerHTML = ''; replayWorkflowEvents(workflowEntries, workflowEvents); }
                if (monitorContent) { monitorContent.innerHTML = ''; replayMonitorEvents(monitorContent, workflowEvents); }
                stopSessionPolling();
                // 标记任务完成
                endReviewTask();
                setProgressStep('reviewing', 'completed');
                setProgressStep('reporting', 'completed');
                loadSessions(); // 刷新会话列表以更新状态
                return;
            }
            if (workflowEntries) {
                workflowEntries.innerHTML = '';
                if (workflowEvents.length) {
                    replayWorkflowEvents(workflowEntries, workflowEvents);
                }
            }
            if (monitorContent && workflowEvents.length) {
                monitorContent.innerHTML = '';
                replayMonitorEvents(monitorContent, workflowEvents);
            }
            if (metadata.status === 'completed') {
                stopSessionPolling();
            }
        } catch (e) {}
    };
    pollOnce();
    SessionState.pollTimerId = setInterval(pollOnce, 2000);
}

/**
 * 回放工作流事件，用于显示历史会话的工作流信息
 * @param {HTMLElement} container - 工作流容器元素
 * @param {Array} events - 工作流事件数组
 */
function replayWorkflowEvents(container, events) {
    if (!container || !events || events.length === 0) return;
    
    // 按阶段分组事件
    const stageGroups = {};
    let currentStage = null;
    
    events.forEach(evt => {
        const stage = evt.stage || 'review';
        if (!stageGroups[stage]) {
            stageGroups[stage] = [];
        }
        stageGroups[stage].push(evt);
    });
    
    // 阶段配置
    const stageConfig = {
        'intent': { title: '意图分析', icon: 'bot', color: '#6366f1' },
        'planner': { title: '审查规划', icon: 'plan', color: '#8b5cf6' },
        'review': { title: '代码审查', icon: 'review', color: '#10b981' }
    };
    
    // 渲染每个阶段
    const stageOrder = ['intent', 'planner', 'review'];
    stageOrder.forEach(stage => {
        const stageEvents = stageGroups[stage];
        if (!stageEvents || stageEvents.length === 0) return;
        
        const config = stageConfig[stage] || { title: stage, icon: 'settings', color: '#64748b' };
        
        // 创建阶段容器
        const stageSection = document.createElement('div');
        stageSection.className = 'workflow-stage-section';
        stageSection.dataset.stage = stage;
        stageSection.innerHTML = `
            <div class="stage-header collapsible" onclick="toggleStageSection(this)">
                <div class="stage-indicator" style="--stage-color: ${config.color}">
                    ${getIcon(config.icon)}
                    <span>${config.title}</span>
                </div>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="stage-content"></div>
        `;
        container.appendChild(stageSection);
        
        const stageContent = stageSection.querySelector('.stage-content');
        
        // 合并相邻的思考事件和输出事件
        let currentThoughtText = '';
        let currentChunkText = '';
        
        stageEvents.forEach((evt, idx) => {
            const isLast = idx === stageEvents.length - 1;
            const nextEvt = stageEvents[idx + 1];
            
            if (evt.type === 'thought') {
                currentThoughtText += evt.content || '';
                // 如果下一个事件不是思考，或者是最后一个，则输出思考块
                if (isLast || (nextEvt && nextEvt.type !== 'thought')) {
                    if (currentThoughtText.trim()) {
                        const thoughtEl = document.createElement('div');
                        thoughtEl.className = 'workflow-thought collapsed';
                        thoughtEl.innerHTML = `
                            <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                                ${getIcon('bot')}
                                <span>思考过程</span>
                                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                            </div>
                            <div class="thought-body"><pre class="thought-text">${escapeHtml(currentThoughtText)}</pre></div>
                        `;
                        stageContent.appendChild(thoughtEl);
                    }
                    currentThoughtText = '';
                }
            } else if (evt.type === 'chunk') {
                currentChunkText += evt.content || '';
                // 如果下一个事件不是 chunk，或者是最后一个，则处理内容
                if (isLast || (nextEvt && nextEvt.type !== 'chunk')) {
                    if (currentChunkText.trim()) {
                        // review 阶段：检查后面是否有工具调用
                        if (stage === 'review') {
                            // 查找后续是否有工具调用
                            const hasFollowingToolCall = stageEvents.slice(idx + 1).some(
                                e => e.type === 'tool_start' || e.type === 'tool_call_start'
                            );
                            
                            if (hasFollowingToolCall && nextEvt && (nextEvt.type === 'tool_start' || nextEvt.type === 'tool_call_start')) {
                                // 后面紧跟工具调用，这是工具解释，显示为解释语言
                                const explanationEl = document.createElement('div');
                                explanationEl.className = 'workflow-tool-explanation';
                                explanationEl.innerHTML = `
                                    <div class="tool-explanation-content markdown-body">
                                        ${marked.parse(currentChunkText)}
                                    </div>
                                `;
                                stageContent.appendChild(explanationEl);
                            }
                            // 如果是最后的内容（没有后续工具调用），不在右侧显示
                            // 因为这是最终报告，会显示在左侧
                        } else {
                            // 非 review 阶段，显示在可折叠框内
                            // planner 阶段显示为"上下文决策"，其他阶段显示为"输出内容"
                            const chunkTitle = stage === 'planner' ? '上下文决策' : '输出内容';
                            const wrapper = document.createElement('div');
                            wrapper.className = 'workflow-chunk-wrapper collapsed';
                            wrapper.innerHTML = `
                                <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                                    ${getIcon('folder')}
                                    <span>${chunkTitle}</span>
                                    <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                                </div>
                                <div class="chunk-body">
                                    <div class="workflow-chunk markdown-body">${marked.parse(currentChunkText)}</div>
                                </div>
                            `;
                            stageContent.appendChild(wrapper);
                        }
                    }
                    currentChunkText = '';
                }
            } else if (evt.type === 'tool_start' || evt.type === 'tool_call_start') {
                const toolEl = document.createElement('div');
                toolEl.className = 'workflow-tool';
                const toolName = evt.tool || evt.tool_name || '未知工具';
                const detail = evt.detail || '';
                toolEl.innerHTML = `
                    <div class="tool-info">
                        ${getIcon('settings')}
                        <span class="tool-name">${escapeHtml(toolName)}</span>
                        ${detail ? `<span class="tool-args">${escapeHtml(detail)}</span>` : ''}
                    </div>
                `;
                stageContent.appendChild(toolEl);
            }
        });
    });
}

/**
 * 回放监控日志事件，用于显示历史会话的监控信息
 * @param {HTMLElement} container - 监控面板容器元素
 * @param {Array} events - 工作流事件数组（包含监控事件）
 */
function replayMonitorEvents(container, events) {
    if (!container || !events || events.length === 0) return;
    
    // 过滤出监控相关的事件
    const monitorEvents = events.filter(evt => 
        evt.type === 'warning' || evt.type === 'usage_summary'
    );
    
    if (monitorEvents.length === 0) return;
    
    let hasWarnings = false;
    
    monitorEvents.forEach(evt => {
        if (evt.type === 'warning') {
            hasWarnings = true;
            const s = evt.fallback_summary || {};
            const summaryEl = document.createElement('div');
            summaryEl.className = 'fallback-summary';
            
            const total = s.total || 0;
            const byKey = s.by_key || {};
            const byPriority = s.by_priority || {};
            const byCategory = s.by_category || {};
            
            let html = `
                <div class="summary-header">
                    ${getIcon('clock')}
                    <span>回退统计</span>
                </div>
                <div class="summary-stat">
                    <span class="stat-label">总回退次数</span>
                    <span class="stat-value">${total}</span>
                </div>
            `;
            
            if (Object.keys(byKey).length) {
                html += '<div class="summary-stat"><span class="stat-label">按键统计</span></div>';
                html += '<div style="padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                for (const [k, v] of Object.entries(byKey)) {
                    html += `<span class="fallback-badge warning">${escapeHtml(k)}: ${v}</span>`;
                }
                html += '</div>';
            }
            
            if (Object.keys(byPriority).length) {
                html += '<div class="summary-stat"><span class="stat-label">按优先级</span></div>';
                html += '<div style="padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                for (const [k, v] of Object.entries(byPriority)) {
                    const badgeClass = k.toLowerCase().includes('high') ? 'error' : 
                                       k.toLowerCase().includes('low') ? 'info' : 'warning';
                    html += `<span class="fallback-badge ${badgeClass}">${escapeHtml(k)}: ${v}</span>`;
                }
                html += '</div>';
            }
            
            if (Object.keys(byCategory).length) {
                html += '<div class="summary-stat"><span class="stat-label">按分类</span></div>';
                html += '<div style="padding: 0.5rem 0; display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                for (const [k, v] of Object.entries(byCategory)) {
                    html += `<span class="fallback-badge info">${escapeHtml(k)}: ${v}</span>`;
                }
                html += '</div>';
            }
            
            summaryEl.innerHTML = html;
            container.appendChild(summaryEl);
        }
        
        if (evt.type === 'usage_summary') {
            const call = evt.call_usage || {};
            const totals = evt.session_usage || {};
            const stageText = evt.usage_stage || '';
            const callIndex = evt.call_index;
            const item = document.createElement('div');
            item.className = 'process-item';
            const idx = (callIndex !== undefined && callIndex !== null) ? `#${callIndex}` : '';
            item.innerHTML = `
                <div><strong>API调用 ${idx}</strong>${stageText ? ` · ${escapeHtml(stageText)}` : ''}</div>
                <ul>
                    <li>本次 tokens: 总计 ${call.total ?? '-'}（入 ${call.in ?? '-'}，出 ${call.out ?? '-'})</li>
                    <li>会话累计: 总计 ${totals.total ?? '-'}（入 ${totals.in ?? '-'}，出 ${totals.out ?? '-'})</li>
                </ul>
            `;
            container.appendChild(item);
        }
    });
    
    // 更新监控面板状态
    const monitorPanel = document.getElementById('monitorPanel');
    if (monitorPanel) {
        if (hasWarnings) {
            monitorPanel.classList.remove('ok');
        }
        const titleEl = monitorPanel.querySelector('.panel-title');
        if (titleEl) titleEl.textContent = '日志';
        // 展开监控面板
        monitorPanel.classList.remove('collapsed');
    }
}

// 更新会话列表中的选中状态
function updateSessionActiveState(activeSessionId) {
    if (!sessionListEl) return;
    const items = sessionListEl.querySelectorAll('.session-item');
    items.forEach(item => {
        if (item.dataset.sessionId === activeSessionId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

async function renameSession(sid, oldName) {
    const newName = prompt("请输入新的会话名称:", oldName);
    if (newName && newName !== oldName) {
        try {
            const res = await fetch("/api/sessions/rename", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sid, new_name: newName })
            });
            if (!res.ok) throw new Error("Rename failed");
            loadSessions(); // Refresh list
        } catch (e) {
            showToast("重命名失败: " + e.message, "error");
        }
    }
}

async function deleteSession(sid) {
    if (confirm("确定要删除此会话吗？此操作无法撤销。")) {
        try {
            const res = await fetch("/api/sessions/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sid })
            });
            if (!res.ok) throw new Error("Delete failed");
            
            // 如果删除的是当前会话，返回到新工作区
            if (currentSessionId === sid) {
                returnToNewWorkspace();
            }
            
            // 如果删除的是正在运行的任务，清除运行状态
            if (getRunningSessionId() === sid) {
                endReviewTask();
            }
            
            loadSessions(); // Refresh list
            showToast("会话已删除", "success");
        } catch (e) {
            showToast("删除失败: " + e.message, "error");
        }
    }
}

function generateSessionId() {
    return "sess_" + Date.now();
}

/**
 * 创建新会话并刷新列表
 * @param {string} projectRoot - 项目根路径
 * @param {boolean} switchToPage - 是否切换到审查页面
 * @returns {Promise<string>} 新会话ID
 */
async function createAndRefreshSession(projectRoot = null, switchToPage = false) {
    const newId = generateSessionId();
    
    // 退出历史浏览模式
    setViewingHistory(false);
    
    // 重置到初始布局
    setLayoutState(LayoutState.INITIAL);
    
    // 清空消息容器
    if (messageContainer) {
        messageContainer.innerHTML = `
            <div class="message system-message">
                <div class="avatar">${getIcon('bot')}</div>
                <div class="content">
                    <p>准备好审查您的代码。请选择一个项目文件夹开始。</p>
                </div>
            </div>
        `;
    }
    
    // 清空工作流和报告面板
    const workflowEntries = document.getElementById('workflowEntries');
    const reportContainer = document.getElementById('reportContainer');
    if (workflowEntries) workflowEntries.innerHTML = '';
    if (reportContainer) {
        reportContainer.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon"><svg class="icon icon-large"><use href="#icon-report"></use></svg></div>
                <p>审查完成后将在此展示最终报告</p>
            </div>
        `;
    }
    
    // 重置进度
    resetProgress();
    
    if (switchToPage) switchPage('review');
    
    // 后端创建会话
    try {
        const res = await fetch("/api/sessions/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                session_id: newId, 
                project_root: projectRoot || currentProjectRoot 
            })
        });
        
        if (res.ok) {
            currentSessionId = newId;
            setLastSessionId(newId);
            await loadSessions();
            updateSessionActiveState(newId);
            showToast("已创建新会话", "success");
        } else {
            const errorData = await res.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${res.status}`);
        }
    } catch (e) {
        console.error("Failed to create session:", e);
        showToast("创建会话失败: " + e.message, "error");
        // 失败时也设置为当前会话，但不保存到 localStorage
        currentSessionId = newId;
    }
    
    return newId;
}

// --- Options Loader ---
async function loadOptions() {
    try {
        const res = await fetch("/api/options");
        if (!res.ok) {
            console.error("Failed to load options:", res.status);
            // 显示用户可见的错误提示
            if (toolListContainer) {
                toolListContainer.innerHTML = `
                    <div class="error-state" style="padding:0.5rem;text-align:center;">
                        <span style="color:#dc2626;font-size:0.85rem;">加载失败</span>
                        <button class="btn-text" onclick="loadOptions()" style="margin-left:0.5rem;">重试</button>
                    </div>
                `;
            }
            return;
        }
        const data = await res.json();
        
        // Render Models
        availableGroups = data.models || [];
        window.availableModels = availableGroups;
        renderModelMenu(availableGroups);
        if (typeof renderIntentModelDropdown === 'function') {
            renderIntentModelDropdown(availableGroups);
        }
        
        // Render Manage Models UI
        renderManageModelsList();

        // Render Tools
        if (toolListContainer) {
            const tools = data.tools || [];
            if (tools.length === 0) {
                toolListContainer.innerHTML = '<span class="text-muted" style="font-size:0.85rem;">无可用工具</span>';
                return;
            }
            toolListContainer.innerHTML = "";
            tools.forEach(tool => {
                const label = document.createElement("label");
                const isDefault = tool.default === true;
                label.className = `tool-item ${isDefault ? 'checked' : ''}`;
                const toolName = escapeHtml(tool.name || '');
                label.innerHTML = `
                    <input type="checkbox" value="${toolName}" ${isDefault ? 'checked' : ''}>
                    ${toolName}
                `;
                const checkbox = label.querySelector('input');
                checkbox.onchange = () => {
                    if(checkbox.checked) label.classList.add('checked');
                    else label.classList.remove('checked');
                };
                toolListContainer.appendChild(label);
            });
        }
        
    } catch (e) { 
        console.error("Load options error:", e);
        if (toolListContainer) {
            toolListContainer.innerHTML = `
                <div class="error-state" style="padding:0.5rem;text-align:center;">
                    <span style="color:#dc2626;font-size:0.85rem;">加载失败</span>
                    <button class="btn-text" onclick="loadOptions()" style="margin-left:0.5rem;">重试</button>
                </div>
            `;
        }
    }
}

function renderModelMenu(groups) {
    if (!modelDropdownMenu) return;
    
    modelDropdownMenu.innerHTML = "";
    
    if (!groups || groups.length === 0) {
        modelDropdownMenu.innerHTML = '<div class="dropdown-item" style="color:var(--text-muted);">无可用模型</div>';
        return;
    }
    
    groups.forEach(g => {
        const groupDiv = document.createElement("div");
        groupDiv.className = "dropdown-group-container expanded";
        
        const providerLabel = escapeHtml(g.label || (g.provider ? g.provider.toUpperCase() : '未知'));
        const models = g.models || [];
        
        groupDiv.innerHTML = `
             <div class="dropdown-group-header">
                <span>${providerLabel}</span>
                <svg class="icon chevron-dropdown"><use href="#icon-chevron-down"></use></svg>
             </div>
             <div class="dropdown-group-models">
                ${models.map(m => {
                    const modelName = escapeHtml(m.name || '');
                    const modelLabel = escapeHtml(m.label || m.name || '');
                    const isSelected = m.name === currentModelValue;
                    const isAvailable = m.available !== false;
                    return `
                    <div class="dropdown-item ${isSelected ? 'selected' : ''}" 
                         style="${!isAvailable ? 'opacity:0.5;cursor:not-allowed;' : ''}"
                         data-value="${modelName}" 
                         data-label="${modelLabel}"
                         data-available="${isAvailable ? 'true' : 'false'}">
                        <span>${modelLabel}</span>
                    </div>`;
                }).join('')}
             </div>
        `;
        
        // Bind click events properly
        const header = groupDiv.querySelector('.dropdown-group-header');
        header.onclick = (e) => {
            e.stopPropagation();
            groupDiv.classList.toggle('expanded');
        };
        
        const items = groupDiv.querySelectorAll('.dropdown-item');
        items.forEach(item => {
            item.onclick = (e) => {
                e.stopPropagation();
                if (item.dataset.available === 'true') {
                    selectModel(item.dataset.value, item.dataset.label);
                }
            };
        });
        
        modelDropdownMenu.appendChild(groupDiv);
    });
}

function selectModel(val, label) {
    currentModelValue = val;
    if (selectedModelText) selectedModelText.textContent = label;
    if (modelDropdown) modelDropdown.classList.remove('open');
    
    // Update selected state in menu
    if (modelDropdownMenu) {
        const items = modelDropdownMenu.querySelectorAll('.dropdown-item');
        items.forEach(item => {
            if (item.dataset.value === val) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });
    }
}

// --- Model Management ---
function openManageModelsModal() {
    const modal = document.getElementById('manageModelsModal');
    if (modal) {
        modal.style.display = 'flex';
        loadModelProviders();
        renderManageModelsList();
    }
}

function closeManageModelsModal() {
    const modal = document.getElementById('manageModelsModal');
    if (modal) modal.style.display = 'none';
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('manageModelsModal');
    if (event.target === modal) {
        closeManageModelsModal();
    }
}

async function loadModelProviders() {
    const container = document.getElementById('providerSelectContainer');
    if (!container) return;
    
    try {
        const res = await fetch('/api/models/providers');
        const data = await res.json();
        const providers = data.providers || [];
        
        let html = `
            <select id="providerSelect" class="bare-select">
                ${providers.map(p => `<option value="${p.id}">${p.label}</option>`).join('')}
            </select>
        `;
        container.innerHTML = html;
    } catch (e) {
        console.error("Load providers error:", e);
        container.innerHTML = "Error loading providers";
    }
}

function renderManageModelsList() {
    const list = document.getElementById('modelList');
    if (!list) return;
    
    list.innerHTML = "";
    
    if (availableGroups.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无模型</div>';
        return;
    }
    
    availableGroups.forEach(g => {
        const groupDiv = document.createElement("div");
        groupDiv.className = "model-group-item";
        
        const providerName = g.label || g.provider;
        const models = g.models || [];

        const modelsHtml = models.map(m => `
            <div class="model-list-row">
                <span class="model-name" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</span>
                <button class="icon-btn-small delete-btn" onclick="deleteModel('${g.provider}', '${escapeHtml(m.name)}')">
                    ${getIcon('trash')}
                </button>
            </div>
        `).join('');

        groupDiv.innerHTML = `
            <div class="group-header"><strong>${escapeHtml(providerName)}</strong><span class="count-badge">${models.length}</span></div>
            <div class="group-body">${modelsHtml}</div>
        `;
        list.appendChild(groupDiv);
    });
}

async function addModel() {
    const providerSelect = document.getElementById('providerSelect');
    const nameInput = document.getElementById('newModelName');
    
    if (!providerSelect || !nameInput) return;
    
    const provider = providerSelect.value;
    const name = nameInput.value.trim();
    
    if (!name) {
        showToast("请输入模型名称", "warning");
        return;
    }
    
    try {
        const res = await fetch('/api/models/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ provider: provider, model: name })
        });
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Add failed");
        }
        
        nameInput.value = "";
        await loadOptions(); // Reload global options
        showToast("模型添加成功", "success");
    } catch (e) {
        showToast("添加失败: " + e.message, "error");
    }
}

async function deleteModel(provider, name) {
    if (!confirm(`确定要删除模型 ${name} 吗？`)) return;
    
    try {
        const res = await fetch('/api/models/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ provider: provider, model: name })
        });
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Delete failed");
        }
        
        await loadOptions(); // Reload global options
        showToast("模型删除成功", "success");
    } catch (e) {
        showToast("删除失败: " + e.message, "error");
    }
}

// --- Bind new events ---
document.addEventListener('DOMContentLoaded', () => {
    const addBtn = document.getElementById('addModelBtn');
    if (addBtn) addBtn.onclick = addModel;
    
    const closeModalBtn = document.querySelector('.close-modal');
    if (closeModalBtn) closeModalBtn.onclick = closeManageModelsModal;
    
    // Add Manage Models button to config page if not exists
    // We can inject it dynamically when config page loads or just add a button in the header
});

// --- Tool Helpers ---

/**
 * Copy the report content to clipboard.
 * Copies the text content (without HTML) for easy sharing.
 */
async function copyReportContent() {
    const reportContent = document.getElementById('reportContainer');
    if (!reportContent) {
        showToast('没有可复制的报告内容', 'warning');
        return;
    }
    
    try {
        // Get text content, preserving some structure
        const textContent = reportContent.innerText || reportContent.textContent;
        await navigator.clipboard.writeText(textContent);
        showToast('报告已复制到剪贴板', 'success');
    } catch (e) {
        console.error('Copy failed:', e);
        showToast('复制失败: ' + e.message, 'error');
    }
}

/**
 * Toggle report panel fullscreen mode.
 * In fullscreen mode, the report panel takes up the entire workbench area.
 */
function toggleReportFullScreen() {
    const reportPanel = document.querySelector('.report-panel');
    if (!reportPanel) return;
    
    // Toggle fullscreen class
    reportPanel.classList.toggle('fullscreen');
    
    // Update button icon/title based on state
    const fullscreenBtn = reportPanel.querySelector('.actions .icon-btn[title="全屏"]');
    if (fullscreenBtn) {
        if (reportPanel.classList.contains('fullscreen')) {
            fullscreenBtn.title = '退出全屏';
        } else {
            fullscreenBtn.title = '全屏';
        }
    }
}

function reportGoBack() {
    const panel = document.getElementById('reportPanel');
    if (panel && panel.classList.contains('fullscreen')) {
        toggleReportFullScreen();
        return;
    }
    // 返回到全新工作区
    returnToNewWorkspace();
}

/**
 * 返回到全新的无状态工作区
 * 如果有任务正在运行，先保存快照再返回
 */
function returnToNewWorkspace() {
    // 如果有任务在运行，保存快照但不中断任务
    if (isReviewRunning()) {
        saveRunningUISnapshot();
        // 提示用户任务仍在后台运行
        showToast("审查任务继续在后台运行，可从历史记录返回", "info");
    }
    stopSessionPolling();
    
    // 清空当前会话状态（注意：不清除 runningSessionId）
    currentSessionId = null;
    currentProjectRoot = null;
    
    // 重置布局到初始状态
    setLayoutState(LayoutState.INITIAL);
    
    // 清空消息容器
    if (messageContainer) {
        messageContainer.innerHTML = `
            <div class="message system-message">
                <div class="avatar">${getIcon('bot')}</div>
                <div class="content">
                    <p>准备好审查您的代码。请选择一个项目文件夹开始。</p>
                </div>
            </div>
        `;
    }
    
    // 清空工作流和报告面板
    const workflowEntries = document.getElementById('workflowEntries');
    const reportContainer = document.getElementById('reportContainer');
    if (workflowEntries) workflowEntries.innerHTML = '';
    if (reportContainer) {
        reportContainer.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon"><svg class="icon icon-large"><use href="#icon-report"></use></svg></div>
                <p>审查完成后将在此展示最终报告</p>
            </div>
        `;
    }
    
    // 重置进度条
    resetProgress();
    
    // 清空项目路径显示
    updateProjectPath('');
    
    // 隐藏历史模式指示器
    setViewingHistory(false);
    
    // 清除会话选中状态
    updateSessionActiveState(null);
    
    // 更新后台任务按钮
    updateBackgroundTaskIndicator();
    
    // 关闭历史抽屉（如果打开着）
    if (historyDrawer) historyDrawer.classList.remove('open');
}


// --- Toast Notification ---
function showToast(message, type = 'info') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    let iconName = 'bot';
    if (type === 'error') iconName = 'x';
    if (type === 'success') iconName = 'check'; // Assuming check icon exists or fallback
    
    toast.innerHTML = `
        <div class="toast-icon">${getIcon(iconName)}</div>
        <div class="toast-content">${escapeHtml(message)}</div>
        <div class="toast-close">${getIcon('x')}</div>
    `;
    
    toast.querySelector('.toast-close').onclick = () => {
        toast.classList.add('hiding');
        toast.addEventListener('animationend', () => toast.remove());
    };
    
    container.appendChild(toast);
    
    // Auto remove
    setTimeout(() => {
        if (toast.isConnected) {
            toast.classList.add('hiding');
            toast.addEventListener('animationend', () => toast.remove());
        }
    }, 5000);
}

// --- Helper: Button Loading State ---
function setButtonLoading(btn, isLoading, loadingText = null) {
    if (!btn) return;
    if (isLoading) {
        btn.classList.add('btn-loading');
        if (!btn.dataset.originalText) btn.dataset.originalText = btn.innerHTML;
        btn.disabled = true;
        // Optional: change text if needed, but CSS spinner usually suffices
    } else {
        btn.classList.remove('btn-loading');
        btn.disabled = false;
        if (btn.dataset.originalText) {
            // Restore text if needed, though we usually just overlay spinner
            // btn.innerHTML = btn.dataset.originalText; 
        }
    }
}

// --- Intent Panel Logic (Enhanced) ---

let currentIntentModel = "auto";
let intentContent = ""; // Store content globally

function initIntentPanel() {
    // Initialize dropdown if not already done
    if (document.getElementById('intentModelDropdown')) {
         if (window.availableModels) {
             renderIntentModelDropdown(window.availableModels);
         }
    }
    
    // Bind events for intent panel
    const trigger = document.getElementById('intentModelDropdownTrigger');
    if (trigger) {
        trigger.onclick = (e) => {
            e.stopPropagation();
            const dropdown = document.getElementById('intentModelDropdown');
            if (dropdown) dropdown.classList.toggle('open');
        };
    }
    
    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        const dropdown = document.getElementById('intentModelDropdown');
        if (dropdown && dropdown.classList.contains('open') && !dropdown.contains(e.target)) {
            dropdown.classList.remove('open');
        }
    });
}

function renderIntentModelDropdown(groupsData) {
    const menu = document.getElementById('intentModelDropdownMenu');
    if (!menu) return;
    
    menu.innerHTML = '';
    
    // Add Auto option
    const autoItem = document.createElement('div');
    autoItem.className = `dropdown-item ${currentIntentModel === 'auto' ? 'selected' : ''}`;
    autoItem.innerHTML = `<span>自动 (Auto)</span>`;
    autoItem.onclick = () => selectIntentModel('auto', '自动 (Auto)');
    menu.appendChild(autoItem);
    
    if (!groupsData || groupsData.length === 0) return;

    // groupsData is an array of provider groups
    groupsData.forEach(group => {
        const providerName = group.label || group.provider || 'Unknown';
        const models = group.models || [];
        
        if (models.length === 0) return;

        const header = document.createElement('div');
        header.className = 'dropdown-group-header';
        header.innerHTML = `<span>${escapeHtml(providerName)}</span>`;
        menu.appendChild(header);
        
        models.forEach(m => {
            const item = document.createElement('div');
            const modelName = m.name || '';
            const modelLabel = m.label || m.name || '';
            const isAvailable = m.available !== false;
            
            item.className = `dropdown-item ${currentIntentModel === modelName ? 'selected' : ''}`;
            if (!isAvailable) {
                item.style.opacity = '0.5';
                item.style.cursor = 'not-allowed';
            }
            
            item.innerHTML = `<span>${escapeHtml(modelLabel)}</span>`;
            
            if (isAvailable) {
                item.onclick = () => selectIntentModel(modelName, modelLabel);
            }
            menu.appendChild(item);
        });
    });
}

function selectIntentModel(model, displayName) {
    currentIntentModel = model;
    const text = document.getElementById('intentSelectedModelText');
    if (text) text.textContent = displayName;
    
    const dropdown = document.getElementById('intentModelDropdown');
    if (dropdown) dropdown.classList.remove('open');
    
    // Update selection styles
    const items = document.querySelectorAll('#intentModelDropdownMenu .dropdown-item');
    items.forEach(item => {
        if (item.textContent.trim() === displayName || (model === 'auto' && item.textContent.includes('Auto'))) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }
    });
}

async function runIntentAnalysis() {
    if (!currentProjectRoot) {
        showToast("请先选择项目文件夹", "error");
        return;
    }
    
    const btn = document.getElementById('intent-analyze-btn');
    setButtonLoading(btn, true);
    
    const thoughtContainer = document.getElementById('intent-thought-container');
    const thoughtContent = document.getElementById('intent-thought-content');
    const thoughtStatus = document.getElementById('thought-status');
    const contentView = document.getElementById('intent-view');
    const contentDiv = document.getElementById('intent-content');
    const emptyState = document.getElementById('intent-empty');
    
    // Reset UI
    if (emptyState) emptyState.style.display = 'none';
    if (contentView) contentView.style.display = 'block';
    if (contentDiv) contentDiv.innerHTML = '';
    if (thoughtContainer) thoughtContainer.style.display = 'none';
    if (thoughtContent) thoughtContent.innerHTML = '';
    if (thoughtStatus) thoughtStatus.textContent = "";
    
    let fullContent = "";
    let fullThought = "";
    
    try {
        const response = await fetch("/api/intent/analyze_stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                project_root: currentProjectRoot,
                model: currentIntentModel
            })
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop() || "";
            
            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    try {
                        const evt = JSON.parse(line.slice(6));
                        
                        if (evt.type === "thought") {
                            if (thoughtContainer.style.display === 'none') {
                                thoughtContainer.style.display = 'block';
                                if (thoughtStatus) thoughtStatus.textContent = "Thinking...";
                            }
                            fullThought += evt.content;
                            thoughtContent.textContent = fullThought;
                            thoughtContent.scrollTop = thoughtContent.scrollHeight;
                        } else if (evt.type === "chunk") {
                            fullContent += evt.content;
                            contentDiv.innerHTML = marked.parse(fullContent);
                        } else if (evt.type === "final") {
                            if (evt.content) {
                                fullContent = evt.content;
                                contentDiv.innerHTML = marked.parse(fullContent);
                            }
                            if (thoughtStatus) thoughtStatus.textContent = "Completed";
                        } else if (evt.type === "error") {
                            showToast("分析出错: " + evt.message, "error");
                        }
                    } catch (e) {
                        console.error("SSE Parse Error", e);
                    }
                }
            }
        }
        
        intentContent = fullContent;
        
    } catch (e) {
        console.error("Intent Analysis Error:", e);
        showToast("分析失败: " + e.message, "error");
        if (contentDiv && !fullContent) {
             contentDiv.innerHTML = `<p class="error-text">分析失败: ${escapeHtml(e.message)}</p>`;
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

function enterIntentEditMode() {
    const viewMode = document.getElementById('intent-view');
    const textarea = document.getElementById('intent-textarea');
    const actions = document.getElementById('intent-edit-actions');
    const contentDiv = document.getElementById('intent-content');
    
    if (textarea && viewMode && actions) {
        textarea.value = intentContent || (contentDiv ? contentDiv.innerText : ""); 
        
        viewMode.style.display = 'none';
        textarea.style.display = 'block';
        actions.style.display = 'flex';
        
        textarea.focus();
    }
}

function cancelIntentEdit() {
    const viewMode = document.getElementById('intent-view');
    const textarea = document.getElementById('intent-textarea');
    const actions = document.getElementById('intent-edit-actions');
    
    if (viewMode && textarea && actions) {
        viewMode.style.display = 'block';
        textarea.style.display = 'none';
        actions.style.display = 'none';
    }
}

async function saveIntentEdit() {
    const textarea = document.getElementById('intent-textarea');
    if (!textarea) return;
    
    const newContent = textarea.value;
    
    // Optimistic update
    intentContent = newContent; 
    const contentDiv = document.getElementById('intent-content');
    if (contentDiv) contentDiv.innerHTML = marked.parse(newContent);
    
    cancelIntentEdit();
    
    // Persist to backend
    if (currentProjectRoot) {
        try {
            const res = await fetch('/api/intent/update', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    project_root: currentProjectRoot,
                    content: newContent
                })
            });
            
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            
            const result = await res.json();
            if (result.success) {
                showToast('意图已保存', 'success');
            } else {
                showToast('保存失败: ' + (result.error || 'Unknown error'), 'error');
            }
        } catch (e) {
            console.error("Save intent error:", e);
            showToast('保存请求失败: ' + e.message, 'error');
        }
    } else {
        showToast('未选择项目，仅本地更新', 'warning');
    }
}

// Ensure init runs
document.addEventListener('DOMContentLoaded', initIntentPanel);


// ============================================
// Report Panel Utilities
// ============================================

/**
 * Copy the content of the report to clipboard.
 */
function copyReportContent() {
    const reportContainer = document.getElementById('reportContainer');
    if (reportContainer && reportContainer.innerText.trim()) {
        navigator.clipboard.writeText(reportContainer.innerText).then(() => {
            showToast('内容已复制到剪贴板', 'success');
        }).catch(err => {
            console.error('Copy failed:', err);
            showToast('复制失败', 'error');
        });
    } else {
        showToast('没有可复制的内容', 'warning');
    }
}

/**
 * Toggle fullscreen mode for the report panel.
 */
function toggleReportFullScreen() {
    const reportPanel = document.getElementById('reportPanel');
    if (reportPanel) {
        reportPanel.classList.toggle('fullscreen');
    }
}
