// --- Icons Helper ---
function getIcon(name) {
    return `<svg class="icon"><use href="#icon-${name}"></use></svg>`;
}

// --- Global State ---
let currentSessionId = null;
let currentProjectRoot = null;
let currentDiffMode = 'auto';
let currentModelValue = "auto";
let availableGroups = [];

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
    
    console.log(`Layout state changed: ${previousState} -> ${newState}`);
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
const newSessionBtn = document.getElementById('newSessionBtn');
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

// --- Initialization ---

async function init() {
    console.log("Initializing App...");
    try {
        // Bind global events
        bindEvents();
        
        // Initialize layout state to initial (single canvas)
        setLayoutState(LayoutState.INITIAL);
        
        // Initial loads (don't fail if these error)
        try {
            await loadOptions();
        } catch (e) {
            console.error("Failed to load options:", e);
        }
        
        try {
            await loadSessions();
        } catch (e) {
            console.error("Failed to load sessions:", e);
        }
        
        // Default page
        switchPage('review');
        
        // Start loop for health check
        setInterval(updateHealthStatus, 30000);
        console.log("App Initialized Successfully");
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
    if(newSessionBtn) newSessionBtn.onclick = startNewSession;
    
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
            const content = data.content || "";
            
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
            diffContentArea.innerHTML = `
                <div style="padding:1rem; border-bottom: 1px solid var(--border-color); display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="margin:0;">${escapeHtml(filePath)}</h3>
                    <div class="diff-controls">
                        <label><input type="radio" name="diff-view" value="line-by-line" onclick="toggleDiffView('line-by-line')"> Unified</label>
                        <label><input type="radio" name="diff-view" value="side-by-side" checked onclick="toggleDiffView('side-by-side')"> Split</label>
                    </div>
                </div>
                <div id="diff-ui-container" style="padding: 0;"></div>
            `;
            
            window.currentDiffText = diffText; // Store for toggling
            renderDiff2Html(diffText, 'side-by-side');
            
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
                    const project = escapeHtml(i.project || 'Unknown');
                    const timestamp = i.timestamp ? new Date(i.timestamp * 1000).toLocaleString() : '';
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
            currentProjectRoot = data.path;
            if (projectRootInput) projectRootInput.value = data.path;
            if (currentPathLabel) currentPathLabel.textContent = data.path;
            if (dashProjectPath) dashProjectPath.textContent = data.path;
            
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
    const logSummary = document.getElementById('logSummary');
    if (logSummary) {
        logSummary.classList.toggle('collapsed');
    }
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
async function triggerCompletionTransition(reportContent, score = null) {
    const steps = ['init', 'analysis', 'planning', 'reviewing', 'reporting'];
    
    // Step 1: Mark all nodes as completed in rapid sequence (Requirement 4.2)
    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        setProgressStep(step, 'completed');
        // Short delay between each step for visual effect (50ms each)
        await new Promise(resolve => setTimeout(resolve, 50));
    }
    
    // Step 2: Short pause before layout transition
    await new Promise(resolve => setTimeout(resolve, 200));
    
    // Step 3: Update report panel content before showing
    if (reportContainer && reportContent) {
        reportContainer.innerHTML = marked.parse(reportContent);
        
        // Add score display if provided (Requirement 4.6)
        if (score !== null) {
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
    }
    
    // Step 4: Transition to completed layout state (Requirement 4.3, 4.4, 4.5)
    // This triggers CSS transitions for:
    // - Right panel shrinking
    // - Report panel expanding to at least 65% width
    setLayoutState(LayoutState.COMPLETED);
    
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
        startReviewBtn.innerHTML = `<span class="spinner"></span> 正在审查...`;
    }

    // Trigger layout split animation - switch to reviewing state
    // This will expand the right panel with progress timeline
    setLayoutState(LayoutState.REVIEWING);
    
    // Reset and initialize progress steps
    resetProgress();
    setProgressStep('init', 'completed');
    setProgressStep('analysis', 'active');

    // Ensure session
    if (!currentSessionId) await startNewSession();

    const tools = Array.from(document.querySelectorAll('#toolListContainer input:checked')).map(cb => cb.value);
    const autoApprove = autoApproveInput ? autoApproveInput.checked : false;
    
    try {
        const response = await fetch("/api/review/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                project_root: currentProjectRoot,
                model: currentModelValue,
                tools: tools,
                autoApprove: autoApprove
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        await handleSSEResponse(response);

    } catch (e) {
        console.error("Start review error:", e);
        addSystemMessage("启动审查失败: " + escapeHtml(e.message));
        
        // Reset layout state on error
        setLayoutState(LayoutState.INITIAL);
        
        if (startReviewBtn) {
            startReviewBtn.disabled = false;
            startReviewBtn.innerHTML = `${getIcon('send')} <span>开始代码审查</span>`;
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
    if (!currentSessionId) await startNewSession();

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
        
        await handleSSEResponse(response);

    } catch (e) {
        console.error("Send message error:", e);
        addMessage("system", `<p>发送失败: ${escapeHtml(e.message)}</p>`);
    }
}

async function handleSSEResponse(response) {
    if (!response.body) {
        console.error("Response body is null");
        return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // Create a placeholder for streaming response
    const msgId = "msg-" + Date.now();
    addMessage("assistant", '<span class="typing-indicator">Thinking...</span>', msgId);
    const msgEl = document.getElementById(msgId);
    const msgContentEl = msgEl ? msgEl.querySelector('.content') : null;
    let fullContent = "";
    let fullThought = ""; // 累积思考内容
    let streamEnded = false;

    const processEvent = (evt) => {
        if (!msgEl || !msgContentEl) return;
        
        // Ensure process log exists if needed
        let processLog = msgEl.querySelector('.process-log');
        if (!processLog && (evt.type === 'thought' || evt.type === 'tool_start')) {
            processLog = document.createElement('div');
            processLog.className = 'process-log active';
            
            const msgBody = msgEl.querySelector('.message-body');
            if (msgBody) {
                msgBody.prepend(processLog);
            } else {
                // Fallback for old messages or if structure is different
                const avatar = msgEl.querySelector('.avatar');
                if (avatar) {
                    avatar.after(processLog);
                } else {
                    msgEl.prepend(processLog);
                }
            }
        }

        if (evt.type === "thought") {
            // Update Progress: Thought implies Planning or Reviewing logic
            setProgressStep('analysis', 'completed');
            setProgressStep('planning', 'active');

            // 累积思考内容，而不是每次创建新元素
            fullThought += evt.content || "";
            
            // 查找或创建思考内容容器
            let thoughtItem = processLog.querySelector('.thought-stream');
            if (!thoughtItem) {
                thoughtItem = document.createElement('div');
                thoughtItem.className = 'process-item thought thought-stream';
                thoughtItem.innerHTML = `<div class="process-item-content"></div>`;
                processLog.appendChild(thoughtItem);
            }
            
            // 更新思考内容
            const contentEl = thoughtItem.querySelector('.process-item-content');
            if (contentEl) {
                contentEl.textContent = fullThought;
            }
            processLog.scrollTop = processLog.scrollHeight;
            
            // Clear initial typing indicator if present
            if (msgContentEl.innerHTML.includes('typing-indicator')) {
                msgContentEl.innerHTML = '';
            }

        } else if (evt.type === "tool_start") {
            // Update Progress: Tool calls are part of planning/analysis
            setProgressStep('planning', 'active');

            const item = document.createElement('div');
            item.className = 'process-item tool';
            item.innerHTML = `${getIcon('settings')} <div class="process-item-content">Call: ${escapeHtml(evt.tool)}</div>`;
            processLog.appendChild(item);
            processLog.scrollTop = processLog.scrollHeight;

        } else if (evt.type === "chunk") {
            // Update Progress: Content generation means reviewing
            setProgressStep('planning', 'completed');
            setProgressStep('reviewing', 'active');

            if (fullContent === "" && msgContentEl.innerHTML.includes('typing-indicator')) {
                msgContentEl.innerHTML = "";
            }
            fullContent += evt.content || "";
            msgContentEl.innerHTML = marked.parse(fullContent);
            
        } else if (evt.type === "final") {
            // Update Progress: Review done, start reporting phase
            setProgressStep('reviewing', 'completed');
            setProgressStep('reporting', 'active');

            if (evt.content && evt.content !== fullContent) {
                fullContent = evt.content;
                msgContentEl.innerHTML = marked.parse(evt.content);
            }
            
            // Extract score from content if present (look for patterns like "评分: 85/100" or "Score: 85")
            const finalContent = evt.content || fullContent;
            let score = null;
            const scoreMatch = finalContent.match(/(?:评分|Score|分数)[:\s]*(\d+)/i);
            if (scoreMatch) {
                score = parseInt(scoreMatch[1], 10);
            }
            
            // Check if this looks like a review report
            const isReport = finalContent.includes("# Code Review Report") || 
                            finalContent.includes("# 代码审查报告") ||
                            finalContent.includes("## 审查结果") ||
                            finalContent.includes("## Summary");
            
            if (isReport) {
                // Trigger the completion transition animation sequence
                // Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
                setTimeout(() => {
                    triggerCompletionTransition(finalContent, score);
                }, 500);
            } else {
                // Not a report, just update the report container
                if (reportContainer) {
                    reportContainer.innerHTML = marked.parse(finalContent);
                }
                setProgressStep('reporting', 'completed');
            }
            
            streamEnded = true;
            
        } else if (evt.type === "error") {
            fullContent += `\n\n**Error:** ${evt.message}`;
            msgContentEl.innerHTML = marked.parse(fullContent);
            streamEnded = true;
            
        } else if (evt.type === "done") {
            streamEnded = true;
            // 审查完成后刷新历史记录列表
            loadSessions();
        }
    };

    try {
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
                        processEvent(evt);
                        if (streamEnded) break;
                    } catch (e) {
                        console.error("SSE Parse Error", e, line);
                    }
                }
            }
            if (streamEnded) break;
        }
        
        // Process remaining buffer
        if (buffer && buffer.startsWith("data: ")) {
            try {
                const evt = JSON.parse(buffer.slice(6));
                processEvent(evt);
            } catch (e) {
                // Ignore incomplete data
            }
        }
    } catch (e) {
        console.error("SSE Stream Error", e);
        if (msgContentEl) {
            fullContent += `\n\n**Stream Error:** ${e.message}`;
            msgContentEl.innerHTML = marked.parse(fullContent);
        }
    }
    
    if (startReviewBtn) {
        startReviewBtn.disabled = false;
        startReviewBtn.innerHTML = `${getIcon('send')} <span>开始代码审查</span>`;
    }
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

function toggleReportView(show) {
    if (!workbenchEl) return;
    if (show) {
        workbenchEl.classList.add("split-view");
    } else {
        workbenchEl.classList.remove("split-view");
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
        
        if(sessionListEl) {
            sessionListEl.innerHTML = "";
            if (sessions.length === 0) {
                sessionListEl.innerHTML = '<div class="empty-state" style="padding:1rem;font-size:0.85rem;">暂无历史会话</div>';
                return;
            }
            
            sessions.forEach(s => {
                const div = document.createElement("div");
                const isActive = s.session_id === currentSessionId;
                div.className = `session-item ${isActive ? 'active' : ''}`;
                div.dataset.sessionId = s.session_id; // 添加 data 属性便于查找
                
                // 格式化日期显示
                const dateStr = s.updated_at ? new Date(s.updated_at).toLocaleString('zh-CN', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                }) : '';
                
                // 生成显示名称：优先使用 name，否则使用简化的 session_id
                const displayName = s.name || (s.session_id ? s.session_id.replace('sess_', '会话 ') : '未命名会话');
                
                div.innerHTML = `
                    <div class="session-icon">${getIcon('clock')}</div>
                    <div class="session-info">
                        <span class="session-title" title="${escapeHtml(s.name || s.session_id)}">${escapeHtml(displayName)}</span>
                        <span class="session-date">${dateStr}</span>
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
        }
    } catch (e) { 
        console.error("Load sessions error:", e); 
        if(sessionListEl) sessionListEl.innerHTML = `<div style="padding:1rem;color:red;">加载失败</div>`;
    }
}

async function loadSession(sid) {
    currentSessionId = sid;
    
    // 使用 data 属性更新选中状态
    updateSessionActiveState(sid);

    try {
        const res = await fetch(`/api/sessions/${sid}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        
        messageContainer.innerHTML = "";
        
        // Replay messages
        // Check structure: data.conversation.messages OR data.messages (depending on API response)
        // SessionAPI.get_session returns session.to_dict()
        // ReviewSession.to_dict() structure: { "conversation": { "messages": [...] }, "metadata": ... }
        
        const messages = (data.conversation && data.conversation.messages) ? data.conversation.messages : (data.messages || []);
        
        if (messages.length > 0) {
            messages.forEach(msg => {
                addMessage(msg.role, marked.parse(msg.content || ""));
            });
        } else {
            // Empty session
            messageContainer.innerHTML = `
                <div class="empty-state">
                    <div style="text-align:center;color:var(--text-muted);">
                        <div style="margin-bottom:1rem;">${getIcon('bot')}</div>
                        <p>这是一个新会话。准备好审查您的代码。</p>
                    </div>
                </div>
            `;
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
        
        // 移动端自动关闭抽屉
        if (window.innerWidth < 768 && historyDrawer) historyDrawer.classList.remove("open");
        
    } catch(e) { 
        console.error("Load session error:", e);
        addSystemMessage("加载会话失败: " + e.message);
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
            
            if (currentSessionId === sid) {
                currentSessionId = null;
                startNewSession();
            }
            loadSessions(); // Refresh list
        } catch (e) {
            showToast("删除失败: " + e.message, "error");
        }
    }
}

async function startNewSession() {
    currentSessionId = generateSessionId();
    
    // 清空消息容器，显示欢迎信息
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
    
    // 清除所有会话的选中状态
    updateSessionActiveState(null);
    
    // 切换到审查页面
    switchPage('review');
}

function generateSessionId() {
    return "sess_" + Date.now();
}

// --- Options Loader ---
async function loadOptions() {
    try {
        const res = await fetch("/api/options");
        if (!res.ok) {
            console.error("Failed to load options:", res.status);
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
    
    // Render Manage Models UI (if config page is active or just update internal state)
    // We will call this when opening the modal or config page
    renderManageModelsList();

    // Render Tools
        if(toolListContainer) {
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
        
    } catch (e) { console.error("Load options error:", e); }
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
        
        let modelsHtml = (g.models || []).map(m => `
            <div class="model-list-row">
                <span class="model-name">${escapeHtml(m.name)}</span>
                <button class="icon-btn-small delete-btn" onclick="deleteModel('${g.provider}', '${escapeHtml(m.name)}')">
                    ${getIcon('trash')}
                </button>
            </div>
        `).join('');
        
        groupDiv.innerHTML = `
            <div class="group-header"><strong>${escapeHtml(providerName)}</strong></div>
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
