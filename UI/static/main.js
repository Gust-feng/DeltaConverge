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
const sessionStatsContent = document.getElementById('session-stats-content');
const sessionTotalBadge = document.getElementById('session-total-badge');
const providerStatusContent = document.getElementById('provider-status-content');
const providerAvailableBadge = document.getElementById('provider-available-badge');
const scannerStatusContent = document.getElementById('scanner-status-content');
const scannerSummaryBadge = document.getElementById('scanner-summary-badge');
const scannerToggleBtn = document.getElementById('scanner-toggle-btn');
let scannerViewMode = 'summary'; // 'summary' (languages) or 'detail' (tools)
let detectedLanguages = [];

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
        
        // 环境检测
        try {
            await checkEnvironment();
        } catch (e) {
            console.warn("Environment check failed", e);
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

async function checkEnvironment() {
    try {
        const res = await fetch('/api/system/env');
        if (!res.ok) return;
        const data = await res.json();
        window.isDockerEnv = !!(data && data.is_docker);
        window.defaultProjectRoot = data && data.default_project_root ? data.default_project_root : null;
        window.platform = (data && data.platform) ? data.platform : null;
    } catch (e) {
        // ignore
    }
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
        'dashboard': '仪表盘 - DeltaConverge',
        'review': '代码审查 - DeltaConverge',
        'diff': '代码变更 - DeltaConverge',
        'config': '设置 - DeltaConverge',
        'debug': '调试 - DeltaConverge',
        'rule-growth': '规则优化 - DeltaConverge'
    };
    document.title = titles[pageId] || 'Code Review Agent';

    // Trigger Loaders
    if (pageId === 'dashboard') loadDashboardData();
    if (pageId === 'diff') refreshDiffAnalysis();
    if (pageId === 'config') loadConfig();
    if (pageId === 'debug') loadDebugInfo();
    if (pageId === 'rule-growth') loadRuleGrowthData();
}

// --- Dashboard Logic ---

async function updateHealthStatus() {
    try {
        const res = await fetch('/api/health/simple');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        
        // Update header health status
        const dashboardHeader = document.getElementById('dashboard-header-container');
        const dashboardHealthLabel = document.getElementById('dashboard-health-label');
        
        if (dashboardHeader && dashboardHealthLabel) {
            dashboardHeader.className = `health-border ${data.healthy ? 'healthy' : 'unhealthy'}`;
            dashboardHealthLabel.style.display = 'inline-block';
            dashboardHealthLabel.textContent = data.healthy ? 'HEALTHY' : 'UNHEALTHY';
            dashboardHealthLabel.className = `health-indicator ${data.healthy ? 'healthy' : 'unhealthy'}`;
        }

        // Update badge (if still used, or hide it)
        if (healthStatusBadge) {
            healthStatusBadge.style.display = 'none'; // Hide old badge
        }
    } catch (e) {
        console.error("Health check failed", e);
        const dashboardHeader = document.getElementById('dashboard-header-container');
        const dashboardHealthLabel = document.getElementById('dashboard-health-label');
        if (dashboardHeader && dashboardHealthLabel) {
            dashboardHeader.className = `health-border unhealthy`;
            dashboardHealthLabel.style.display = 'inline-block';
            dashboardHealthLabel.textContent = 'ERROR';
            dashboardHealthLabel.className = `health-indicator unhealthy`;
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
                healthMetricsDiv.style.display = 'flex';
                const uptime = metrics.uptime_seconds ? Math.floor(metrics.uptime_seconds / 60) : 0;
                const memory = metrics.memory_usage_mb ? metrics.memory_usage_mb.toFixed(1) : '0';
                const threads = metrics.thread_count || 0;
                healthMetricsDiv.innerHTML = `
                    <span>Uptime: <b style="color:var(--text-main)">${uptime}m</b></span>
                    <span>Mem: <b style="color:var(--text-main)">${memory}MB</b></span>
                    <span>Threads: <b style="color:var(--text-main)">${threads}</b></span>
                `;
            }
        } else {
            if (healthMetricsDiv) {
                healthMetricsDiv.style.display = 'none';
                const msg = res.status === 499 ? 'Metrics Blocked' : `HTTP ${res.status}`;
                healthMetricsDiv.setAttribute('title', msg);
            }
        }
    } catch (e) {
        if (healthMetricsDiv) {
            healthMetricsDiv.style.display = 'none';
            healthMetricsDiv.setAttribute('title', 'Metrics Error');
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
                    // 检查是否有错误（如非 git 仓库）
                    if (status.error) {
                        dashDiffStatus.textContent = `Error: ${status.error}`;
                        dashDiffStatus.title = status.error;
                    } else if (status.has_working_changes || status.has_staged_changes) {
                        dashDiffStatus.textContent = `Has Changes (${status.detected_mode || 'unknown'})`;
                    } else {
                        dashDiffStatus.textContent = "Clean (no changes)";
                    }
                }
            } else {
                if (dashDiffStatus) dashDiffStatus.textContent = `HTTP Error ${res.status}`;
            }
        } catch (e) {
            console.error("Diff status check error:", e);
            if (dashDiffStatus) dashDiffStatus.textContent = "Error checking diff";
        }
    } else {
        if (dashProjectPath) dashProjectPath.textContent = "未选择";
        if (dashDiffStatus) dashDiffStatus.textContent = "-";
    }
    
    // Load Intent Data
    loadIntentData();

    try {
        const res = await fetch('/api/sessions/stats');
        if (res.ok) {
            const stats = await res.json();
            if (sessionTotalBadge) sessionTotalBadge.textContent = String(stats.total_sessions || 0);
            if (sessionStatsContent) {
                const totalMsgs = stats.total_messages || 0;
                const byStatus = stats.by_status || {};
                const statusEntries = Object.entries(byStatus).sort((a,b)=>b[1]-a[1]).slice(0,3);
                const byProject = stats.by_project || {};
                const projectCount = Object.keys(byProject).length;
                let html = '';
                html += `<div class="stat-row"><span class="label">消息总数:</span><span class="value">${totalMsgs}</span></div>`;
                html += `<div class="stat-row"><span class="label">项目数:</span><span class="value">${projectCount}</span></div>`;
                statusEntries.forEach(([k,v])=>{
                    html += `<div class="stat-row"><span class="label">${k}:</span><span class="value">${v}</span></div>`;
                });
                sessionStatsContent.innerHTML = html;
            }
        }
    } catch (e) {}

    try {
        const res = await fetch('/api/providers/status');
        if (res.ok) {
            const providers = await res.json();
            const total = providers.length || 0;
            const avail = providers.filter(p=>p.available).length;
            if (providerAvailableBadge) providerAvailableBadge.textContent = `${avail}/${total}`;
            if (providerStatusContent) {
                let html = '';
                providers.forEach(p=>{
                    const dotClass = p.available ? 'success' : 'error';
                    const statusText = p.available ? '已配置' : '未配置';
                    const dot = `<span class="status-dot ${dotClass}" title="${escapeHtml(p.error || statusText)}"></span>`;
                    html += `<div class="stat-row"><span class="label">${p.label || p.name}:</span><span class="value" style="display:flex;align-items:center;gap:0.4rem">${dot}<span style="font-size:0.75rem;color:var(--text-muted)">${statusText}</span></span></div>`;
                });
                providerStatusContent.classList.add('compact-list');
                providerStatusContent.innerHTML = html;
            }
        }
    } catch (e) {}

    // Prepare modal handlers
    window.openProviderKeysModal = async function(){
        const modal = document.getElementById('providerKeysModal');
        const list = document.getElementById('providerKeysList');
        if (!modal || !list) return;
        modal.style.display = 'flex';
        list.innerHTML = '<div class="empty-state">加载中...</div>';
        const keyMap = {
            glm: 'GLM_API_KEY',
            bailian: 'BAILIAN_API_KEY',
            modelscope: 'MODELSCOPE_API_KEY',
            moonshot: 'MOONSHOT_API_KEY',
            openrouter: 'OPENROUTER_API_KEY',
            siliconflow: 'SILICONFLOW_API_KEY',
            deepseek: 'DEEPSEEK_API_KEY'
        };
        const providerMeta = [
            { name: 'glm', label: '智谱AI (GLM)' },
            { name: 'bailian', label: '阿里百炼 (Bailian)' },
            { name: 'modelscope', label: '魔搭社区 (ModelScope)' },
            { name: 'moonshot', label: '月之暗面 (Moonshot)' },
            { name: 'openrouter', label: 'OpenRouter' },
            { name: 'siliconflow', label: '硅基流动 (SiliconFlow)' },
            { name: 'deepseek', label: 'DeepSeek' },
        ];
        function renderProviderKeys(providers, envVars){
            let html = '';
            providers.forEach(p=>{
                const k = keyMap[p.name] || '';
                if (!k) return;
                const val = (envVars && envVars[k]) ? envVars[k] : '';
                const inputId = `provider-key-${p.name}`;
                html += `
                <div class="env-var-row">
                    <span class="env-key" title="${p.name}">${p.label || p.name}</span>
                    <input id="${inputId}" type="password" class="env-value" value="${escapeHtml(val)}" placeholder="输入密钥..." autocomplete="new-password" name="pk-${p.name}">
                    <button class="btn-icon" onclick="(function(){const el=document.getElementById('${inputId}'); const icon=this.querySelector('use'); if(el){ const isPass=el.type==='password'; el.type = isPass ? 'text' : 'password'; icon.setAttribute('href', isPass ? '#icon-eye-off' : '#icon-eye'); } }).call(this)" title="显示/隐藏">
                        <svg class="icon"><use href="#icon-eye"></use></svg>
                    </button>
                    <button class="btn-primary" onclick="(function(){const el=document.getElementById('${inputId}'); if(el){ updateEnvVar('${k}', el.value.trim()); } })()">保存</button>
                </div>`;
            });
            return html || '<div class="empty-state">暂无可配置的提供商</div>';
        }
        try {
            const now = Date.now();
            const cache = window.__providerKeysCache || { ts: 0, providers: null, envVars: null };
            // 首屏：使用本地静态提供商 + 已缓存的环境变量，立即渲染
            if (window.__envVarsCache) {
                list.innerHTML = renderProviderKeys(providerMeta, window.__envVarsCache);
            } else {
                list.innerHTML = renderProviderKeys(providerMeta, {});
            }
            if (cache.providers && cache.envVars && (now - cache.ts) < 30000) {
                list.innerHTML = renderProviderKeys(cache.providers, cache.envVars);
            }
            const [pRes, envRes] = await Promise.all([
                fetch('/api/providers/status'),
                fetch('/api/env/vars')
            ]);
            const providers = pRes.ok ? await pRes.json() : [];
            const envVars = envRes.ok ? await envRes.json() : {};
            window.__envVarsCache = envVars;
            window.__providerKeysCache = { ts: Date.now(), providers, envVars };
            // 后续：如果后端返回的 providers 与本地静态不同，用后端数据刷新；否则仅刷新值
            list.innerHTML = renderProviderKeys(providers && providers.length ? providers : providerMeta, envVars);
        } catch (e) {
            list.innerHTML = '<div class="empty-state">加载失败</div>';
        }
    };
    window.closeProviderKeysModal = function(){
        const modal = document.getElementById('providerKeysModal');
        if (modal) modal.style.display = 'none';
    };

    try {
        const infoRes = currentProjectRoot ? await fetch(`/api/project/info?project_root=${encodeURIComponent(currentProjectRoot)}`) : null;
        if (infoRes && infoRes.ok) {
            const pinfo = await infoRes.json();
            const names = Array.isArray(pinfo.detected_languages) ? pinfo.detected_languages : [];
            const map = {
                'Python': 'python',
                'TypeScript': 'typescript',
                'JavaScript': 'javascript',
                'Java': 'java',
                'Go': 'go',
                'Ruby': 'ruby',
                'C': 'c',
                'C++': 'cpp',
                'C#': 'csharp',
                'Rust': 'rust',
                'Kotlin': 'kotlin',
                'Swift': 'swift',
                'PHP': 'php',
                'Scala': 'scala'
            };
            detectedLanguages = names.map(n => map[n]).filter(Boolean);
        } else {
            detectedLanguages = [];
        }

        const res = await fetch('/api/scanners/status');
        if (res.ok) {
            const data = await res.json();
            const langs = data.languages || [];
            
            // 智能过滤：如果有检测到的语言，则只展示相关语言；否则展示全部
            const used = detectedLanguages.length > 0 
                ? langs.filter(l => detectedLanguages.includes(l.language))
                : langs;
                
            let totalAvailable = 0;
            let totalCount = 0;
            
            // 计算总数
            used.forEach(l => {
                totalAvailable += l.available_count || 0;
                totalCount += l.total_count || 0;
            });
            
            if (scannerStatusContent) {
                let html = '';
                
                if (scannerViewMode === 'summary') {
                    // 摘要视图：按语言统计
                    used.forEach(l=>{
                        const ratio = l.total_count > 0 ? (l.available_count / l.total_count) : 0;
                        const colorClass = ratio === 1 ? 'success' : (ratio > 0 ? 'warning' : 'error');
                        // 显示语言名 + 进度条或数字
                        html += `
                        <div class="stat-row">
                            <span class="label" style="width:100px">${l.language}</span>
                            <div style="flex:1;display:flex;align-items:center;justify-content:flex-end;gap:0.5rem">
                                <div style="width:60px;height:6px;background:#f1f5f9;border-radius:3px;overflow:hidden">
                                    <div style="width:${ratio*100}%;height:100%;background:var(--${colorClass}-color, #10b981)"></div>
                                </div>
                                <span class="value" style="min-width:30px;text-align:right">${l.available_count}/${l.total_count}</span>
                            </div>
                        </div>`;
                    });
                } else {
                    // 详情视图：列出具体扫描器
                    used.forEach(l => {
                        const scanners = l.scanners || [];
                        if (scanners.length > 0) {
                            // 语言标题行（可选，或者直接在工具名后标注）
                            // html += `<div class="list-section-header">${l.language}</div>`;
                            
                            scanners.forEach(s => {
                                const statusClass = s.available ? 'success' : 'error';
                                const icon = s.available ? 
                                    '<svg class="icon" style="color:#10b981"><use href="#icon-check"></use></svg>' : 
                                    '<svg class="icon" style="color:#ef4444"><use href="#icon-x"></use></svg>';
                                
                                // 显式状态文本与原因
                                let statusLabel = "";
                                let reasonHtml = "";
                                
                                if (s.available) {
                                    statusLabel = `<span style="font-size:0.75rem;color:var(--text-muted)">已就绪</span>`;
                                } else {
                                    // 区分未启用和未安装
                                    if (!s.enabled) {
                                        statusLabel = `<span style="font-size:0.75rem;color:#f59e0b">已禁用</span>`;
                                        reasonHtml = `<span style="font-size:0.7rem;color:var(--text-muted);margin-right:0.3rem">配置限制</span>`;
                                    } else {
                                        statusLabel = `<span style="font-size:0.75rem;color:#ef4444">未安装</span>`;
                                        reasonHtml = `<span style="font-size:0.7rem;color:var(--text-muted);margin-right:0.3rem">找不到命令</span>`;
                                    }
                                }
                                
                                // 构造工具提示文本（保留作为补充详情）
                                let tooltip = s.available ? `路径: ${s.command}` : `不可用: 未找到命令 ${s.command}`;
                                if (!s.enabled) tooltip += " (配置中已禁用)";
                                
                                html += `<div class="stat-row" title="${escapeHtml(tooltip)}">
                                    <div style="flex:1;display:flex;align-items:center;gap:0.5rem">
                                        <span class="value" style="font-weight:600">${s.name}</span>
                                        <span class="badge" style="font-size:0.7rem;padding:0.1rem 0.4rem;background:#f1f5f9;color:#64748b">${l.language}</span>
                                    </div>
                                    <div style="display:flex;align-items:center;gap:0.4rem">
                                        ${reasonHtml}
                                        ${statusLabel}
                                        ${icon}
                                    </div>
                                </div>`;
                            });
                        }
                    });
                }
                
                if (html === '') {
                    html = '<div class="empty-state" style="padding:1rem;font-size:0.85rem">无相关扫描器</div>';
                }
                scannerStatusContent.innerHTML = html;
            }
            if (scannerSummaryBadge) scannerSummaryBadge.textContent = `${totalAvailable}/${totalCount}`;
        }
    } catch (e) {}
}

if (scannerToggleBtn) {
    scannerToggleBtn.onclick = () => {
        scannerViewMode = scannerViewMode === 'summary' ? 'detail' : 'summary';
        scannerToggleBtn.textContent = scannerViewMode === 'summary' ? '查看详情' : '返回汇总';
        refreshScannerStatus();
    };
}

async function refreshScannerStatus() {
    try {
        const infoRes = currentProjectRoot ? await fetch(`/api/project/info?project_root=${encodeURIComponent(currentProjectRoot)}`) : null;
        if (infoRes && infoRes.ok) {
            const pinfo = await infoRes.json();
            const names = Array.isArray(pinfo.detected_languages) ? pinfo.detected_languages : [];
            const map = {
                'Python': 'python',
                'TypeScript': 'typescript',
                'JavaScript': 'javascript',
                'Java': 'java',
                'Go': 'go',
                'Ruby': 'ruby',
                'C': 'c',
                'C++': 'cpp',
                'C#': 'csharp',
                'Rust': 'rust',
                'Kotlin': 'kotlin',
                'Swift': 'swift',
                'PHP': 'php',
                'Scala': 'scala'
            };
            detectedLanguages = names.map(n => map[n]).filter(Boolean);
        } else {
            detectedLanguages = [];
        }

        const res = await fetch('/api/scanners/status');
        if (res.ok) {
            const data = await res.json();
            const langs = data.languages || [];
            const used = detectedLanguages.length > 0 
                ? langs.filter(l => detectedLanguages.includes(l.language))
                : langs;
            let totalAvailable = 0;
            let totalCount = 0;
            used.forEach(l => {
                totalAvailable += l.available_count || 0;
                totalCount += l.total_count || 0;
            });
            if (scannerStatusContent) {
                let html = '';
                if (scannerViewMode === 'summary') {
                    used.forEach(l=>{
                        const ratio = l.total_count > 0 ? (l.available_count / l.total_count) : 0;
                        const colorClass = ratio === 1 ? 'success' : (ratio > 0 ? 'warning' : 'error');
                        html += `
                        <div class="stat-row">
                            <span class="label" style="width:100px">${l.language}</span>
                            <div style="flex:1;display:flex;align-items:center;justify-content:flex-end;gap:0.5rem">
                                <div style="width:60px;height:6px;background:#f1f5f9;border-radius:3px;overflow:hidden">
                                    <div style="width:${ratio*100}%;height:100%;background:var(--${colorClass}-color, #10b981)"></div>
                                </div>
                                <span class="value" style="min-width:30px;text-align:right">${l.available_count}/${l.total_count}</span>
                            </div>
                        </div>`;
                    });
                } else {
                    used.forEach(l => {
                        const scanners = l.scanners || [];
                        if (scanners.length > 0) {
                            scanners.forEach(s => {
                                const icon = s.available ? 
                                    '<svg class="icon" style="color:#10b981"><use href="#icon-check"></use></svg>' : 
                                    '<svg class="icon" style="color:#ef4444"><use href="#icon-x"></use></svg>';
                                let statusLabel = "";
                                let reasonHtml = "";
                                if (s.available) {
                                    statusLabel = `<span style="font-size:0.75rem;color:var(--text-muted)">已就绪</span>`;
                                } else {
                                    if (!s.enabled) {
                                        statusLabel = `<span style="font-size:0.75rem;color:#f59e0b">已禁用</span>`;
                                        reasonHtml = `<span style="font-size:0.7rem;color:var(--text-muted);margin-right:0.3rem">配置限制</span>`;
                                    } else {
                                        statusLabel = `<span style="font-size:0.75rem;color:#ef4444">未安装</span>`;
                                        reasonHtml = `<span style="font-size:0.7rem;color:var(--text-muted);margin-right:0.3rem">找不到命令</span>`;
                                    }
                                }
                                let tooltip = s.available ? `路径: ${s.command}` : `不可用: 未找到命令 ${s.command}`;
                                if (!s.enabled) tooltip += " (配置中已禁用)";
                                html += `<div class="stat-row" title="${escapeHtml(tooltip)}">
                                    <div style="flex:1;display:flex;align-items:center;gap:0.5rem">
                                        <span class="value" style="font-weight:600">${s.name}</span>
                                        <span class="badge" style="font-size:0.7rem;padding:0.1rem 0.4rem;background:#f1f5f9;color:#64748b">${l.language}</span>
                                    </div>
                                    <div style="display:flex;align-items:center;gap:0.4rem">
                                        ${reasonHtml}
                                        ${statusLabel}
                                        ${icon}
                                    </div>
                                </div>`;
                            });
                        }
                    });
                }
                if (html === '') {
                    html = '<div class="empty-state" style="padding:1rem;font-size:0.85rem">无相关扫描器</div>';
                }
                scannerStatusContent.innerHTML = html;
            }
            if (scannerSummaryBadge) scannerSummaryBadge.textContent = `${totalAvailable}/${totalCount}`;
        }
    } catch (e) {}
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
        } else if (res.status === 404) {
            // Cache not found - this is normal for new projects
            if (emptyState) emptyState.style.display = 'flex';
            if (contentDiv) contentDiv.innerHTML = '';
            if (typeof intentContent !== 'undefined') intentContent = "";
        } else {
            // Other error
            console.error("Load intent error: HTTP", res.status);
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
        var reqMode = 'working';
        try {
            var sres = await fetch('/api/diff/status?project_root=' + encodeURIComponent(currentProjectRoot));
            if (sres && sres.ok) {
                var st = await sres.json();
                if (st && st.has_staged_changes) reqMode = 'staged';
                else if (st && st.has_working_changes) reqMode = 'working';
            }
        } catch (_) {}
        var res = await fetch('/api/diff/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: currentProjectRoot, mode: reqMode })
        });
        if (!res.ok) {
            throw new Error('HTTP ' + res.status);
        }
        var data = await res.json();
        var errorMsg = null;
        if (data && data.status && data.status.error) {
            errorMsg = data.status.error;
        } else if (data && data.summary && data.summary.error) {
            errorMsg = data.summary.error;
        }
        if (errorMsg) {
            if (errorMsg.indexOf('not a git repository') >= 0 || errorMsg.indexOf('Git repository check failed') >= 0) {
                diffFileList.innerHTML = '<div class="empty-state">此目录不是 Git 仓库</div>';
            } else if (errorMsg.indexOf('No changes detected') >= 0 || errorMsg.indexOf('No diff detected') >= 0) {
                diffFileList.innerHTML = '<div class="empty-state">无文件变更（工作区干净）</div>';
            } else {
                diffFileList.innerHTML = '<div class="empty-state">' + escapeHtml(errorMsg) + '</div>';
            }
            return;
        }
        currentDiffMode = reqMode;
        var files = (data && data.files) ? data.files : [];
        renderDiffFileList(files);
    } catch (e) {
        console.error('Refresh diff error:', e);
        diffFileList.innerHTML = '<div style="padding:1rem;color:red;">Error: ' + escapeHtml(e.message || String(e)) + '</div>';
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

/**
 * 截断文本到指定长度
 */
function truncateTextGlobal(text, maxLen = 100) {
    if (!text) return '';
    const str = String(text);
    return str.length > maxLen ? str.slice(0, maxLen) + '...' : str;
}

/**
 * 格式化文件大小
 */
function formatFileSizeGlobal(bytes) {
    if (bytes == null) return '?';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

/**
 * 根据工具名称智能渲染工具返回结果 (全局版本，供历史回放使用)
 */
function renderToolContentGlobal(toolName, rawContent) {
    if (rawContent === undefined || rawContent === null || rawContent === '') {
        return '<span class="tool-empty">无返回内容</span>';
    }

    let data = rawContent;
    if (typeof rawContent === 'string') {
        try { data = JSON.parse(rawContent); } catch (_) { /* keep raw */ }
    }

    // 如果有错误字段，直接返回错误展示
    if (data && typeof data === 'object' && data.error) {
        return `<div class="tool-result error">${escapeHtml(String(data.error))}</div>`;
    }

    const name = (toolName || '').toLowerCase();

    // ========== read_file_hunk: 代码片段展示 ==========
    if (name.includes('read_file_hunk') || name.includes('read_file') && data && data.snippet_with_line_numbers) {
        const filePath = data.path || '';
        const ctxStart = data.context_start || data.start_line || 1;
        const ctxEnd = data.context_end || data.end_line || ctxStart;
        const totalLines = data.total_lines || '?';
        const snippet = data.snippet_with_line_numbers || data.snippet || '';
        const ext = filePath.split('.').pop() || 'txt';
        const langMap = { py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript', json: 'json', yml: 'yaml', yaml: 'yaml', md: 'markdown', css: 'css', html: 'html' };
        const lang = langMap[ext.toLowerCase()] || ext;

        return `
            <div class="tool-code-block">
                <div class="code-header">
                    <span class="code-path" title="${escapeHtml(filePath)}">${getIcon('folder')} ${escapeHtml(filePath.split(/[\/\\]/).pop() || filePath)}</span>
                    <span class="code-range">行 ${ctxStart}-${ctxEnd} / 共 ${totalLines} 行</span>
                </div>
                <pre class="code-content" data-lang="${escapeHtml(lang)}"><code>${escapeHtml(snippet)}</code></pre>
            </div>
        `;
    }

    // ========== read_file_info: 文件信息卡片 ==========
    if (name.includes('read_file_info') || (data && data.line_count !== undefined && data.language !== undefined)) {
        const filePath = data.path || '';
        const size = data.size_bytes != null ? formatFileSizeGlobal(data.size_bytes) : '?';
        const lang = data.language || 'unknown';
        const lines = data.line_count || 0;
        const isTest = data.is_test_file ? '是' : '否';
        const isConfig = data.is_config_file ? '是' : '否';

        return `
            <div class="tool-file-info">
                <div class="file-info-header">
                    ${getIcon('folder')}
                    <span class="file-name">${escapeHtml(filePath.split(/[\/\\]/).pop() || filePath)}</span>
                </div>
                <div class="file-info-grid">
                    <div class="info-item"><span class="label">路径</span><span class="value" title="${escapeHtml(filePath)}">${escapeHtml(truncateTextGlobal(filePath, 60))}</span></div>
                    <div class="info-item"><span class="label">大小</span><span class="value">${escapeHtml(size)}</span></div>
                    <div class="info-item"><span class="label">语言</span><span class="value lang-badge">${escapeHtml(lang)}</span></div>
                    <div class="info-item"><span class="label">行数</span><span class="value">${lines}</span></div>
                    <div class="info-item"><span class="label">测试文件</span><span class="value">${isTest}</span></div>
                    <div class="info-item"><span class="label">配置文件</span><span class="value">${isConfig}</span></div>
                </div>
            </div>
        `;
    }

    // ========== search_in_project: 搜索结果列表 ==========
    if (name.includes('search') && data && Array.isArray(data.matches)) {
        const query = data.query || '';
        const matches = data.matches || [];
        if (matches.length === 0) {
            return `<div class="tool-search-empty">${getIcon('review')} 未找到匹配: <code>${escapeHtml(query)}</code></div>`;
        }
        const items = matches.slice(0, 20).map(m => {
            const fileName = (m.path || '').split(/[\/\\]/).pop() || m.path;
            return `
                <div class="search-match">
                    <span class="match-file" title="${escapeHtml(m.path)}">${escapeHtml(fileName)}</span>
                    <span class="match-line">:${m.line || 0}</span>
                    <code class="match-snippet">${escapeHtml(truncateTextGlobal(m.snippet || '', 120))}</code>
                </div>
            `;
        }).join('');
        const moreText = matches.length > 20 ? `<div class="search-more">... 共 ${matches.length} 条结果</div>` : '';
        return `
            <div class="tool-search-results">
                <div class="search-header">${getIcon('review')} 搜索 <code>${escapeHtml(query)}</code> — ${matches.length} 条匹配</div>
                <div class="search-list">${items}${moreText}</div>
            </div>
        `;
    }

    // ========== list_directory: 目录列表 ==========
    if (name.includes('list_dir') || name.includes('directory') || (data && data.directories !== undefined && data.files !== undefined)) {
        const dirPath = data.path || '';
        const dirs = data.directories || [];
        const files = data.files || [];
        const dirItems = dirs.slice(0, 30).map(d => `<span class="dir-item">${getIcon('folder')} ${escapeHtml(d)}</span>`).join('');
        const fileItems = files.slice(0, 50).map(f => `<span class="file-item">${escapeHtml(f)}</span>`).join('');
        const moreText = (dirs.length > 30 || files.length > 50) ? `<div class="dir-more">...</div>` : '';
        return `
            <div class="tool-directory">
                <div class="dir-header">${getIcon('folder')} ${escapeHtml(dirPath || '/')}</div>
                <div class="dir-content">
                    ${dirItems}
                    ${fileItems}
                    ${moreText}
                </div>
            </div>
        `;
    }

    // ========== 通用：尝试美化 JSON，否则显示原始文本 ==========
    if (typeof data === 'object') {
        const jsonStr = JSON.stringify(data, null, 2);
        return `<pre class="tool-json"><code>${escapeHtml(truncateTextGlobal(jsonStr, 3000))}</code></pre>`;
    }

    return `<pre class="tool-text"><code>${escapeHtml(truncateTextGlobal(String(rawContent), 2000))}</code></pre>`;
}

function formatToolArgsGlobal(toolName, rawArgs) {
    if (rawArgs === undefined || rawArgs === null || rawArgs === '') {
        return '<span class="tool-args-empty">无参数</span>';
    }
    let text = '';
    if (typeof rawArgs === 'string') {
        text = rawArgs;
    } else if (typeof rawArgs === 'object') {
        const preferred = ['path', 'start_line', 'end_line'];
        const keys = [...new Set([...preferred.filter(k => k in rawArgs), ...Object.keys(rawArgs)])];
        const parts = keys.map(k => {
            const v = rawArgs[k];
            const val = typeof v === 'object' ? JSON.stringify(v) : String(v ?? '');
            return `${k}=${val}`;
        });
        text = parts.join(', ');
    } else {
        text = String(rawArgs);
    }
    return `<code class="args-line">${escapeHtml(truncateTextGlobal(text, 200))}</code>`;
}


// --- Config Logic ---

async function loadConfig() {
    if (!configFormContainer) return;
    configFormContainer.innerHTML = 'Loading...';
    try {
        const [configRes, envRes] = await Promise.all([
            fetch('/api/config'),
            fetch('/api/env/vars')
        ]);

        if (!configRes.ok) {
            throw new Error(`HTTP ${configRes.status}`);
        }
        
        const config = await configRes.json();
        const envVars = envRes.ok ? await envRes.json() : {};
        
        renderConfigForm(config, envVars);
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
    "context.max_context_chars": "单字段最大长度 (字符)",
    "context.full_file_max_lines": "全文件读取限制 (行)",
    "context.callers_max_hits": "调用者最大命中数",
    "context.file_cache_ttl": "文件缓存时间 (秒)",
    "review.max_units_per_batch": "单次审查最大单元数",
    "review.enable_intent_cache": "启用意图缓存",
    "review.intent_cache_ttl_days": "意图缓存过期天数",
    "review.stream_chunk_sample_rate": "流式日志采样率",
    "fusion_thresholds.high": "高置信度阈值",
    "fusion_thresholds.medium": "中置信度阈值",
    "fusion_thresholds.low": "低置信度阈值"
};

const CONFIG_DESCRIPTIONS = {
    "llm.call_timeout": "单次 LLM API 调用的最大等待时间，超时将自动中断。",
    "llm.planner_timeout": "规划阶段（分析代码结构）的最大等待时间。",
    "llm.max_retries": "API 调用失败时的最大重试次数。",
    "llm.retry_delay": "每次重试前的等待时间，避免频繁请求。",
    "context.max_context_chars": "单字段最大字符数；每个上下文字段（diff/函数/文件/调用方等）分别截断。",
    "context.full_file_max_lines": "完整文件模式的最大行数，超过则按行截断或回退。",
    "context.callers_max_hits": "调用方搜索的最大命中数，用于限制收集的调用方片段数量。",
    "context.file_cache_ttl": "文件内容在内存中的缓存时间，减少磁盘 IO。",
    "review.max_units_per_batch": "单次审查任务包含的最大代码单元数量（如函数/类）。",
    "review.enable_intent_cache": "启用意图分析缓存；结果以 JSON 文件保存在 Agent/DIFF/rule/data，下次优先使用缓存。",
    "review.intent_cache_ttl_days": "意图缓存的过期天数；超期将自动清理缓存文件。",
    "review.stream_chunk_sample_rate": "流式日志采样率（数值越大记录越稀疏），用于调试用量。",
    "fusion_thresholds.high": "规则侧置信度≥此值时，以规则建议为主；若LLM建议的上下文级别更高，可升级。",
    "fusion_thresholds.medium": "介于低/高之间为中等置信区间；根据上下文级别优先级选择更高等级。",
    "fusion_thresholds.low": "规则侧置信度≤此值时，优先采纳 LLM 的上下文建议。"
};

function renderConfigForm(config, envVars = {}) {
    // Flatten or categorize config
    // For simplicity, we'll just dump JSON for now or simple key-values
    // A better implementation would allow editing specific fields
    
    let html = '';
    
    // Config Form
    if (config.llm) {
        html += `<div class="config-section">
            <div class="section-header">
                <h3>LLM 配置</h3>
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

    // Review Config Section
    if (config.review) {
        html += `<div class="config-section"><h3>审查配置</h3>`;
        for (const [key, val] of Object.entries(config.review)) {
             if (typeof val === 'object' && val !== null) continue;
             const label = CONFIG_LABELS[`review.${key}`] || key;
             html += createConfigInput(`review.${key}`, label, val);
        }
        html += `</div>`;
    }

    // Fusion Thresholds Section
    if (config.fusion_thresholds) {
        html += `<div class="config-section"><h3>融合阈值配置</h3>`;
        for (const [key, val] of Object.entries(config.fusion_thresholds)) {
             if (typeof val === 'object' && val !== null) continue;
             const label = CONFIG_LABELS[`fusion_thresholds.${key}`] || key;
             html += createConfigInput(`fusion_thresholds.${key}`, label, val);
        }
        html += `</div>`;
    }

    // 设置页不再显示环境变量与管理模型，改由仪表盘的弹窗进入

    if (!html) {
        html = '<div class="empty-state">无可用配置项</div>';
    }
    
    configFormContainer.innerHTML = html;
    attachConfigInteractions();
}

// Helper functions for Env Vars
window.createEnvVarInput = function(key, value) {
    const safeKey = escapeHtml(key);
    const safeVal = escapeHtml(value);
    const inputId = `env-value-${safeKey}`;
    return `
        <div class="env-var-row">
            <input type="text" class="env-key" value="${safeKey}" placeholder="KEY" readonly>
            <input id="${inputId}" type="password" class="env-value" value="${safeVal}" placeholder="VALUE" onchange="updateEnvVar('${safeKey}', this.value)">
            <button class="btn-icon" onclick="toggleEnvVisibility('${inputId}')" title="显示/隐藏">显示</button>
            <button class="btn-icon" onclick="deleteEnvVar('${safeKey}')" title="删除"><svg class="icon icon-trash"><use href="#icon-trash"></use></svg></button>
        </div>
    `;
};

window.toggleEnvVisibility = function(inputId){
    const el = document.getElementById(inputId);
    if (!el) return;
    el.type = el.type === 'password' ? 'text' : 'password';
};

window.addEnvVar = function() {
    const container = document.getElementById('env-vars-container');
    const div = document.createElement('div');
    div.className = 'env-var-row';
    div.innerHTML = `
        <input type="text" class="env-key-new" placeholder="KEY">
        <input type="text" class="env-value-new" placeholder="VALUE">
        <button class="btn-primary btn-small" onclick="saveNewEnvVar(this)">保存</button>
        <button class="btn-secondary btn-small" onclick="this.parentElement.remove()">取消</button>
    `;
    container.appendChild(div);
    div.querySelector('.env-key-new').focus();
};

window.saveNewEnvVar = async function(btn) {
    const row = btn.parentElement;
    const keyInput = row.querySelector('.env-key-new');
    const valInput = row.querySelector('.env-value-new');
    const key = keyInput.value.trim();
    const value = valInput.value.trim();
    
    if (!key) {
        showToast('请输入变量名', 'warning');
        return;
    }
    
    try {
        const res = await fetch('/api/env/vars', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value})
        });
        if (!res.ok) throw new Error('Failed to save');
        loadConfig(); 
        showToast('环境变量已添加', 'success');
    } catch (e) {
        console.error(e);
        showToast('保存失败', 'error');
    }
};

window.updateEnvVar = async function(key, value) {
    try {
        const res = await fetch('/api/env/vars', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, value})
        });
        if (!res.ok) throw new Error('Failed to update');
        showToast('环境变量已更新', 'success');
        try {
            window.__envVarsCache = window.__envVarsCache || {};
            window.__envVarsCache[key] = value || '';
            if (typeof refreshProviderStatus === 'function') {
                await refreshProviderStatus();
            } else {
                const sres = await fetch('/api/providers/status');
                if (sres.ok) {
                    const providers = await sres.json();
                    const total = providers.length || 0;
                    const avail = providers.filter(p=>p.available).length;
                    if (providerAvailableBadge) providerAvailableBadge.textContent = `${avail}/${total}`;
                    if (providerStatusContent) {
                        let html = '';
                        providers.forEach(p=>{
                            const dotClass = p.available ? 'success' : 'error';
                            const statusText = p.available ? '已配置' : '未配置';
                            const dot = `<span class="status-dot ${dotClass}" title="${escapeHtml(p.error || statusText)}"></span>`;
                            html += `<div class="stat-row"><span class="label">${p.label || p.name}:</span><span class="value" style="display:flex;align-items:center;gap:0.4rem">${dot}<span style="font-size:0.75rem;color:var(--text-muted)">${statusText}</span></span></div>`;
                        });
                        providerStatusContent.classList.add('compact-list');
                        providerStatusContent.innerHTML = html;
                    }
                }
            }
        } catch (_) {}
    } catch (e) {
        console.error(e);
        showToast('更新失败', 'error');
    }
};

async function refreshProviderStatus() {
    try {
        const res = await fetch('/api/providers/status');
        if (res.ok) {
            const providers = await res.json();
            const total = providers.length || 0;
            const avail = providers.filter(p=>p.available).length;
            if (providerAvailableBadge) providerAvailableBadge.textContent = `${avail}/${total}`;
            if (providerStatusContent) {
                let html = '';
                providers.forEach(p=>{
                    const dotClass = p.available ? 'success' : 'error';
                    const statusText = p.available ? '已配置' : '未配置';
                    const dot = `<span class="status-dot ${dotClass}" title="${escapeHtml(p.error || statusText)}"></span>`;
                    html += `<div class="stat-row"><span class="label">${p.label || p.name}:</span><span class="value" style="display:flex;align-items:center;gap:0.4rem">${dot}<span style="font-size:0.75rem;color:var(--text-muted)">${statusText}</span></span></div>`;
                });
                providerStatusContent.classList.add('compact-list');
                providerStatusContent.innerHTML = html;
            }
        }
    } catch (_) {}
}

window.deleteEnvVar = async function(key) {
    if (!confirm(`确定要删除环境变量 ${key} 吗？`)) return;
    try {
        const res = await fetch(`/api/env/vars/${encodeURIComponent(key)}`, {
            method: 'DELETE'
        });
        if (!res.ok) throw new Error('Failed to delete');
        loadConfig();
        showToast('环境变量已删除', 'success');
    } catch (e) {
        console.error(e);
        showToast('删除失败', 'error');
    }
};

function createConfigInput(fullKey, label, value) {
    const isBool = typeof value === 'boolean';
    const type = isBool ? 'checkbox' : (typeof value === 'number' ? 'number' : 'text');
    const checked = isBool && value ? 'checked' : '';
    const valueAttr = isBool ? '' : `value="${escapeHtml(value)}"`;
    
    // Description Lookup
    const description = CONFIG_DESCRIPTIONS[fullKey];
    const tooltipHtml = description ? `
        <div class="tooltip-container">
            <svg class="icon icon-info tooltip-trigger"><use href="#icon-info"></use></svg>
            <div class="tooltip-content">${escapeHtml(description)}</div>
        </div>
    ` : '';
    
    if (isBool) {
        return `
            <div class="form-group form-group-checkbox">
                <label class="checkbox-label">
                    <span class="checkbox-text-container">
                        <span class="checkbox-text">${escapeHtml(label)}</span>
                        ${tooltipHtml}
                    </span>
                    <span class="checkbox-status ${checked ? 'status-enabled' : 'status-disabled'}">
                        ${checked ? '已启用' : '已禁用'}
                    </span>
                    <input type="${type}" data-key="${escapeHtml(fullKey)}" ${checked} class="toggle-checkbox" role="switch" aria-checked="${checked ? 'true' : 'false'}">
                </label>
            </div>
        `;
    }
    
    return `
        <div class="form-group">
            <div class="label-container">
                <label>${escapeHtml(label)}</label>
                ${tooltipHtml}
            </div>
            <input type="${type}" data-key="${escapeHtml(fullKey)}" ${valueAttr} class="config-input">
        </div>
    `;
}

function attachConfigInteractions() {
    if (!configFormContainer) return;
    const labels = configFormContainer.querySelectorAll('.form-group-checkbox .checkbox-label');
    labels.forEach(label => {
        const input = label.querySelector('.toggle-checkbox');
        const status = label.querySelector('.checkbox-status');
        if (!input || !status) return;
        input.addEventListener('change', () => {
            const enabled = input.checked;
            status.textContent = enabled ? '已启用' : '已禁用';
            status.classList.toggle('status-enabled', enabled);
            status.classList.toggle('status-disabled', !enabled);
            input.setAttribute('aria-checked', enabled ? 'true' : 'false');
        });
        label.addEventListener('click', (e) => {
            if (e.target === input) return;
            input.click();
        });
    });
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
        await openWebFolderPicker();
    } catch (e) {
        console.error("Pick folder error:", e);
        showToast("选择文件夹失败: " + e.message, "error");
    }
}

async function openWebFolderPicker() {
    const existing = document.getElementById('folderPickerDialog');
    if (existing) existing.remove();
    const dialog = document.createElement('div');
    dialog.id = 'folderPickerDialog';
    dialog.className = 'modal-overlay';
    dialog.innerHTML = `
        <div class="modal-container folder-picker-container">
            <div class="modal-header">
                <h3>选择项目根目录</h3>
                <button class="icon-btn modal-close-btn" onclick="closeFolderPicker()"><svg class="icon"><use href="#icon-x"></use></svg></button>
            </div>
            <div class="modal-body">
                <div id="folderPickerPathBar" class="picker-toolbar">
                    <input id="folderPickerPathInput" type="text" class="bare-input picker-path-input" placeholder="输入或选择路径">
                    <div class="picker-actions">
                        <button class="btn-secondary" id="folderPickerGoBtn">前往</button>
                        <button class="btn-secondary" id="folderPickerUpBtn">上一级</button>
                        <button class="btn-secondary" id="folderPickerNativeBtn">使用系统选择器</button>
                    </div>
                </div>
                <div id="folderPickerList" class="file-list"></div>
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeFolderPicker()">取消</button>
                <button class="btn-primary" id="folderPickerConfirmBtn">选择此文件夹</button>
            </div>
        </div>
    `;
    document.body.appendChild(dialog);
    const pathInput = document.getElementById('folderPickerPathInput');
    const goBtn = document.getElementById('folderPickerGoBtn');
    const upBtn = document.getElementById('folderPickerUpBtn');
    const confirmBtn = document.getElementById('folderPickerConfirmBtn');
    const nativeBtn = document.getElementById('folderPickerNativeBtn');
    let currentPath = '';
    try {
        const resEnv = await fetch('/api/system/env');
        const env = resEnv.ok ? await resEnv.json() : {};
        if (env) {
            window.platform = env.platform || window.platform;
            window.isDockerEnv = !!env.is_docker;
        }
        currentPath = currentProjectRoot || env.default_project_root || '';
    } catch (_) {}
    if (pathInput) pathInput.value = currentPath || '';
    const loadList = async (p) => {
        const listEl = document.getElementById('folderPickerList');
        if (!listEl) return;
        listEl.innerHTML = '<div class="empty-state">加载中...</div>';
        try {
            const res = await fetch('/api/system/list-directory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: p }) });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (data.error) {
                listEl.innerHTML = `<div class="empty-state">${escapeHtml(data.error)}</div>`;
                return;
            }
            currentPath = data.path || p;
            if (pathInput) pathInput.value = currentPath || '';
            if (!data.children || data.children.length === 0) {
                listEl.innerHTML = '<div class="empty-state">空目录</div>';
                return;
            }
            listEl.innerHTML = data.children.map(c => `
                <div class="file-list-item" data-name="${escapeHtml(c.name)}">
                    <svg class="icon"><use href="#icon-folder"></use></svg>
                    <span>${escapeHtml(c.name)}</span>
                </div>
            `).join('');
            listEl.querySelectorAll('.file-list-item').forEach(item => {
                item.onclick = () => {
                    const name = item.getAttribute('data-name');
                    const sep = (currentPath.includes('\\') && !currentPath.includes('/')) ? '\\' : '/';
                    const np = (currentPath ? currentPath.replace(/[\\/]+$/,'') + sep : '') + name;
                    loadList(np);
                };
            });
        } catch (e) {
            listEl.innerHTML = `<div class="empty-state">${escapeHtml(e.message)}</div>`;
        }
    };
    if (currentPath) loadList(currentPath); else loadList(null);
    if (goBtn) goBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const p = pathInput ? pathInput.value : '';
        if (p) loadList(p);
    };
    if (pathInput) pathInput.onkeydown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            e.stopPropagation();
            const p = pathInput.value || '';
            if (p) loadList(p);
        }
    };
    if (upBtn) upBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const cur = pathInput ? pathInput.value : currentPath;
        let s = cur || '';
        if (!s) return;
        s = s.replace(/[\\/]+$/, '');
        const win = s.includes('\\') && !s.includes('/');
        const sep = win ? '\\' : '/';
        const idx = s.lastIndexOf(sep);
        if (idx <= 0) {
            loadList(s);
        } else {
            let parent = s.slice(0, idx);
            if (win && parent.length <= 2) parent = parent + '\\';
            loadList(parent);
        }
    };
    if (confirmBtn) confirmBtn.onclick = () => {
        const p = pathInput ? pathInput.value : '';
        if (p) {
            updateProjectPath(p);
            const dashboardPage = document.getElementById('page-dashboard');
            if (dashboardPage && dashboardPage.style.display !== 'none') {
                loadDashboardData();
            }
            const diffPage = document.getElementById('page-diff');
            if (diffPage && diffPage.style.display !== 'none') {
                refreshDiffAnalysis();
            }
            addSystemMessage(`已选择项目路径: ${escapeHtml(p)}`);
            closeFolderPicker();
        }
    };
    if (nativeBtn) {
        const isWin = (window.platform === 'win32');
        if (!isWin || window.isDockerEnv) {
            nativeBtn.style.display = 'none';
        } else {
            nativeBtn.style.display = 'inline-flex';
            nativeBtn.onclick = async (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                    const res = await fetch('/api/system/pick-folder', { method: 'POST' });
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    const data = await res.json();
                    if (data.error) {
                        showToast('系统选择器失败: ' + data.error, 'error');
                        return;
                    }
                    if (data.path) {
                        const p = data.path;
                        if (pathInput) pathInput.value = p;
                        updateProjectPath(p);
                        const dashboardPage = document.getElementById('page-dashboard');
                        if (dashboardPage && dashboardPage.style.display !== 'none') {
                            loadDashboardData();
                        }
                        const diffPage = document.getElementById('page-diff');
                        if (diffPage && diffPage.style.display !== 'none') {
                            refreshDiffAnalysis();
                        }
                        addSystemMessage(`已选择项目路径: ${escapeHtml(p)}`);
                        closeFolderPicker();
                    }
                } catch (err) {
                    showToast('系统选择器失败: ' + err.message, 'error');
                }
            };
        }
    }
    
}

function closeFolderPicker() {
    const dialog = document.getElementById('folderPickerDialog');
    if (dialog) dialog.remove();
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
    const monitorPanel = document.getElementById('monitorPanel');
    if (monitorPanel) {
        monitorPanel.classList.remove('ok', 'error');
        const titleEl = monitorPanel.querySelector('.panel-title');
        if (titleEl) titleEl.textContent = '日志';
    }
    
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
    let errorSeen = false;

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

    // 工具调用渲染状态存储
    const toolCallEntries = new Map();

    /**
     * 实时跟随始终启用
     */
    function isLiveFollowEnabled() {
        return true;
    }

    /**
     * 实时跟随：展开指定元素（如果折叠）并滚动到视图
     */
    function liveFollowExpand(el) {
        if (!el || !isLiveFollowEnabled()) return;
        if (el.classList.contains('collapsed')) {
            el.classList.remove('collapsed');
        }
    }

    /**
     * 实时跟随：折叠指定元素
     */
    function liveFollowCollapse(el) {
        if (!el || !isLiveFollowEnabled()) return;
        if (!el.classList.contains('collapsed')) {
            el.classList.add('collapsed');
        }
    }

    /**
     * 实时跟随：滚动工作流到底部
     */
    function liveFollowScroll() {
        if (!isLiveFollowEnabled()) return;
        // 滚动容器是 .workflow-content，而不是 #workflowEntries
        const scrollContainer = document.querySelector('#workflowPanel .workflow-content');
        if (scrollContainer) {
            scrollContainer.scrollTop = scrollContainer.scrollHeight;
        }
    }

    function truncateText(text, max = 240) {
        const safe = text == null ? '' : String(text);
        return safe.length > max ? `${safe.slice(0, max)}…` : safe;
    }

    function formatToolArgs(rawArgs) {
        if (rawArgs === undefined || rawArgs === null || rawArgs === '') {
            return '<span class="tool-args-empty">无参数</span>';
        }

        let parsed = rawArgs;
        if (typeof rawArgs === 'string') {
            try { parsed = JSON.parse(rawArgs); } catch (_) { /* keep raw */ }
        }

        if (typeof parsed === 'object') {
            const entries = Array.isArray(parsed)
                ? parsed.map((v, i) => [`#${i}`, v])
                : Object.entries(parsed);
            const limited = entries.slice(0, 6);
            const pills = limited.map(([k, v]) => {
                const valueText = typeof v === 'object' ? JSON.stringify(v) : String(v ?? '');
                return `<span class="kv-pill"><span class="kv-key">${escapeHtml(truncateText(k, 40))}</span><span class="kv-value">${escapeHtml(truncateText(valueText, 160))}</span></span>`;
            }).join('');
            const more = entries.length > limited.length ? '<span class="kv-pill muted">...</span>' : '';
            return `<div class="kv-pills">${pills}${more}</div>`;
        }

        return `<code class="mono">${escapeHtml(truncateText(parsed, 200))}</code>`;
    }

    function getToolKey(evt) {
        // 优先使用工具调用ID（每个工具调用的唯一标识）
        if (evt.tool_call_id) return `id-${evt.tool_call_id}`;
        // 回退：使用 call_index + tool_name + arguments_hash 生成唯一key
        const callIdx = evt.call_index ?? 'x';
        const toolName = evt.tool_name || evt.tool || 'tool';
        const argsStr = typeof evt.arguments === 'string' ? evt.arguments : JSON.stringify(evt.arguments || '');
        // 简单hash函数
        let hash = 0;
        for (let i = 0; i < argsStr.length; i++) {
            hash = ((hash << 5) - hash) + argsStr.charCodeAt(i);
            hash = hash & hash; // Convert to 32bit integer
        }
        return `${callIdx}-${toolName}-${hash}`;
    }

    function ensureToolCard(stageContent, evt) {
        const key = getToolKey(evt);
        const name = evt.tool_name || evt.tool || '未知工具';
        let entry = toolCallEntries.get(key);
        if (entry) return entry;

        const card = document.createElement('div');
        card.className = 'workflow-tool';
        card.dataset.callKey = key;
        card.innerHTML = `
            <div class="tool-head">
                <div class="tool-title">
                    ${getIcon('terminal')}
                    <div class="tool-title-text">
                        <span class="tool-name">${escapeHtml(name)}</span>
                        ${evt.call_index !== undefined && evt.call_index !== null ? `<span class="tool-badge">#${escapeHtml(String(evt.call_index))}</span>` : ''}
                    </div>
                </div>
                <span class="tool-status status-running">调用中</span>
            </div>
            <div class="tool-section tool-args">${formatToolArgs(evt.arguments || evt.detail)}</div>
            <div class="tool-section tool-output" style="display:none"></div>
            <div class="tool-section tool-meta" style="display:none"></div>
        `;
        stageContent.appendChild(card);

        entry = {
            key,
            card,
            statusEl: card.querySelector('.tool-status'),
            argsEl: card.querySelector('.tool-args'),
            outputEl: card.querySelector('.tool-output'),
            metaEl: card.querySelector('.tool-meta'),
            name,
        };
        toolCallEntries.set(key, entry);
        return entry;
    }

    function setToolStatus(entry, status, label) {
        if (!entry || !entry.statusEl) return;
        entry.statusEl.className = `tool-status status-${status}`;
        entry.statusEl.textContent = label;
    }

    function updateToolMeta(entry, evt) {
        if (!entry || !entry.metaEl) return;
        const chips = [];
        if (evt.duration_ms !== undefined && evt.duration_ms !== null) {
            chips.push(`<span class="meta-chip">耗时 ${Math.round(evt.duration_ms)}ms</span>`);
        }
        if (evt.cpu_time !== undefined && evt.cpu_time !== null) {
            chips.push(`<span class="meta-chip">CPU ${escapeHtml(String(evt.cpu_time))}</span>`);
        }
        if (evt.mem_delta !== undefined && evt.mem_delta !== null) {
            chips.push(`<span class="meta-chip">内存 Δ${escapeHtml(String(evt.mem_delta))}</span>`);
        }
        if (chips.length === 0) return;
        entry.metaEl.innerHTML = chips.join('');
        entry.metaEl.style.display = 'flex';
    }

    /**
     * 根据工具名称智能渲染工具返回结果
     */
    function renderToolContent(toolName, rawContent) {
        if (rawContent === undefined || rawContent === null || rawContent === '') {
            return '<span class="tool-empty">无返回内容</span>';
        }

        let data = rawContent;
        if (typeof rawContent === 'string') {
            try { data = JSON.parse(rawContent); } catch (_) { /* keep raw */ }
        }

        // 如果有错误字段，直接返回错误展示
        if (data && typeof data === 'object' && data.error) {
            return `<div class="tool-result error">${escapeHtml(String(data.error))}</div>`;
        }

        const name = (toolName || '').toLowerCase();

        // ========== read_file_hunk: 代码片段展示 ==========
        if (name.includes('read_file_hunk') || name.includes('read_file') && data && data.snippet_with_line_numbers) {
            const filePath = data.path || '';
            const ctxStart = data.context_start || data.start_line || 1;
            const ctxEnd = data.context_end || data.end_line || ctxStart;
            const totalLines = data.total_lines || '?';
            const snippet = data.snippet_with_line_numbers || data.snippet || '';
            const ext = filePath.split('.').pop() || 'txt';
            const langMap = { py: 'python', js: 'javascript', ts: 'typescript', jsx: 'javascript', tsx: 'typescript', json: 'json', yml: 'yaml', yaml: 'yaml', md: 'markdown', css: 'css', html: 'html' };
            const lang = langMap[ext.toLowerCase()] || ext;

            return `
                <div class="tool-code-block">
                    <div class="code-header">
                        <span class="code-path" title="${escapeHtml(filePath)}">${getIcon('folder')} ${escapeHtml(filePath.split(/[\/\\]/).pop() || filePath)}</span>
                        <span class="code-range">行 ${ctxStart}-${ctxEnd} / 共 ${totalLines} 行</span>
                    </div>
                    <pre class="code-content" data-lang="${escapeHtml(lang)}"><code>${escapeHtml(snippet)}</code></pre>
                </div>
            `;
        }

        // ========== read_file_info: 文件信息卡片 ==========
        if (name.includes('read_file_info') || (data && data.line_count !== undefined && data.language !== undefined)) {
            const filePath = data.path || '';
            const size = data.size_bytes != null ? formatFileSize(data.size_bytes) : '?';
            const lang = data.language || 'unknown';
            const lines = data.line_count || 0;
            const isTest = data.is_test_file ? '是' : '否';
            const isConfig = data.is_config_file ? '是' : '否';

            return `
                <div class="tool-file-info">
                    <div class="file-info-header">
                        ${getIcon('folder')}
                        <span class="file-name">${escapeHtml(filePath.split(/[\/\\]/).pop() || filePath)}</span>
                    </div>
                    <div class="file-info-grid">
                        <div class="info-item"><span class="label">路径</span><span class="value" title="${escapeHtml(filePath)}">${escapeHtml(truncateText(filePath, 60))}</span></div>
                        <div class="info-item"><span class="label">大小</span><span class="value">${escapeHtml(size)}</span></div>
                        <div class="info-item"><span class="label">语言</span><span class="value lang-badge">${escapeHtml(lang)}</span></div>
                        <div class="info-item"><span class="label">行数</span><span class="value">${lines}</span></div>
                        <div class="info-item"><span class="label">测试文件</span><span class="value">${isTest}</span></div>
                        <div class="info-item"><span class="label">配置文件</span><span class="value">${isConfig}</span></div>
                    </div>
                </div>
            `;
        }

        // ========== search_in_project: 搜索结果列表 ==========
        if (name.includes('search') && data && Array.isArray(data.matches)) {
            const query = data.query || '';
            const matches = data.matches || [];
            if (matches.length === 0) {
                return `<div class="tool-search-empty">${getIcon('review')} 未找到匹配: <code>${escapeHtml(query)}</code></div>`;
            }
            const items = matches.slice(0, 20).map(m => {
                const fileName = (m.path || '').split(/[\/\\]/).pop() || m.path;
                return `
                    <div class="search-match">
                        <span class="match-file" title="${escapeHtml(m.path)}">${escapeHtml(fileName)}</span>
                        <span class="match-line">:${m.line || 0}</span>
                        <code class="match-snippet">${escapeHtml(truncateText(m.snippet || '', 120))}</code>
                    </div>
                `;
            }).join('');
            const moreText = matches.length > 20 ? `<div class="search-more">... 共 ${matches.length} 条结果</div>` : '';
            return `
                <div class="tool-search-results">
                    <div class="search-header">${getIcon('review')} 搜索 <code>${escapeHtml(query)}</code> — ${matches.length} 条匹配</div>
                    <div class="search-list">${items}${moreText}</div>
                </div>
            `;
        }

        // ========== list_directory: 目录列表 ==========
        if (name.includes('list_dir') || name.includes('directory') || (data && data.directories !== undefined && data.files !== undefined)) {
            const dirPath = data.path || '';
            const dirs = data.directories || [];
            const files = data.files || [];
            const dirItems = dirs.slice(0, 30).map(d => `<span class="dir-item">${getIcon('folder')} ${escapeHtml(d)}</span>`).join('');
            const fileItems = files.slice(0, 50).map(f => `<span class="file-item">${escapeHtml(f)}</span>`).join('');
            const moreText = (dirs.length > 30 || files.length > 50) ? `<div class="dir-more">...</div>` : '';
            return `
                <div class="tool-directory">
                    <div class="dir-header">${getIcon('folder')} ${escapeHtml(dirPath || '/')}</div>
                    <div class="dir-content">
                        ${dirItems}
                        ${fileItems}
                        ${moreText}
                    </div>
                </div>
            `;
        }

        // ========== 通用：尝试美化 JSON，否则显示原始文本 ==========
        if (typeof data === 'object') {
            const jsonStr = JSON.stringify(data, null, 2);
            return `<pre class="tool-json"><code>${escapeHtml(truncateText(jsonStr, 3000))}</code></pre>`;
        }

        return `<pre class="tool-text"><code>${escapeHtml(truncateText(String(rawContent), 2000))}</code></pre>`;
    }

    function formatFileSize(bytes) {
        if (bytes == null) return '?';
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    }

    function updateToolOutput(entry, evt) {
        if (!entry || !entry.outputEl) return;
        const hasError = !!evt.error;
        let body;
        if (hasError) {
            body = `<div class="tool-result error">${escapeHtml(String(evt.error))}</div>`;
        } else {
            body = `<div class="tool-result success">${renderToolContent(entry.name, evt.content)}</div>`;
        }
        entry.outputEl.innerHTML = body;
        entry.outputEl.style.display = 'block';
        setToolStatus(entry, hasError ? 'error' : 'success', hasError ? '失败' : '完成');
        updateToolMeta(entry, evt);
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
                // 初始状态：如果开启实时跟随则展开，否则折叠
                currentThoughtEl.className = isLiveFollowEnabled() ? 'workflow-thought' : 'workflow-thought collapsed';
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
            // 实时跟随：滚动思考块内部到底部
            const thoughtBody = currentThoughtEl.querySelector('.thought-body');
            if (thoughtBody) {
                thoughtBody.scrollTop = thoughtBody.scrollHeight;
            }
            // 实时跟随：滚动工作流面板到底部
            liveFollowScroll();
            return;
        }

        // 处理流式内容输出
        if (evt.type === 'chunk') {
            // 停止思考计时器（chunk 表示思考结束）
            stopThoughtTimer();
            // 实时跟随：折叠思考块
            if (currentThoughtEl) {
                liveFollowCollapse(currentThoughtEl);
            }
            
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
        // 实时跟随：折叠之前的 chunk wrapper
        if (currentChunkEl) {
            const wrapper = currentChunkEl.closest('.workflow-chunk-wrapper');
            if (wrapper) {
                liveFollowCollapse(wrapper);
            }
        }
        currentChunkEl = null;
        // 实时跟随：折叠思考块
        if (currentThoughtEl) {
            liveFollowCollapse(currentThoughtEl);
        }
        stopThoughtTimer();

        // 处理工具调用开始/结束/结果
        if (evt.type === 'tool_start' || evt.type === 'tool_call_start' || evt.type === 'tool_result' || evt.type === 'tool_call_end') {
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

            const entry = ensureToolCard(stageContent, evt);
            if (evt.type === 'tool_result') {
                updateToolOutput(entry, evt);
            } else if (evt.type === 'tool_call_end') {
                setToolStatus(entry, evt.success === false ? 'error' : 'success', evt.success === false ? '失败' : '完成');
                updateToolMeta(entry, evt);
            } else {
                // tool_start/tool_call_start: refresh args/status
                if (entry.argsEl && (evt.arguments || evt.detail)) {
                    entry.argsEl.innerHTML = formatToolArgs(evt.arguments || evt.detail);
                }
                setToolStatus(entry, 'running', '调用中');
            }
            // 实时跟随：滚动到底部
            liveFollowScroll();
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
        if (evt.type === 'thought' || evt.type === 'tool_start' || evt.type === 'tool_result' || evt.type === 'tool_call_end' || evt.type === 'chunk' || evt.type === 'workflow_chunk' || evt.type === 'tool_call_start') {
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
                    const entry = ensureToolCard(stageContent, {
                        tool_name: name,
                        arguments: argText,
                        call_index: call.index ?? call.call_index,
                    });
                    if (entry.argsEl) {
                        entry.argsEl.innerHTML = formatToolArgs(argText);
                    }
                    setToolStatus(entry, 'running', '调用中');
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
            // 保存累计消耗，供最后显示
            SessionState.lastSessionUsage = totals;
            
            const stageText = evt.usage_stage || '';
            const callIndex = evt.call_index;
            const item = document.createElement('div');
            item.className = 'process-item api-call-card';
            const idx = (callIndex !== undefined && callIndex !== null) ? `#${callIndex}` : '';
            item.innerHTML = `
                <div class="api-call-header">
                    <div class="api-title-group">
                        <svg class="icon api-icon"><use href="#icon-zap"></use></svg>
                        <span class="api-title">API调用 ${idx}</span>
                    </div>
                    ${stageText ? `<span class="api-stage-badge">${escapeHtml(stageText)}</span>` : ''}
                </div>
                <div class="api-stats-grid">
                    <div class="stat-row">
                        <span class="stat-label">消耗</span>
                        <span class="stat-value">${call.total ?? '-'}</span>
                        <span class="stat-detail"><span class="stat-in" title="Input Tokens">↑${call.in ?? '-'}</span> <span class="stat-out" title="Output Tokens">↓${call.out ?? '-'}</span></span>
                    </div>
                </div>
            `;
            monitorEntries.appendChild(item);
            return;
        }

        if (evt.type === 'final') {
            setProgressStep('reviewing', 'completed');
            setProgressStep('reporting', 'active');
            
            // 显示最终 Token 消耗总结
            if (SessionState.lastSessionUsage && monitorEntries) {
                const totals = SessionState.lastSessionUsage;
                const item = document.createElement('div');
                item.className = 'process-item api-summary-card';
                item.innerHTML = `
                    <div class="api-call-header">
                        <div class="api-title-group">
                            <svg class="icon api-icon"><use href="#icon-trending-up"></use></svg>
                            <span class="api-title">Token 消耗总计</span>
                        </div>
                    </div>
                    <div class="api-stats-grid">
                        <div class="stat-row">
                            <span class="stat-label">总计</span>
                            <span class="stat-value">${totals.total ?? '-'}</span>
                            <span class="stat-detail"><span class="stat-in" title="Total Input">↑${totals.in ?? '-'}</span> <span class="stat-out" title="Total Output">↓${totals.out ?? '-'}</span></span>
                        </div>
                    </div>
                `;
                monitorEntries.appendChild(item);
                // 清除状态，避免重复显示
                SessionState.lastSessionUsage = null;
            }
            
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
                
                // 报告完成后，平滑滚动到顶部
                requestAnimationFrame(() => {
                    reportCanvasContainer.scrollTo({
                        top: 0,
                        behavior: 'smooth'
                    });
                });
            }
            
            let score = null;
            const scoreMatch = finalContent.match(/(?:评分|Score|分数)[:\s]*(\d+)/i);
            if (scoreMatch) score = parseInt(scoreMatch[1], 10);
            triggerCompletionTransition(null, score, true);
            const monitorPanel = document.getElementById('monitorPanel');
            if (monitorPanel && !fallbackSeen && !errorSeen) {
                monitorPanel.classList.add('ok');
                const titleEl = monitorPanel.querySelector('.panel-title');
                if (titleEl) titleEl.textContent = '日志 · 运行正常';
            }
            stopReviewTimer();
            streamEnded = true;
            return;
        }

        if (evt.type === 'error') {
            errorSeen = true;
            const monitorPanel = document.getElementById('monitorPanel');
            if (monitorPanel) {
                monitorPanel.classList.remove('ok');
                monitorPanel.classList.add('error');
                const titleEl = monitorPanel.querySelector('.panel-title');
                if (titleEl) titleEl.textContent = '日志 · 运行异常';
                monitorPanel.classList.remove('collapsed');
            }
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
        const monitorPanel = document.getElementById('monitorPanel');
        if (monitorPanel) {
            monitorPanel.classList.remove('ok');
            monitorPanel.classList.add('error');
            const titleEl = monitorPanel.querySelector('.panel-title');
            if (titleEl) titleEl.textContent = '日志 · 连接异常';
            monitorPanel.classList.remove('collapsed');
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
                // 查找对应的 tool_result 事件
                const toolName = evt.tool || evt.tool_name || '未知工具';
                const toolCallId = evt.tool_call_id;
                const callIndex = evt.call_index;
                
                // 在后续事件中查找匹配的 tool_result
                let resultEvt = null;
                for (let j = idx + 1; j < stageEvents.length; j++) {
                    const candidateEvt = stageEvents[j];
                    if (candidateEvt.type === 'tool_result') {
                        // 优先匹配 tool_call_id
                        if (toolCallId && candidateEvt.tool_call_id === toolCallId) {
                            resultEvt = candidateEvt;
                            break;
                        }
                        // 其次匹配 tool_name 和 call_index
                        if ((candidateEvt.tool_name === toolName || candidateEvt.tool === toolName) &&
                            (callIndex === undefined || candidateEvt.call_index === callIndex)) {
                            resultEvt = candidateEvt;
                            break;
                        }
                    }
                }
                
                const toolEl = document.createElement('div');
                toolEl.className = 'workflow-tool';
                
                // 格式化参数显示
                let argsHtml = '';
                const detail = evt.detail || evt.arguments || '';
                if (detail) {
                    argsHtml = `<div class="tool-section tool-args">${formatToolArgsGlobal(toolName, detail)}</div>`;
                }
                
                // 渲染工具输出
                let outputHtml = '';
                let statusClass = 'status-success';
                let statusText = '完成';
                
                if (resultEvt) {
                    const hasError = !!resultEvt.error;
                    statusClass = hasError ? 'status-error' : 'status-success';
                    statusText = hasError ? '失败' : '完成';
                    
                    if (hasError) {
                        outputHtml = `<div class="tool-section tool-output"><div class="tool-result error">${escapeHtml(String(resultEvt.error))}</div></div>`;
                    } else if (resultEvt.content !== undefined && resultEvt.content !== null) {
                        outputHtml = `<div class="tool-section tool-output"><div class="tool-result success">${renderToolContentGlobal(toolName, resultEvt.content)}</div></div>`;
                    }
                } else {
                    // 没有找到结果事件（旧数据），只显示基本信息
                    statusClass = 'status-success';
                    statusText = '已执行';
                }
                
                toolEl.innerHTML = `
                    <div class="tool-head">
                        <div class="tool-title">
                            ${getIcon('terminal')}
                            <div class="tool-title-text">
                                <span class="tool-name">${escapeHtml(toolName)}</span>
                            </div>
                        </div>
                        <span class="tool-status ${statusClass}">${statusText}</span>
                    </div>
                    ${argsHtml}
                    ${outputHtml}
                `;
                stageContent.appendChild(toolEl);
            } else if (evt.type === 'tool_result') {
                // tool_result 已在 tool_start/tool_call_start 中处理，跳过
                // 避免重复渲染
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
    let lastSessionUsage = null;
    
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
            // 记录最后的累计消耗
            lastSessionUsage = totals;

            const stageText = evt.usage_stage || '';
            const callIndex = evt.call_index;
            const item = document.createElement('div');
            item.className = 'process-item api-call-card';
            const idx = (callIndex !== undefined && callIndex !== null) ? `#${callIndex}` : '';
            item.innerHTML = `
                <div class="api-call-header">
                    <div class="api-title-group">
                        <svg class="icon api-icon"><use href="#icon-zap"></use></svg>
                        <span class="api-title">API调用 ${idx}</span>
                    </div>
                    ${stageText ? `<span class="api-stage-badge">${escapeHtml(stageText)}</span>` : ''}
                </div>
                <div class="api-stats-grid">
                    <div class="stat-row">
                        <span class="stat-label">消耗</span>
                        <span class="stat-value">${call.total ?? '-'}</span>
                        <span class="stat-detail"><span class="stat-in" title="Input Tokens">↑${call.in ?? '-'}</span> <span class="stat-out" title="Output Tokens">↓${call.out ?? '-'}</span></span>
                    </div>
                </div>
            `;
            container.appendChild(item);
        }
    });

    // 如果有累计消耗数据，在最后显示汇总卡片
    if (lastSessionUsage) {
        const totals = lastSessionUsage;
        const item = document.createElement('div');
        item.className = 'process-item api-summary-card';
        item.innerHTML = `
            <div class="api-call-header">
                <div class="api-title-group">
                    <svg class="icon api-icon"><use href="#icon-trending-up"></use></svg>
                    <span class="api-title">Token 消耗总计</span>
                </div>
            </div>
            <div class="api-stats-grid">
                <div class="stat-row">
                    <span class="stat-label">总计</span>
                    <span class="stat-value">${totals.total ?? '-'}</span>
                    <span class="stat-detail"><span class="stat-in" title="Total Input">↑${totals.in ?? '-'}</span> <span class="stat-out" title="Total Output">↓${totals.out ?? '-'}</span></span>
                </div>
            </div>
        `;
        container.appendChild(item);
    }
    
    // 更新监控面板状态
    const monitorPanel = document.getElementById('monitorPanel');
    if (monitorPanel) {
        if (hasWarnings) {
            monitorPanel.classList.remove('ok');
            monitorPanel.classList.add('warning');
            const titleEl = monitorPanel.querySelector('.panel-title');
            if (titleEl) titleEl.textContent = '日志 · 存在回退';
        } else {
            monitorPanel.classList.remove('warning');
            monitorPanel.classList.remove('error');
            monitorPanel.classList.add('ok');
            const titleEl = monitorPanel.querySelector('.panel-title');
            if (titleEl) titleEl.textContent = '日志 · 正常';
        }
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
                    <p>准备好审查您的代码，请选择一个项目文件夹开始。</p>
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
        const pkModal = document.getElementById('providerKeysModal');
        if (event.target === pkModal) {
            closeProviderKeysModal();
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
                <button class="icon-btn-small delete-btn" onclick="deleteModel('${g.provider}', '${escapeHtml(m.label || m.name)}')">
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
            body: JSON.stringify({ provider: provider, model_name: name })
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

async function deleteModel(provider, modelName) {
    if (!confirm(`确定要删除模型 ${modelName} 吗？`)) return;
    
    try {
        const modelId = (modelName && modelName.includes(':')) ? modelName.split(':').slice(-1)[0] : modelName;
        const res = await fetch('/api/models/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ provider: provider, model_name: modelId })
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
                    <p>准备好审查您的代码，请选择一个项目文件夹开始。</p>
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


// ==================== 规则优化功能 ====================

/**
 * 加载规则优化页面数据
 */
async function loadRuleGrowthData() {
    try {
        await Promise.all([
            loadRuleGrowthSummary(),
            loadEnhancedSuggestions()
        ]);
    } catch (e) {
        console.error('Load rule growth data error:', e);
        showToast('加载规则数据失败: ' + e.message, 'error');
    }
}

/**
 * 加载冲突汇总统计
 */
async function loadRuleGrowthSummary() {
    const summaryContent = document.getElementById('rg-summary-content');
    const summaryEmpty = document.getElementById('rg-summary-empty');
    const totalBadge = document.getElementById('rg-total-badge');
    
    try {
        const res = await fetch('/api/rule-growth/summary');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        
        const data = await res.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        const total = data.total_conflicts || 0;
        if (totalBadge) totalBadge.textContent = total;
        
        if (total === 0) {
            if (summaryEmpty) summaryEmpty.style.display = 'flex';
            if (summaryContent) summaryContent.innerHTML = '';  // 清空内容
            return;
        }
        
        if (summaryEmpty) summaryEmpty.style.display = 'none';
        
        // 渲染统计内容
        let html = '';
        
        // 总数显示
        html += `<div class="stat-total" style="text-align: center; padding: 1rem 0; margin-bottom: 1rem; background: #f9fafb; border-radius: 8px;">
            <div style="font-size: 2rem; font-weight: 700; color: var(--primary);">${total}</div>
            <div style="font-size: 0.8rem; color: var(--text-muted);">总冲突数</div>
        </div>`;
        
        // 按类型分组
        if (data.by_type && Object.keys(data.by_type).length > 0) {
            html += '<div class="stat-section"><h4>按冲突类型</h4><div class="stat-list">';
            for (const [type, count] of Object.entries(data.by_type)) {
                const typeLabel = getRuleGrowthTypeLabel(type);
                const typeIcon = getRuleGrowthTypeIcon(type);
                html += `<div class="stat-row">
                    <span class="label">${typeIcon} ${escapeHtml(typeLabel)}</span>
                    <span class="value">${count}</span>
                </div>`;
            }
            html += '</div></div>';
        }
        
        // 按语言分组
        if (data.by_language && Object.keys(data.by_language).length > 0) {
            html += '<div class="stat-section"><h4>按语言</h4><div class="stat-list">';
            for (const [lang, count] of Object.entries(data.by_language)) {
                const langLabel = formatLanguageLabel(lang);
                html += `<div class="stat-row">
                    <span class="label">${escapeHtml(langLabel)}</span>
                    <span class="value">${count}</span>
                </div>`;
            }
            html += '</div></div>';
        }
        
        if (summaryContent) summaryContent.innerHTML = html;
        
    } catch (e) {
        console.error('Load rule growth summary error:', e);
        if (summaryContent) {
            summaryContent.innerHTML = `<div class="error-text">加载失败: ${escapeHtml(e.message)}</div>`;
        }
    }
}

/**
 * 获取冲突类型的图标（使用 SVG）
 */
function getRuleGrowthTypeIcon(type) {
    const iconMap = {
        'rule_high_llm_expand': 'trending-up',
        'rule_high_llm_skip': 'x',
        'rule_low_llm_consistent': 'lightbulb',
        'context_level_mismatch': 'alert-triangle'
    };
    const iconName = iconMap[type] || 'rule';
    return `<svg class="icon icon-small"><use href="#icon-${iconName}"></use></svg>`;
}

// 语言友好名映射，扩大常见语言覆盖
function formatLanguageLabel(lang) {
    if (!lang) return 'unknown';
    const lower = String(lang).toLowerCase();
    const map = {
        javascript: 'JavaScript', js: 'JavaScript',
        typescript: 'TypeScript', ts: 'TypeScript',
        python: 'Python', py: 'Python',
        java: 'Java',
        go: 'Go', golang: 'Go',
        ruby: 'Ruby', rb: 'Ruby',
        rust: 'Rust', rs: 'Rust',
        php: 'PHP',
        'c#': 'C#', cs: 'C#',
        c: 'C', cpp: 'C++', cxx: 'C++',
        scala: 'Scala',
        kotlin: 'Kotlin', kt: 'Kotlin',
        swift: 'Swift',
        'objective-c': 'Objective-C', objc: 'Objective-C',
        shell: 'Shell', bash: 'Bash', sh: 'Shell',
        powershell: 'PowerShell', ps1: 'PowerShell',
        html: 'HTML', css: 'CSS', scss: 'SCSS', less: 'LESS',
        sql: 'SQL',
        yaml: 'YAML', yml: 'YAML',
        json: 'JSON', md: 'Markdown', markdown: 'Markdown'
    };
    return map[lower] || lang;
}

/**
 * 加载规则优化建议
 */
async function loadRuleGrowthSuggestions() {
    const suggestionsContent = document.getElementById('rg-suggestions-content');
    const suggestionsEmpty = document.getElementById('rg-suggestions-empty');
    const suggestionsList = document.getElementById('rg-suggestions-list');
    const suggestionsBadge = document.getElementById('rg-suggestions-badge');
    
    try {
        const res = await fetch('/api/rule-growth/suggestions');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        
        const data = await res.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        const suggestions = data.suggestions || [];
        const total = suggestions.length;
        
        if (suggestionsBadge) suggestionsBadge.textContent = total;
        
        if (total === 0) {
            if (suggestionsEmpty) suggestionsEmpty.style.display = 'flex';
            if (suggestionsList) suggestionsList.style.display = 'none';
            return;
        }
        
        if (suggestionsEmpty) suggestionsEmpty.style.display = 'none';
        if (suggestionsList) suggestionsList.style.display = 'block';
        
        // 按置信度排序（API 已排序，但确保一下）
        suggestions.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
        
        // 渲染建议列表
        let html = '';
        for (const suggestion of suggestions) {
            const typeLabel = getSuggestionTypeLabel(suggestion.type);
            const typeBadgeClass = getSuggestionTypeBadgeClass(suggestion.type);
            const confidence = Math.round((suggestion.confidence || 0) * 100);
            const occurrences = suggestion.occurrence_count || 0;
            
            html += `
                <div class="suggestion-item">
                    <div class="suggestion-header">
                        <span class="badge ${typeBadgeClass}">${escapeHtml(typeLabel)}</span>
                        <span class="suggestion-confidence">${confidence}% 置信度</span>
                    </div>
                    <div class="suggestion-body">
                        ${suggestion.suggested_change ? `<p class="suggestion-change">${escapeHtml(suggestion.suggested_change)}</p>` : ''}
                        ${suggestion.rule_notes ? `<p class="suggestion-rule"><strong>规则:</strong> ${escapeHtml(suggestion.rule_notes)}</p>` : ''}
                        ${suggestion.language ? `<p class="suggestion-lang"><strong>语言:</strong> ${escapeHtml(suggestion.language)}</p>` : ''}
                        <p class="suggestion-meta">出现 ${occurrences} 次</p>
                    </div>
                    ${suggestion.sample_files && suggestion.sample_files.length > 0 ? `
                        <div class="suggestion-files">
                            <span class="files-label">示例文件:</span>
                            <ul class="files-list">
                                ${suggestion.sample_files.slice(0, 3).map(f => `<li>${escapeHtml(f)}</li>`).join('')}
                            </ul>
                        </div>
                    ` : ''}
                </div>
            `;
        }
        
        if (suggestionsList) suggestionsList.innerHTML = html;
        
    } catch (e) {
        console.error('Load rule growth suggestions error:', e);
        if (suggestionsContent) {
            suggestionsContent.innerHTML = `<div class="error-text">加载失败: ${escapeHtml(e.message)}</div>`;
        }
    }
}

/**
 * 加载增强的规则建议（可应用规则和参考提示）
 */
async function loadEnhancedSuggestions() {
    const applicableContent = document.getElementById('rg-applicable-content');
    const applicableEmpty = document.getElementById('rg-applicable-empty');
    const applicableList = document.getElementById('rg-applicable-list');
    const applicableBadge = document.getElementById('rg-applicable-badge');
    
    const hintsContent = document.getElementById('rg-hints-content');
    const hintsEmpty = document.getElementById('rg-hints-empty');
    const hintsList = document.getElementById('rg-hints-list');
    const hintsBadge = document.getElementById('rg-hints-badge');
    
    try {
        const res = await fetch('/api/rule-growth/enhanced-suggestions');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        
        const data = await res.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        const applicableRules = data.applicable_rules || [];
        const referenceHints = data.reference_hints || [];
        
        // 渲染可应用规则
        if (applicableBadge) applicableBadge.textContent = applicableRules.length;
        
        if (applicableRules.length === 0) {
            if (applicableEmpty) applicableEmpty.style.display = 'flex';
            if (applicableList) applicableList.style.display = 'none';
        } else {
            if (applicableEmpty) applicableEmpty.style.display = 'none';
            if (applicableList) {
                applicableList.style.display = 'block';
                applicableList.innerHTML = applicableRules.map(rule => renderApplicableRule(rule)).join('');
            }
        }
        
        // 渲染参考提示（按语言分组）
        // **Feature: rule-growth-layout-optimization**
        // **Validates: Requirements 6.1, 6.2, 6.3**
        if (hintsBadge) hintsBadge.textContent = referenceHints.length;
        
        if (referenceHints.length === 0) {
            if (hintsEmpty) hintsEmpty.style.display = 'flex';
            if (hintsList) hintsList.style.display = 'none';
        } else {
            if (hintsEmpty) hintsEmpty.style.display = 'none';
            if (hintsList) {
                hintsList.style.display = 'block';
                // 使用按语言分组的渲染方式
                hintsList.innerHTML = renderGroupedHintsByLanguage(referenceHints);
            }
        }
        
    } catch (e) {
        console.error('Load enhanced suggestions error:', e);
        if (applicableContent) {
            applicableContent.innerHTML = `<div class="error-text">加载失败: ${escapeHtml(e.message)}</div>`;
        }
    }
}

/**
 * 渲染可应用规则卡片
 */
function renderApplicableRule(rule) {
    const tagsHtml = rule.required_tags.map(tag => 
        `<span class="tag-badge">${escapeHtml(tag)}</span>`
    ).join('');
    
    return `
        <div class="applicable-rule-card" data-rule-id="${escapeHtml(rule.rule_id)}">
            <div class="rule-header">
                <span class="rule-language">${escapeHtml(rule.language)}</span>
                <span class="rule-tags">${tagsHtml}</span>
            </div>
            <div class="rule-body">
                <div class="rule-suggestion">
                    <svg class="icon"><use href="#icon-zap"></use></svg>
                    建议上下文级别: <strong>${escapeHtml(rule.suggested_context_level)}</strong>
                </div>
                <div class="rule-stats">
                    <span title="样本数量">${rule.sample_count} 次</span>
                    <span title="一致性">${Math.round(rule.consistency * 100)}% 一致</span>
                    <span title="不同文件数">${rule.unique_files} 文件</span>
                </div>
            </div>
            <div class="rule-warning">
                <svg class="icon"><use href="#icon-alert-triangle"></use></svg>
                <span>此规则将全局生效，影响所有匹配的代码变更</span>
            </div>
            <div class="rule-actions">
                <button class="btn-primary btn-small" onclick="applyRule('${escapeHtml(rule.rule_id)}')">
                    <svg class="icon"><use href="#icon-check"></use></svg>
                    确认并应用
                </button>
            </div>
        </div>
    `;
}

/**
 * 渲染参考提示卡片（重构版）
 * 
 * **Feature: rule-growth-layout-optimization**
 * **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
 */
function renderReferenceHint(hint) {
    const tagsHtml = hint.tags.map(tag => 
        `<span class="tag-badge tag-muted">${escapeHtml(tag)}</span>`
    ).join('');

    // 安全序列化 hint，避免内联 JSON 破坏 onclick
    const hintEncoded = encodeURIComponent(JSON.stringify(hint));
    
    const consistencyPercent = Math.round(hint.consistency * 100);
    const hintId = `hint-${hint.language}-${hint.tags.join('-')}-${Date.now()}`;
    
    // 渲染冲突文件列表（使用 conflicts 数据，如果有的话）
    const conflictFilesHtml = renderConflictFilesBlock(hint);
    
    // 渲染决策对比（使用 conflicts 数据，如果有的话）
    const decisionCompareHtml = renderDecisionCompareBlock(hint);
    
    // 渲染时间分布（使用 conflicts 数据，如果有的话）
    const timeDistributionHtml = renderTimeDistributionBlock(hint);
    
    // 渲染未满足条件（Requirements 4.1, 4.2, 4.3）
    const unmetConditionsHtml = renderUnmetConditionsBlock(hint);
    
    return `
        <div class="reference-hint-card" data-hint-id="${escapeHtml(hintId)}">
            <!-- 摘要头部 -->
            <div class="hint-summary">
                <div class="hint-summary-row">
                    <span class="hint-language-badge">${escapeHtml(hint.language)}</span>
                    <span class="hint-tags">${tagsHtml}</span>
                </div>
                <div class="hint-summary-row">
                    <span class="hint-suggestion-text">
                        <svg class="icon icon-small"><use href="#icon-zap"></use></svg>
                        建议: ${escapeHtml(hint.suggested_context_level)}
                    </span>
                </div>
                <div class="hint-summary-row hint-metrics">
                    <span class="hint-metric">
                        <span class="metric-value">${hint.sample_count}</span> 次出现
                    </span>
                    <span class="hint-metric">
                        <span class="metric-value">${consistencyPercent}%</span> 一致性
                    </span>
                    <span class="hint-metric">
                        <span class="metric-value">${hint.unique_files || 0}</span> 文件
                    </span>
                </div>
            </div>
            
            <!-- 可折叠信息块 -->
            <div class="hint-info-blocks">
                ${conflictFilesHtml}
                ${decisionCompareHtml}
                ${timeDistributionHtml}
                ${unmetConditionsHtml}
            </div>
            
            <!-- 不可应用原因 -->
            <div class="hint-reason-section">
                <svg class="icon icon-small"><use href="#icon-alert-triangle"></use></svg>
                <span class="reason-text">${escapeHtml(hint.reason)}</span>
            </div>
            
            <!-- 手动提升按钮 (Requirements 5.1) -->
            <div class="hint-actions">
                <button class="btn-secondary btn-small hint-promote-btn" onclick="showPromoteHintDialog('${escapeHtml(hintId)}', decodeURIComponent('${hintEncoded}'))" title="手动提升为规则">
                    <svg class="icon"><use href="#icon-trending-up"></use></svg>
                    提升为规则
                </button>
            </div>
        </div>
    `;
}

/**
 * 渲染冲突文件信息块
 * 
 * **Feature: rule-growth-layout-optimization, Property 2: 冲突文件完整展示**
 * **Validates: Requirements 2.2, 3.1**
 */
function renderConflictFilesBlock(hint) {
    const conflicts = hint.conflicts || [];
    const fileCount = conflicts.length || hint.unique_files || 0;
    
    let contentHtml = '';
    if (conflicts.length > 0) {
        // 按目录分组文件
        const groupedFiles = groupFilesByDirectory(conflicts);
        contentHtml = renderGroupedFileList(groupedFiles);
    } else {
        contentHtml = `<div class="block-empty-state">
            <span class="text-muted">共 ${fileCount} 个文件涉及此模式</span>
        </div>`;
    }
    
    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-folder"></use></svg>
                <span class="block-title">冲突文件</span>
                <span class="block-badge">${fileCount}</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
}

/**
 * 渲染决策对比信息块
 * 
 * **Feature: rule-growth-layout-optimization, Property 3: 决策对比正确性**
 * **Validates: Requirements 2.3**
 */
function renderDecisionCompareBlock(hint) {
    const conflicts = hint.conflicts || [];
    
    let contentHtml = '';
    if (conflicts.length > 0) {
        // 统计决策分布
        const decisionStats = calculateDecisionStats(conflicts);
        contentHtml = renderDecisionStats(decisionStats);
    } else {
        // 使用 hint 级别的数据
        contentHtml = `
            <div class="decision-compare-summary">
                <div class="decision-item">
                    <span class="decision-label">建议上下文级别:</span>
                    <span class="decision-value">${escapeHtml(hint.suggested_context_level)}</span>
                </div>
                <div class="decision-item">
                    <span class="decision-label">一致性:</span>
                    <span class="decision-value">${Math.round(hint.consistency * 100)}%</span>
                </div>
                <div class="decision-item">
                    <span class="decision-label">冲突类型:</span>
                    <span class="decision-value">${escapeHtml(getRuleGrowthTypeLabel(hint.conflict_type))}</span>
                </div>
            </div>
        `;
    }
    
    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-git-compare"></use></svg>
                <span class="block-title">决策对比</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
}

/**
 * 渲染时间分布信息块
 * 
 * **Feature: rule-growth-layout-optimization, Property 4: 时间分布完整性**
 * **Validates: Requirements 2.4**
 */
function renderTimeDistributionBlock(hint) {
    const conflicts = hint.conflicts || [];
    
    let contentHtml = '';
    if (conflicts.length > 0) {
        // 渲染时间分布
        const timeStats = calculateTimeDistribution(conflicts);
        contentHtml = renderTimeStats(timeStats);
    } else {
        contentHtml = `<div class="block-empty-state">
            <span class="text-muted">详细时间分布需要加载完整冲突数据</span>
        </div>`;
    }
    
    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-clock"></use></svg>
                <span class="block-title">时间分布</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
}

/**
 * 切换可折叠信息块的展开/折叠状态
 * 
 * **Feature: rule-growth-layout-optimization**
 * **Validates: Requirements 2.5**
 */
function toggleInfoBlock(blockEl) {
    if (blockEl) {
        blockEl.classList.toggle('collapsed');
    }
}

/**
 * 按目录分组文件
 * 
 * **Feature: rule-growth-layout-optimization, Property 5: 文件分组正确性**
 * **Validates: Requirements 3.2**
 */
function groupFilesByDirectory(conflicts) {
    const groups = {};
    
    for (const conflict of conflicts) {
        // 跳过已提升为规则的冲突
        if (conflict.promoted) {
            continue;
        }
        
        const filePath = conflict.file_path || conflict.filePath || '';
        const lastSlash = filePath.lastIndexOf('/');
        const directory = lastSlash > 0 ? filePath.substring(0, lastSlash) : '(root)';
        const fileName = lastSlash > 0 ? filePath.substring(lastSlash + 1) : filePath;
        
        if (!groups[directory]) {
            groups[directory] = [];
        }
        
        groups[directory].push({
            fileName,
            filePath,
            conflictType: conflict.conflict_type || conflict.conflictType || '',
            timestamp: conflict.timestamp || '',
            language: conflict.language || 'unknown',
            llmContext: conflict.llm_context_level || conflict.llmContextLevel || '',
            ruleContext: conflict.rule_context_level || conflict.ruleContextLevel || '',
            ruleConfidence: conflict.rule_confidence ?? conflict.ruleConfidence,
            llmReason: conflict.llm_reason || conflict.llmReason || '',
            ruleNotes: conflict.rule_notes || conflict.ruleNotes || '',
            metrics: conflict.metrics || {},
            tags: conflict.tags || []
        });
    }
    
    return groups;
}

/**
 * 按语言分组参考提示
 * 
 * **Feature: rule-growth-layout-optimization, Property 10: 语言分组正确性**
 * **Validates: Requirements 6.1**
 * 
 * 对于任意参考提示集合，按语言分组后，每个提示应出现在正确的语言分组中。
 */
function groupHintsByLanguage(hints) {
    const groups = {};
    
    for (const hint of hints) {
        const language = hint.language || 'unknown';
        
        if (!groups[language]) {
            groups[language] = {
                count: 0,
                hints: [],
                expanded: false
            };
        }
        
        groups[language].hints.push(hint);
        groups[language].count++;
    }
    
    return groups;
}

/**
 * 渲染按语言分组的参考提示列表
 * 
 * **Feature: rule-growth-layout-optimization, Property 11: 语言分组展开完整性**
 * **Validates: Requirements 6.2, 6.3**
 * 
 * 渲染可折叠的语言分组，显示数量徽章。
 * 展开后应显示该语言的所有参考提示。
 */
function renderGroupedHintsByLanguage(hints) {
    if (!hints || hints.length === 0) {
        return '<div class="empty-state"><span class="text-muted">暂无参考提示</span></div>';
    }
    
    const groupedHints = groupHintsByLanguage(hints);
    const languages = Object.keys(groupedHints).sort();
    
    let html = '<div class="language-grouped-hints">';
    
    for (const language of languages) {
        const group = groupedHints[language];
        const languageId = `lang-group-${language.replace(/[^a-zA-Z0-9]/g, '-')}`;
        
        html += `
            <div class="language-group collapsed" data-language="${escapeHtml(language)}" id="${languageId}">
                <div class="language-group-header" onclick="toggleLanguageGroup('${languageId}')">
                    <svg class="icon language-chevron"><use href="#icon-chevron-down"></use></svg>
                    <span class="language-name">${escapeHtml(language)}</span>
                    <span class="language-count-badge">${group.count}</span>
                </div>
                <div class="language-group-content">
                    ${group.hints.map(hint => renderReferenceHint(hint)).join('')}
                </div>
            </div>
        `;
    }
    
    html += '</div>';
    return html;
}

/**
 * 切换语言分组的展开/折叠状态
 * 
 * **Feature: rule-growth-layout-optimization**
 * **Validates: Requirements 6.2**
 */
function toggleLanguageGroup(groupId) {
    const groupEl = document.getElementById(groupId);
    if (groupEl) {
        groupEl.classList.toggle('collapsed');
    }
}

/**
 * 渲染分组后的文件列表
 * 
 * **Feature: rule-growth-layout-optimization, Property 6: 冲突文件信息完整性**
 * **Validates: Requirements 3.4**
 * 
 * 每个冲突文件条目应包含：文件路径、冲突类型、时间戳
 */
function renderGroupedFileList(groupedFiles) {
    const directories = Object.keys(groupedFiles).sort();
    
    if (directories.length === 0) {
        return '<div class="block-empty-state"><span class="text-muted">无文件数据</span></div>';
    }
    
    let html = '<div class="grouped-file-list">';
    
    for (const dir of directories) {
        const files = groupedFiles[dir];
        html += `
            <div class="file-group">
                <div class="file-group-header">
                    <svg class="icon icon-small"><use href="#icon-folder"></use></svg>
                    <span class="file-group-name">${escapeHtml(dir)}</span>
                    <span class="file-group-count">${files.length}</span>
                </div>
                <div class="file-group-items">
                    ${files.map(f => `
                        <div class="file-item">
                            <div class="file-head">
                                <span class="file-name" title="${escapeHtml(f.filePath)}">${escapeHtml(f.fileName)}</span>
                                ${f.conflictType ? `<span class="file-conflict-type">${escapeHtml(getConflictTypeLabel(f.conflictType))}</span>` : ''}
                                ${f.language ? `<span class="file-lang-badge">${escapeHtml(formatLanguageLabel(f.language))}</span>` : ''}
                            </div>
                            <div class="file-meta-row">
                                ${f.llmContext ? `<span class="tag-badge tag-muted">LLM: ${escapeHtml(f.llmContext)}</span>` : ''}
                                ${f.ruleContext ? `<span class="tag-badge">规则: ${escapeHtml(f.ruleContext)}</span>` : ''}
                                ${f.ruleConfidence !== undefined && f.ruleConfidence !== null ? `<span class="tag-badge tag-muted">置信 ${Math.round(f.ruleConfidence * 100)}%</span>` : ''}
                                ${f.timestamp ? `<span class="file-time">${formatTimestamp(f.timestamp)}</span>` : ''}
                            </div>
                            ${f.metrics && (f.metrics.added_lines || f.metrics.removed_lines || f.metrics.hunk_count) ? `
                                <div class="file-metrics">+${f.metrics.added_lines || 0} / -${f.metrics.removed_lines || 0} · 块 ${f.metrics.hunk_count || 0}</div>
                            ` : ''}
                            ${f.llmReason ? `<div class="file-reason" title="${escapeHtml(f.llmReason)}">${escapeHtml(truncateTextGlobal(f.llmReason, 120))}</div>` : ''}
                            ${f.ruleNotes ? `<div class="file-notes" title="${escapeHtml(f.ruleNotes)}">规则提示: ${escapeHtml(truncateTextGlobal(f.ruleNotes, 120))}</div>` : ''}
                            ${f.tags && f.tags.length ? `<div class="file-tags">${f.tags.slice(0, 4).map(t => `<span class="tag-badge tag-muted">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }
    
    html += '</div>';
    return html;
}

/**
 * 获取冲突类型的显示标签
 * 
 * **Feature: rule-growth-layout-optimization**
 * **Validates: Requirements 3.4**
 */
function getConflictTypeLabel(conflictType) {
    const labels = {
        'rule_high_llm_expand': '规则高/LLM扩展',
        'rule_high_llm_skip': '规则高/LLM跳过',
        'rule_low_llm_consistent': '规则低/LLM一致',
        'context_level_mismatch': '上下文级别不匹配'
    };
    return labels[conflictType] || conflictType || '';
}

/**
 * 计算决策统计
 */
function calculateDecisionStats(conflicts) {
    const llmDecisions = {};
    const ruleDecisions = {};
    
    for (const conflict of conflicts) {
        const llmLevel = conflict.llm_context_level || conflict.llmContextLevel || 'unknown';
        const ruleLevel = conflict.rule_context_level || conflict.ruleContextLevel || 'unknown';
        
        llmDecisions[llmLevel] = (llmDecisions[llmLevel] || 0) + 1;
        ruleDecisions[ruleLevel] = (ruleDecisions[ruleLevel] || 0) + 1;
    }
    
    return { llmDecisions, ruleDecisions, total: conflicts.length };
}

/**
 * 渲染决策统计
 */
function renderDecisionStats(stats) {
    let html = '<div class="decision-stats">';
    
    // LLM 决策分布
    html += '<div class="decision-section"><h5>LLM 决策分布</h5><div class="decision-bars">';
    for (const [level, count] of Object.entries(stats.llmDecisions)) {
        const percent = Math.round((count / stats.total) * 100);
        html += `
            <div class="decision-bar-item">
                <span class="bar-label">${escapeHtml(level)}</span>
                <div class="bar-container">
                    <div class="bar-fill" style="width: ${percent}%"></div>
                </div>
                <span class="bar-value">${count} (${percent}%)</span>
            </div>
        `;
    }
    html += '</div></div>';
    
    // 规则决策分布
    html += '<div class="decision-section"><h5>规则决策分布</h5><div class="decision-bars">';
    for (const [level, count] of Object.entries(stats.ruleDecisions)) {
        const percent = Math.round((count / stats.total) * 100);
        html += `
            <div class="decision-bar-item">
                <span class="bar-label">${escapeHtml(level)}</span>
                <div class="bar-container">
                    <div class="bar-fill bar-fill-rule" style="width: ${percent}%"></div>
                </div>
                <span class="bar-value">${count} (${percent}%)</span>
            </div>
        `;
    }
    html += '</div></div>';
    
    html += '</div>';
    return html;
}

/**
 * 计算时间分布
 */
function calculateTimeDistribution(conflicts) {
    const timestamps = conflicts
        .map(c => c.timestamp)
        .filter(t => t)
        .sort();
    
    if (timestamps.length === 0) {
        return { timestamps: [], earliest: null, latest: null };
    }
    
    return {
        timestamps,
        earliest: timestamps[0],
        latest: timestamps[timestamps.length - 1],
        count: timestamps.length
    };
}

/**
 * 渲染时间统计
 */
function renderTimeStats(stats) {
    if (!stats.earliest) {
        return '<div class="block-empty-state"><span class="text-muted">无时间数据</span></div>';
    }
    
    return `
        <div class="time-stats">
            <div class="time-stat-item">
                <span class="time-label">最早记录:</span>
                <span class="time-value">${formatTimestamp(stats.earliest)}</span>
            </div>
            <div class="time-stat-item">
                <span class="time-label">最近记录:</span>
                <span class="time-value">${formatTimestamp(stats.latest)}</span>
            </div>
            <div class="time-stat-item">
                <span class="time-label">记录总数:</span>
                <span class="time-value">${stats.count}</span>
            </div>
        </div>
    `;
}

/**
 * 格式化时间戳
 */
function formatTimestamp(timestamp) {
    if (!timestamp) return '';
    try {
        const date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return timestamp;
    }
}

/**
 * 应用规则
 */
async function applyRule(ruleId) {
    if (!confirm('确定要应用此规则吗？此操作将影响全局规则配置。')) {
        return;
    }
    
    try {
        const res = await fetch('/api/rule-growth/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rule_id: ruleId })
        });
        
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        
        const data = await res.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        showToast('规则已成功应用', 'success');
        
        // 刷新数据
        await loadRuleGrowthData();
        
    } catch (e) {
        console.error('Apply rule error:', e);
        showToast('应用规则失败: ' + e.message, 'error');
    }
}

/**
 * 清理旧的冲突记录
 */
async function ruleGrowthCleanup() {
    if (!confirm('确定要清理 30 天前的冲突记录吗？')) {
        return;
    }
    
    try {
        const res = await fetch('/api/rule-growth/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_age_days: 30 })
        });
        
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        
        const data = await res.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        const deleted = data.deleted_count || 0;
        const remaining = data.remaining_count || 0;
        
        showToast(`已清理 ${deleted} 条记录，剩余 ${remaining} 条`, 'success');
        
        // 刷新数据
        await loadRuleGrowthData();
        
    } catch (e) {
        console.error('Rule growth cleanup error:', e);
        showToast('清理失败: ' + e.message, 'error');
    }
}

/**
 * 获取冲突类型的中文标签
 */
function getRuleGrowthTypeLabel(type) {
    const labels = {
        'rule_high_llm_expand': 'LLM 要求更多上下文',
        'rule_high_llm_skip': 'LLM 建议跳过',
        'rule_low_llm_consistent': '可提取新规则',
        'context_level_mismatch': '上下文级别不匹配'
    };
    return labels[type] || type;
}

/**
 * 获取建议类型的中文标签
 */
function getSuggestionTypeLabel(type) {
    const labels = {
        'upgrade_context_level': '提升上下文级别',
        'add_noise_detection': '添加噪音检测',
        'new_rule': '新增规则'
    };
    return labels[type] || type;
}

/**
 * 获取建议类型的徽章样式类
 */
function getSuggestionTypeBadgeClass(type) {
    const classes = {
        'upgrade_context_level': 'warning',
        'add_noise_detection': 'info',
        'new_rule': 'success'
    };
    return classes[type] || '';
}

/**
 * 格式化未满足条件为"当前值/要求值"格式
 * 
 * **Feature: rule-growth-layout-optimization, Property 7: 未满足条件指标格式**
 * **Validates: Requirements 4.1**
 * 
 * @param {Object} condition - 未满足条件对象
 * @param {string} condition.name - 条件名称
 * @param {number} condition.currentValue - 当前值
 * @param {number} condition.requiredValue - 要求值
 * @returns {string} 格式化后的字符串，如 "3/5 次出现" 或 "67%/90% 一致性"
 */
function formatUnmetCondition(condition) {
    const name = condition.name || '';
    const current = condition.currentValue;
    const required = condition.requiredValue;
    
    // 根据条件名称确定单位和格式
    if (name.includes('一致性') || name.includes('consistency') || name.includes('percent')) {
        // 百分比格式
        const currentPercent = typeof current === 'number' ? Math.round(current * 100) : current;
        const requiredPercent = typeof required === 'number' ? Math.round(required * 100) : required;
        return `${currentPercent}%/${requiredPercent}%`;
    } else if (name.includes('次') || name.includes('count') || name.includes('出现')) {
        // 次数格式
        return `${current}/${required} 次`;
    } else {
        // 默认格式
        return `${current}/${required}`;
    }
}

/**
 * 计算未满足条件的严重程度
 * 
 * **Feature: rule-growth-layout-optimization, Property 7: 未满足条件指标格式**
 * **Validates: Requirements 4.3**
 * 
 * @param {Object} condition - 未满足条件对象
 * @param {number} condition.currentValue - 当前值
 * @param {number} condition.requiredValue - 要求值
 * @returns {string} 'far' (红色) 或 'close' (黄色)
 */
function calculateConditionSeverity(condition) {
    const current = condition.currentValue;
    const required = condition.requiredValue;
    
    if (typeof current !== 'number' || typeof required !== 'number' || required === 0) {
        return 'far';
    }
    
    // 计算完成度百分比
    const completionRatio = current / required;
    
    // 如果完成度 >= 70%，认为接近阈值（黄色）
    // 如果完成度 < 70%，认为距离较远（红色）
    return completionRatio >= 0.7 ? 'close' : 'far';
}

/**
 * 渲染未满足条件信息块
 * 
 * **Feature: rule-growth-layout-optimization, Property 8: 多条件完整列出**
 * **Validates: Requirements 4.1, 4.2, 4.3**
 * 
 * @param {Object} hint - 参考提示对象
 * @param {Array} hint.unmetConditions - 未满足条件列表
 * @returns {string} HTML 字符串
 */
function renderUnmetConditionsBlock(hint) {
    const unmetConditions = hint.unmetConditions || hint.unmet_conditions || [];
    
    if (unmetConditions.length === 0) {
        return '';
    }
    
    const conditionsHtml = unmetConditions.map(condition => {
        const severity = calculateConditionSeverity(condition);
        const formattedValue = formatUnmetCondition(condition);
        const conditionName = condition.name || condition.condition_name || '未知条件';
        
        return `
            <div class="unmet-condition-item severity-${severity}">
                <span class="condition-name">${escapeHtml(conditionName)}</span>
                <span class="condition-values">${escapeHtml(formattedValue)}</span>
            </div>
        `;
    }).join('');
    
    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-alert-circle"></use></svg>
                <span class="block-title">未满足条件</span>
                <span class="block-badge severity-indicator">${unmetConditions.length}</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    <div class="unmet-conditions-list">
                        ${conditionsHtml}
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * 显示提升参考提示为规则的确认对话框
 * 
 * **Feature: rule-growth-layout-optimization**
 * **Validates: Requirements 5.1, 5.2**
 * 
 * @param {string} hintId - 提示 ID
 * @param {Object|string} hintData - 提示数据对象或 JSON 字符串
 */
function showPromoteHintDialog(hintId, hintData) {
    // 解析 hintData（可能是字符串或对象）
    let hint;
    try {
        hint = typeof hintData === 'string' ? JSON.parse(hintData) : hintData;
    } catch (e) {
        console.error('Failed to parse hint data:', e);
        showToast('无法解析提示数据', 'error');
        return;
    }
    
    // 构建规则详情 HTML
    const tagsHtml = (hint.tags || []).map(tag => 
        `<span class="tag-badge">${escapeHtml(tag)}</span>`
    ).join(' ');
    
    const consistencyPercent = Math.round((hint.consistency || 0) * 100);
    
    const dialogContent = `
        <div class="promote-hint-dialog">
            <div class="dialog-section">
                <h4>规则详情</h4>
                <div class="rule-detail-grid">
                    <div class="detail-row">
                        <span class="detail-label">语言:</span>
                        <span class="detail-value">${escapeHtml(hint.language || '')}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">标签:</span>
                        <span class="detail-value">${tagsHtml || '无'}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">建议上下文级别:</span>
                        <span class="detail-value">${escapeHtml(hint.suggested_context_level || hint.suggestedContextLevel || '')}</span>
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
                    <div class="reason-detail">${escapeHtml(hint.reason || '')}</div>
                </div>
            </div>
        </div>
    `;
    
    // 显示确认对话框
    showConfirmDialog({
        title: '提升为规则',
        content: dialogContent,
        confirmText: '确认提升',
        cancelText: '取消',
        onConfirm: () => promoteHintToRule(hint)
    });
}

/**
 * 显示确认对话框
 * 
 * @param {Object} options - 对话框选项
 * @param {string} options.title - 标题
 * @param {string} options.content - 内容 HTML
 * @param {string} options.confirmText - 确认按钮文本
 * @param {string} options.cancelText - 取消按钮文本
 * @param {Function} options.onConfirm - 确认回调
 * @param {Function} options.onCancel - 取消回调
 */
function showConfirmDialog(options) {
    // 移除已存在的对话框
    const existingDialog = document.getElementById('confirmDialog');
    if (existingDialog) {
        existingDialog.remove();
    }
    
    const dialog = document.createElement('div');
    dialog.id = 'confirmDialog';
    dialog.className = 'modal-overlay';
    dialog.innerHTML = `
        <div class="modal-container confirm-dialog-container">
            <div class="modal-header">
                <h3>${escapeHtml(options.title || '确认')}</h3>
                <button class="icon-btn modal-close-btn" onclick="closeConfirmDialog()">
                    <svg class="icon"><use href="#icon-x"></use></svg>
                </button>
            </div>
            <div class="modal-body">
                ${options.content || ''}
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeConfirmDialog()">${escapeHtml(options.cancelText || '取消')}</button>
                <button class="btn-primary" id="confirmDialogBtn">${escapeHtml(options.confirmText || '确认')}</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(dialog);
    
    // 绑定确认按钮事件
    const confirmBtn = document.getElementById('confirmDialogBtn');
    if (confirmBtn && options.onConfirm) {
        confirmBtn.onclick = () => {
            closeConfirmDialog();
            options.onConfirm();
        };
    }
    
    // 点击遮罩关闭
    dialog.onclick = (e) => {
        if (e.target === dialog) {
            closeConfirmDialog();
            if (options.onCancel) options.onCancel();
        }
    };
}

/**
 * 关闭确认对话框
 */
function closeConfirmDialog() {
    const dialog = document.getElementById('confirmDialog');
    if (dialog) {
        dialog.remove();
    }
}

/**
 * 将参考提示提升为规则
 * 
 * **Feature: rule-growth-layout-optimization**
 * **Validates: Requirements 5.3, 5.4**
 * 
 * @param {Object} hint - 参考提示数据
 */
async function promoteHintToRule(hint) {
    try {
        // 提交过程禁用按钮以避免重复点击
        const promoteBtn = document.querySelector('.hint-promote-btn.loading') || document.querySelector('.hint-promote-btn:focus');
        if (promoteBtn) promoteBtn.classList.add('loading');

        // 兜底获取语言和标签，避免写入 unknown 组
        const fallbackConflict = (hint.conflicts && hint.conflicts[0]) || null;
        const language = hint.language || (fallbackConflict && fallbackConflict.language) || 'unknown';
        const tags = Array.isArray(hint.tags) ? hint.tags : (fallbackConflict && fallbackConflict.tags) || [];

        // 调用后端 API 提升提示为规则
        const res = await fetch('/api/rule-growth/promote-hint', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                language,
                tags,
                suggested_context_level: hint.suggested_context_level || hint.suggestedContextLevel,
                sample_count: hint.sample_count || hint.sampleCount,
                consistency: hint.consistency,
                conflict_type: hint.conflict_type || hint.conflictType
            })
        });
        
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || errData.error || `HTTP ${res.status}`);
        }
        
        const data = await res.json();
        
        if (data.error) {
            throw new Error(data.error);
        }
        
        // 显示成功反馈 (Requirements 5.4)
        showToast('提示已成功提升为规则', 'success');
        
        // 刷新数据，从列表移除提示 (Requirements 5.4)
        await loadRuleGrowthData();
        
    } catch (e) {
        console.error('Promote hint error:', e);
        showToast('提升失败: ' + e.message, 'error');
    } finally {
        const promoteBtn = document.querySelector('.hint-promote-btn.loading');
        if (promoteBtn) promoteBtn.classList.remove('loading');
    }
}
