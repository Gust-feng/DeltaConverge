/**
 * dashboard.js - 仪表盘页面模块
 */

async function updateHealthStatus() {
    const healthStatusBadge = document.getElementById('health-status-badge');
    try {
        const res = await fetch('/api/health/simple');
        if (!res.ok) {
            if (healthStatusBadge) {
                healthStatusBadge.textContent = 'Error';
                healthStatusBadge.className = 'badge error';
            }
            return;
        }
        const data = await res.json();
        if (healthStatusBadge) {
            healthStatusBadge.textContent = data.status === 'healthy' ? '正常' : '异常';
            healthStatusBadge.className = `badge ${data.status === 'healthy' ? 'success' : 'error'}`;
        }
    } catch (e) {
        if (healthStatusBadge) {
            healthStatusBadge.textContent = 'Error';
            healthStatusBadge.className = 'badge error';
        }
    }
}

const DASHBOARD_CACHE_TTL_MS = 60 * 1000;
const dashboardCache = new Map();

async function loadDashboardDataUncached() {
    const dashProjectPath = document.getElementById('dash-project-path');
    const dashDiffStatus = document.getElementById('dash-diff-status');
    const sessionStatsContent = document.getElementById('session-stats-content');
    const sessionTotalBadge = document.getElementById('session-total-badge');
    const providerStatusContent = document.getElementById('provider-status-content');
    const providerAvailableBadge = document.getElementById('provider-available-badge');

    updateHealthStatus();

    // Project Info
    if (window.currentProjectRoot) {
        if (dashProjectPath) dashProjectPath.textContent = window.currentProjectRoot;
        if (dashDiffStatus) dashDiffStatus.textContent = "Checking...";

        try {
            const res = await fetch(`/api/diff/status?project_root=${encodeURIComponent(window.currentProjectRoot)}`);
            if (res.ok) {
                const status = await res.json();
                if (dashDiffStatus) {
                    if (status.error) {
                        dashDiffStatus.textContent = `Error: ${status.error}`;
                    } else if (status.has_working_changes || status.has_staged_changes) {
                        dashDiffStatus.textContent = `Has Changes (${status.detected_mode || 'unknown'})`;
                    } else {
                        dashDiffStatus.textContent = "Clean (no changes)";
                    }
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
    if (typeof loadIntentData === 'function') loadIntentData();

    // Load Git History
    if (typeof GitHistory !== 'undefined' && window.currentProjectRoot) {
        try {
            if (!GitHistory.currentProjectRoot || GitHistory.currentProjectRoot !== window.currentProjectRoot) {
                GitHistory.init(window.currentProjectRoot);
            }
        } catch (_) { }
    }

    // Session Stats
    try {
        const res = await fetch('/api/sessions/stats');
        if (res.ok) {
            const stats = await res.json();
            if (sessionTotalBadge) sessionTotalBadge.textContent = String(stats.total_sessions || 0);
            if (sessionStatsContent) {
                const totalMsgs = stats.total_messages || 0;
                const byStatus = stats.by_status || {};
                const statusEntries = Object.entries(byStatus).sort((a, b) => b[1] - a[1]).slice(0, 3);
                const byProject = stats.by_project || {};
                const projectCount = Object.keys(byProject).length;
                let html = '';
                html += `<div class="stat-row"><span class="label">消息总数:</span><span class="value">${totalMsgs}</span></div>`;
                html += `<div class="stat-row"><span class="label">项目数:</span><span class="value">${projectCount}</span></div>`;
                statusEntries.forEach(([k, v]) => {
                    html += `<div class="stat-row"><span class="label">${k}:</span><span class="value">${v}</span></div>`;
                });
                sessionStatsContent.innerHTML = html;
            }
        }
    } catch (e) { }

    // Provider Status
    try {
        const res = await fetch('/api/providers/status');
        if (res.ok) {
            const providers = await res.json();
            const total = providers.length || 0;
            const avail = providers.filter(p => p.available).length;
            if (providerAvailableBadge) providerAvailableBadge.textContent = `${avail}/${total}`;
            if (providerStatusContent) {
                let html = '';
                providers.forEach(p => {
                    const dotClass = p.available ? 'success' : 'error';
                    const statusText = p.available ? '已配置' : '未配置';
                    const dot = `<span class="status-dot ${dotClass}" title="${escapeHtml(p.error || statusText)}"></span>`;
                    html += `<div class="stat-row"><span class="label">${p.label || p.name}:</span><span class="value" style="display:flex;align-items:center;gap:0.4rem">${dot}<span style="font-size:0.75rem;color:var(--text-muted)">${statusText}</span></span></div>`;
                });
                providerStatusContent.classList.add('compact-list');
                providerStatusContent.innerHTML = html;
            }
        }
    } catch (e) { }

    // Setup Provider Keys Modal
    setupProviderKeysModal();

    // Load Scanner Status
    await loadScannerStatus();
}

async function loadDashboardData(options = {}) {
    const force = !!(options && options.force);
    const key = window.currentProjectRoot || '__none__';
    const now = Date.now();

    const cached = dashboardCache.get(key);
    if (!force && cached && cached.promise && (now - cached.ts) < DASHBOARD_CACHE_TTL_MS) {
        return cached.promise;
    }

    const promise = (async () => {
        await loadDashboardDataUncached();
    })();

    dashboardCache.set(key, { ts: now, promise });

    try {
        await promise;
    } catch (e) {
        const latest = dashboardCache.get(key);
        if (latest && latest.promise === promise) {
            dashboardCache.delete(key);
        }
        throw e;
    }
}

let scannerViewMode = 'summary';
let detectedLanguages = [];

async function loadScannerStatus() {
    const scannerStatusContent = document.getElementById('scanner-status-content');
    const scannerSummaryBadge = document.getElementById('scanner-summary-badge');
    const scannerToggleBtn = document.getElementById('scanner-toggle-btn');

    try {
        // 检测项目语言
        if (window.currentProjectRoot) {
            const infoRes = await fetch(`/api/project/info?project_root=${encodeURIComponent(window.currentProjectRoot)}`);
            if (infoRes && infoRes.ok) {
                const pinfo = await infoRes.json();
                const names = Array.isArray(pinfo.detected_languages) ? pinfo.detected_languages : [];
                const map = {
                    'Python': 'python', 'TypeScript': 'typescript', 'JavaScript': 'javascript',
                    'Java': 'java', 'Go': 'go', 'Ruby': 'ruby', 'C': 'c', 'C++': 'cpp',
                    'C#': 'csharp', 'Rust': 'rust', 'Kotlin': 'kotlin', 'Swift': 'swift',
                    'PHP': 'php', 'Scala': 'scala'
                };
                detectedLanguages = names.map(n => map[n]).filter(Boolean);
            } else {
                detectedLanguages = [];
            }
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
                    used.forEach(l => {
                        const ratio = l.total_count > 0 ? (l.available_count / l.total_count) : 0;
                        const colorClass = ratio === 1 ? 'success' : (ratio > 0 ? 'warning' : 'error');
                        html += `
                        <div class="stat-row">
                            <span class="label" style="width:100px">${l.language}</span>
                            <div style="flex:1;display:flex;align-items:center;justify-content:flex-end;gap:0.5rem">
                                <div style="width:60px;height:6px;background:#f1f5f9;border-radius:3px;overflow:hidden">
                                    <div style="width:${ratio * 100}%;height:100%;background:var(--${colorClass}-color, #10b981)"></div>
                                </div>
                                <span class="value" style="min-width:30px;text-align:right">${l.available_count}/${l.total_count}</span>
                            </div>
                        </div>`;
                    });
                } else {
                    used.forEach(l => {
                        const scanners = l.scanners || [];
                        scanners.forEach(s => {
                            const icon = s.available ?
                                '<svg class="icon" style="color:#10b981"><use href="#icon-check"></use></svg>' :
                                '<svg class="icon" style="color:#ef4444"><use href="#icon-x"></use></svg>';
                            const statusLabel = s.available
                                ? '<span style="font-size:0.75rem;color:var(--text-muted)">已就绪</span>'
                                : (!s.enabled
                                    ? '<span style="font-size:0.75rem;color:#f59e0b">已禁用</span>'
                                    : '<span style="font-size:0.75rem;color:#ef4444">未安装</span>');

                            html += `<div class="stat-row">
                                <div style="flex:1;display:flex;align-items:center;gap:0.5rem">
                                    <span class="value" style="font-weight:600">${s.name}</span>
                                    <span class="badge" style="font-size:0.7rem;padding:0.1rem 0.4rem;background:#f1f5f9;color:#64748b">${l.language}</span>
                                </div>
                                <div style="display:flex;align-items:center;gap:0.4rem">
                                    ${statusLabel}
                                    ${icon}
                                </div>
                            </div>`;
                        });
                    });
                }

                if (html === '') {
                    html = '<div class="empty-state" style="padding:1rem;font-size:0.85rem">无相关扫描器</div>';
                }
                scannerStatusContent.innerHTML = html;
            }
            if (scannerSummaryBadge) scannerSummaryBadge.textContent = `${totalAvailable}/${totalCount}`;
        }
    } catch (e) {
        console.error('Load scanner status error:', e);
    }

    // 绑定切换按钮
    if (scannerToggleBtn && !scannerToggleBtn._bound) {
        scannerToggleBtn._bound = true;
        scannerToggleBtn.onclick = () => {
            scannerViewMode = scannerViewMode === 'summary' ? 'detail' : 'summary';
            loadScannerStatus();
        };
    }
}

// --- Unified Model Manager Logic ---

let currentUnifiedProvider = null;
let unifiedData = {
    providers: [], // from /api/providers/status
    keys: [],      // from /api/providers/keys
    models: []     // from /api/options
};

async function openModelManagementModal() {
    const modal = document.getElementById('modelManagementModal');
    if (modal) {
        modal.display = 'flex'; // Fail-safe
        modal.style.display = 'none'; // Reset first
        modal.style.display = 'flex';
        await loadUnifiedData();
    }
}

function closeModelManagementModal() {
    const modal = document.getElementById('modelManagementModal');
    if (modal) modal.style.display = 'none';
}

async function loadUnifiedData() {
    const sidebar = document.getElementById('providerSidebarList');
    const detail = document.getElementById('providerDetailContent');

    if (sidebar) sidebar.innerHTML = '<div class="loading-state"><div class="spinner-small"></div></div>';

    try {
        // Parallel fetch
        const [pRes, kRes, mRes] = await Promise.all([
            fetch('/api/providers/status'),
            fetch('/api/providers/keys'),
            fetch('/api/options', { cache: 'no-store' })
        ]);

        if (pRes.ok) unifiedData.providers = await pRes.json();
        if (kRes.ok) {
            const data = await kRes.json();
            unifiedData.keys = Array.isArray(data.providers) ? data.providers : [];
        }
        if (mRes.ok) {
            const data = await mRes.json();
            unifiedData.models = data.models || [];
        }

        renderUnifiedSidebar();

        // Auto-select first provider if none selected or not found
        if (!currentUnifiedProvider && unifiedData.providers.length > 0) {
            currentUnifiedProvider = unifiedData.providers[0].name;
        }

        if (currentUnifiedProvider) {
            selectUnifiedProvider(currentUnifiedProvider);
        }

    } catch (e) {
        console.error("Failed to load unified data", e);
        if (sidebar) sidebar.innerHTML = '<div class="error-state">加载失败</div>';
    }
}

function renderUnifiedSidebar() {
    const sidebar = document.getElementById('providerSidebarList');
    if (!sidebar) return;

    sidebar.innerHTML = unifiedData.providers.map(p => {
        const isActive = p.name === currentUnifiedProvider;
        const keyInfo = unifiedData.keys.find(k => k.provider === p.name);
        const isConfigured = keyInfo && keyInfo.configured;

        return `
            <div class="provider-item ${isActive ? 'active' : ''}" onclick="selectUnifiedProvider('${escapeHtml(p.name)}')">
                <span>${escapeHtml(p.label || p.name)}</span>
                <div class="provider-status-dot ${isConfigured ? 'active' : ''}" title="${isConfigured ? '已配置' : '未配置'}"></div>
            </div>
        `;
    }).join('');
}

function selectUnifiedProvider(providerName) {
    currentUnifiedProvider = providerName;
    renderUnifiedSidebar(); // Re-render to update active state
    renderUnifiedDetail(providerName);
}

function renderUnifiedDetail(providerName) {
    const container = document.getElementById('providerDetailContent');
    if (!container) return;

    const provider = unifiedData.providers.find(p => p.name === providerName);
    if (!provider) {
        container.innerHTML = '<div class="empty-state">未找到服务商信息</div>';
        return;
    }

    const keyInfo = unifiedData.keys.find(k => k.provider === providerName) || {};
    const modelGroup = unifiedData.models.find(g => (g.provider || '').toLowerCase() === providerName.toLowerCase()) || {};
    const models = modelGroup.models || [];

    const inputId = `unified-key-input-${providerName}`;
    const configured = !!keyInfo.configured;

    // --- Provider Header ---
    const headerHtml = `
        <div class="provider-header">
            <h2 class="provider-title">${escapeHtml(provider.label || provider.name)}</h2>
            <span class="status-badge ${configured ? 'configured' : 'unconfigured'}">
                ${configured ? '已配置' : '未配置'}
            </span>
        </div>
    `;

    // --- API Key Card ---
    const keyCardHtml = `
        <div class="config-card">
            <div class="config-card-header">
                <svg class="icon"><use href="#icon-key"></use></svg>
                <span>API 密钥</span>
            </div>
            <div class="config-card-body">
                <div class="key-input-row">
                    <div class="key-input-wrapper">
                        <input id="${inputId}" type="password" class="key-input" 
                            placeholder="${configured ? '重新输入以覆盖...' : '输入 API Key...'}"
                            autocomplete="new-password">
                        <button class="key-toggle-btn" onclick="toggleUnifiedKeyVisibility('${inputId}')" title="显示/隐藏">
                            ${typeof getIcon === 'function' ? getIcon('eye') : '👁️'}
                        </button>
                    </div>
                    <button class="key-save-btn" onclick="saveUnifiedProviderKey('${escapeHtml(providerName)}')">保存</button>
                    ${configured ? `<button class="key-clear-btn" onclick="clearUnifiedProviderKey('${escapeHtml(providerName)}')">清除</button>` : ''}
                </div>
                <p class="key-hint"><svg class="icon icon-sm"><use href="#icon-info"></use></svg> 密钥仅存储于项目根目录 <code>.env</code> 文件中，不会上传。</p>
            </div>
        </div>
    `;

    // --- Models Card ---
    const modelsListHtml = models.length > 0
        ? `<div class="models-list">${models.map(m => `
            <div class="model-row">
                <span class="model-name">${escapeHtml(m.label || m.name)}</span>
                <button class="model-delete" onclick="deleteUnifiedModel('${escapeHtml(providerName)}', '${escapeHtml(m.label || m.name)}')" title="删除">×</button>
            </div>
          `).join('')}</div>`
        : '<div class="models-empty">暂无模型</div>';

    const modelsCardHtml = `
        <div class="config-card">
            <div class="config-card-header">
                <span>模型列表</span>
                <span class="model-count">${models.length}</span>
            </div>
            <div class="config-card-body">
                <div class="add-model-row">
                    <input type="text" id="newUnifiedModelName" class="add-model-input" placeholder="输入模型 ID">
                    <button class="add-model-btn" onclick="addUnifiedModel('${escapeHtml(providerName)}')">添加</button>
                </div>
                ${modelsListHtml}
            </div>
        </div>
    `;

    container.innerHTML = headerHtml + keyCardHtml + modelsCardHtml;
}

// --- Interactions ---

window.toggleUnifiedKeyVisibility = function (inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
};

window.saveUnifiedProviderKey = async function (provider) {
    const input = document.getElementById(`unified-key-input-${provider}`);
    if (!input) return;
    const value = input.value.trim();

    if (!value) {
        showToast('请输入密钥', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/providers/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, value })
        });
        if (!res.ok) throw new Error('Failed to save key');

        showToast('密钥已保存', 'success');
        input.value = ''; // clear input for security
        loadUnifiedData(); // Refresh to update status

        // Update global provider status if needed
        if (typeof updateHealthStatus === 'function') updateHealthStatus();
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
};

window.clearUnifiedProviderKey = async function (provider) {
    if (!confirm('确定要清除该密钥吗？')) return;
    try {
        const res = await fetch('/api/providers/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, value: '' }) // Clearing essentially sets it to empty? Or specific endpoint? The original code used setProviderKey with source='clear'
        });
        if (!res.ok) throw new Error('Failed to clear key');
        showToast('密钥已清除', 'success');
        loadUnifiedData();
    } catch (e) {
        showToast('清除失败: ' + e.message, 'error');
    }
};

window.addUnifiedModel = async function (provider) {
    const input = document.getElementById('newUnifiedModelName');
    if (!input) return;
    const name = input.value.trim();
    if (!name) {
        showToast('请输入模型名称', 'warning');
        return;
    }

    try {
        const res = await fetch('/api/models/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, model_name: name })
        });
        if (!res.ok) throw new Error('Add failed');

        showToast('模型已添加', 'success');
        input.value = '';
        loadUnifiedData(); // Refresh list
    } catch (e) {
        showToast('添加失败: ' + e.message, 'error');
    }
};

window.deleteUnifiedModel = async function (provider, modelName) {
    if (!confirm(`确认删除模型 ${modelName}?`)) return;
    try {
        const res = await fetch('/api/models/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, model_name: modelName })
        });
        if (!res.ok) throw new Error('Delete failed');

        showToast('模型已删除', 'success');
        loadUnifiedData();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
};


// Exports
window.openModelManagementModal = openModelManagementModal;
window.closeModelManagementModal = closeModelManagementModal;
window.selectUnifiedProvider = selectUnifiedProvider;

// Legacy stubs to prevent errors if called
window.setupProviderKeysModal = function () { };
window.openProviderKeysModal = openModelManagementModal; // Redirect old calls
window.setProviderKey = async function () { };


async function loadIntentData() {
    const contentDiv = document.getElementById('intent-content');
    const emptyState = document.getElementById('intent-empty');
    const viewMode = document.getElementById('intent-view');
    const thoughtContainer = document.getElementById('intent-thought-container');

    // 也处理仪表盘简化版
    const dashIntentContent = document.getElementById('dash-intent-content');

    if (!window.currentProjectRoot) {
        if (emptyState) emptyState.style.display = 'flex';
        if (contentDiv) contentDiv.innerHTML = '';
        if (viewMode) viewMode.style.display = 'block';
        if (thoughtContainer) thoughtContainer.style.display = 'none';
        if (dashIntentContent) dashIntentContent.innerHTML = '<div class="empty-state">请先选择项目</div>';
        window.intentContent = "";
        return;
    }

    // Extract project name
    const projectName = window.currentProjectRoot.replace(/[\\/]$/, '').split(/[\\/]/).pop();

    try {
        const res = await fetch(
            `/api/intent/${encodeURIComponent(projectName)}?project_root=${encodeURIComponent(window.currentProjectRoot)}`
        );
        if (res.ok) {
            const data = await res.json();
            // 支持 response.content 路径
            let content = data.content || "";
            if (!content && data.response && typeof data.response.content === 'string') {
                content = data.response.content;
            }
            if (content) {
                window.intentContent = content;  // 保存原始 Markdown 内容
                if (emptyState) emptyState.style.display = 'none';
                if (viewMode) viewMode.style.display = 'block';
                if (contentDiv) {
                    // 使用 marked 解析 Markdown
                    if (typeof marked !== 'undefined' && marked.parse) {
                        contentDiv.innerHTML = marked.parse(content);
                    } else {
                        contentDiv.innerHTML = `<div class="intent-text">${escapeHtml(content)}</div>`;
                    }
                }
                if (thoughtContainer) thoughtContainer.style.display = 'none';

                // 更新仪表盘简化版
                if (dashIntentContent) {
                    // 截取前 200 个字符作为摘要
                    const summary = content.length > 200 ? content.substring(0, 200) + '...' : content;
                    dashIntentContent.innerHTML = `<div class="intent-text">${escapeHtml(summary)}</div>`;
                }
            } else {
                window.intentContent = "";
                if (emptyState) emptyState.style.display = 'flex';
                if (contentDiv) contentDiv.innerHTML = '';
                if (dashIntentContent) dashIntentContent.innerHTML = '<div class="empty-state">暂无意图分析</div>';
            }
        } else if (res.status === 404) {
            // Cache not found - this is normal for new projects
            window.intentContent = "";
            if (emptyState) emptyState.style.display = 'flex';
            if (contentDiv) contentDiv.innerHTML = '';
            if (dashIntentContent) dashIntentContent.innerHTML = '<div class="empty-state">暂无意图分析，请运行分析</div>';
        } else {
            // Other error
            console.error("Load intent error: HTTP", res.status);
            if (emptyState) emptyState.style.display = 'flex';
            if (contentDiv) contentDiv.innerHTML = '';
            if (dashIntentContent) dashIntentContent.innerHTML = '<div class="error-state">加载失败</div>';
        }
    } catch (e) {
        console.error("Load intent error:", e);
        if (emptyState) emptyState.style.display = 'flex';
        if (dashIntentContent) dashIntentContent.innerHTML = '<div class="error-state">加载失败</div>';
    }
}

function showScannerHelp() {
    // 防御性检查：确保 detectedLanguages 是数组
    const langs = Array.isArray(detectedLanguages) ? detectedLanguages : [];
    // 对语言名称进行 HTML 转义以防止 XSS 攻击
    const escapedLangs = langs.map(lang => escapeHtml(String(lang))).join(', ');

    const helpContent = `
        <p style="margin: 0 0 1rem 0; color: #4b5563; line-height: 1.6;">
            为了简化界面，系统只显示<strong>项目检测到的语言</strong>对应的扫描器。
        </p>
        <div style="padding: 0.75rem 1rem; background: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 1rem;">
            <div style="font-size: 0.75rem; font-weight: 600; color: #6b7280; margin-bottom: 0.5rem; text-transform: uppercase; letter-spacing: 0.05em;">
                当前检测到的语言
            </div>
            <div style="font-size: 0.9rem; color: #1f2937; font-weight: 600;">
                ${langs.length > 0 ? escapedLangs : '尚未检测到项目语言'}
            </div>
        </div>
        <div style="font-size: 0.85rem; color: #6b7280; line-height: 1.6;">
            <p style="margin: 0 0 0.5rem 0;"><strong style="color: #374151;">扫描器状态说明：</strong></p>
            <ul style="margin: 0 0 1rem 0; padding-left: 1.25rem;">
                <li style="margin-bottom: 0.25rem;"><strong>已就绪</strong>：系统已检测到的扫描器工具</li>
                <li style="margin-bottom: 0.25rem;"><strong>未安装</strong>：系统未检测到的扫描器工具</li>
                <li style="margin-bottom: 0.25rem;"><strong>已禁用</strong>：扫描器已被配置为禁用状态</li>
            </ul>
            <p style="margin: 0 0 0.5rem 0;"><strong style="color: #374151;">切换查看模式：</strong></p>
            <ul style="margin: 0; padding-left: 1.25rem;">
                <li style="margin-bottom: 0.25rem;">点击右上角"<strong>扫描器种类</strong>"按钮可切换详细视图</li>
                <li style="margin-bottom: 0.25rem;">详细视图中可查看每个扫描器的具体状态</li>
            </ul>
        </div>
    `;

    showConfirmDialog({
        title: '扫描器显示规则',
        content: helpContent,
        confirmText: '知了',
        showCancel: false,
        showCloseButton: false
    });
}

// Export to window
window.updateHealthStatus = updateHealthStatus;
window.loadDashboardData = loadDashboardData;
window.loadIntentData = loadIntentData;
window.setupProviderKeysModal = setupProviderKeysModal;
window.loadScannerStatus = loadScannerStatus;
window.showScannerHelp = showScannerHelp;
