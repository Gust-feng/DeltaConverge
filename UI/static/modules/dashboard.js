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

async function loadDashboardData() {
    const healthMetricsDiv = document.getElementById('health-metrics');
    const dashProjectPath = document.getElementById('dash-project-path');
    const dashDiffStatus = document.getElementById('dash-diff-status');
    const sessionStatsContent = document.getElementById('session-stats-content');
    const sessionTotalBadge = document.getElementById('session-total-badge');
    const providerStatusContent = document.getElementById('provider-status-content');
    const providerAvailableBadge = document.getElementById('provider-available-badge');

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
        }
    } catch (e) {
        if (healthMetricsDiv) healthMetricsDiv.style.display = 'none';
    }

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
        GitHistory.init(window.currentProjectRoot);
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

function setupProviderKeysModal() {
    window.openProviderKeysModal = async function () {
        const modal = document.getElementById('providerKeysModal');
        const list = document.getElementById('providerKeysList');
        if (!modal || !list) return;

        modal.style.display = 'flex';
        list.innerHTML = '<div class="loading-state">加载中...</div>';

        try {
            const res = await fetch('/api/env/vars');
            if (!res.ok) throw new Error('Failed to load');
            const vars = await res.json();

            const keyVars = Object.entries(vars).filter(([k]) =>
                k.includes('API_KEY') || k.includes('SECRET') || k.includes('TOKEN')
            );

            if (keyVars.length === 0) {
                list.innerHTML = '<div class="empty-state">暂无密钥配置</div>';
            } else {
                list.innerHTML = keyVars.map(([k, v]) => {
                    const masked = v ? '••••••••' + v.slice(-4) : '未设置';
                    return `
                        <div class="env-var-row">
                            <span class="env-key">${escapeHtml(k)}</span>
                            <span class="env-value">${masked}</span>
                            <button class="btn-icon" onclick="editEnvVar('${escapeHtml(k)}')">${getIcon('edit')}</button>
                        </div>
                    `;
                }).join('');
            }
        } catch (e) {
            list.innerHTML = '<div class="error-state">加载失败</div>';
        }
    };

    window.closeProviderKeysModal = function () {
        const modal = document.getElementById('providerKeysModal');
        if (modal) modal.style.display = 'none';
    };

    window.editEnvVar = async function (key) {
        const newValue = prompt(`请输入 ${key} 的新值:`);
        if (newValue === null) return;

        try {
            const res = await fetch('/api/env/vars', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, value: newValue })
            });
            if (!res.ok) throw new Error('Failed to save');
            showToast('密钥已更新', 'success');
            openProviderKeysModal();
        } catch (e) {
            showToast('更新失败', 'error');
        }
    };
}

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
        const res = await fetch(`/api/cache/intent/${encodeURIComponent(projectName)}`);
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

// Export to window
window.updateHealthStatus = updateHealthStatus;
window.loadDashboardData = loadDashboardData;
window.loadIntentData = loadIntentData;
window.setupProviderKeysModal = setupProviderKeysModal;
window.loadScannerStatus = loadScannerStatus;
