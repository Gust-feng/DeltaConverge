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

function setupProviderKeysModal() {
    const savingProviders = new Set();
    const optionsRefreshDelays = [0, 600, 1500, 3000];

    const normalizeProviderName = (provider) => {
        const s = String(provider || '').trim();
        if (!s) return '';
        try {
            return decodeURIComponent(s);
        } catch (_) {
            return s;
        }
    };

    const providerDomId = (provider) => {
        return encodeURIComponent(String(provider || '').trim());
    };

    const getProviderRowEls = (provider) => {
        const raw = normalizeProviderName(provider);
        const p = providerDomId(raw);
        return {
            input: document.getElementById(`provider-key-input-${p}`),
            toggle: document.getElementById(`provider-key-toggle-${p}`),
            clear: document.getElementById(`provider-key-clear-${p}`),
            save: document.getElementById(`provider-key-save-${p}`),
            error: document.getElementById(`provider-key-error-${p}`),
            hint: document.getElementById(`provider-key-hint-${p}`),
        };
    };

    const setRowError = (provider, message) => {
        const els = getProviderRowEls(provider);
        if (!els.error) return;
        const msg = String(message || '').trim();
        if (!msg) {
            els.error.textContent = '';
            els.error.style.display = 'none';
            return;
        }
        els.error.textContent = msg;
        els.error.style.display = 'block';
    };

    const updateSaveDisabled = (provider) => {
        const prov = normalizeProviderName(provider);
        const els = getProviderRowEls(prov);
        if (!els.save || !els.input) return;
        const val = String(els.input.value || '').trim();
        els.save.disabled = savingProviders.has(prov) || !val;
    };

    const refreshOptionsAfterKeyChange = async (provider) => {
        const prov = normalizeProviderName(provider);
        const refreshOnce = async () => {
            if (typeof window.loadOptions === 'function') {
                await window.loadOptions();
            } else {
                const res = await fetch('/api/options', { cache: 'no-store' });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                window.availableGroups = data.models || [];
                window.availableModels = window.availableGroups;
            }

            if (typeof window.renderModelMenu === 'function') {
                window.renderModelMenu(Array.isArray(window.availableGroups) ? window.availableGroups : []);
            }
            if (typeof window.renderIntentModelDropdown === 'function') {
                window.renderIntentModelDropdown(Array.isArray(window.availableGroups) ? window.availableGroups : []);
            }
        };

        for (let i = 0; i < optionsRefreshDelays.length; i++) {
            const waitMs = optionsRefreshDelays[i];
            if (waitMs > 0) {
                await new Promise(r => setTimeout(r, waitMs));
            }

            try {
                await refreshOnce();
            } catch (_) { }

            const groups = Array.isArray(window.availableGroups) ? window.availableGroups : [];
            if (!prov || groups.length === 0) continue;
            const g = groups.find(x => String(x && x.provider ? x.provider : '').trim() === prov);
            const models = g && Array.isArray(g.models) ? g.models : [];
            const anyAvailable = models.some(m => m && m.available !== false);
            if (anyAvailable) break;
        }
    };

    window.toggleProviderKeyVisibility = function (provider) {
        const prov = normalizeProviderName(provider);
        const els = getProviderRowEls(prov);
        if (!els.input || !els.toggle) return;
        const isPass = els.input.type === 'password';
        els.input.type = isPass ? 'text' : 'password';
        els.toggle.innerHTML = (typeof getIcon === 'function')
            ? getIcon(isPass ? 'eye-off' : 'eye')
            : (isPass ? '🙈' : '👁️');
    };

    window.onProviderKeyInput = function (provider) {
        const prov = normalizeProviderName(provider);
        setRowError(prov, '');
        updateSaveDisabled(prov);
    };

    window.saveProviderKey = async function (provider) {
        const prov = normalizeProviderName(provider);
        const els = getProviderRowEls(prov);
        if (!els.input) return;
        const value = String(els.input.value || '').trim();
        await window.setProviderKey(prov, value, { source: 'save' });
    };

    window.clearProviderKey = async function (provider) {
        const prov = normalizeProviderName(provider);
        const ok = confirm('确定要清除该提供商的密钥吗？\n\n清除后该提供商将不可用，直到重新配置。');
        if (!ok) return;
        await window.setProviderKey(prov, '', { source: 'clear' });
    };

    window.openProviderKeysModal = async function () {
        const modal = document.getElementById('providerKeysModal');
        const list = document.getElementById('providerKeysList');
        if (!modal || !list) return;

        modal.style.display = 'flex';
        list.innerHTML = '<div class="loading-state"><div class="spinner-small"></div><span>加载中...</span></div>';

        const renderProviderKeys = (providersData) => {
            const providers = Array.isArray(providersData) ? providersData : [];
            const items = providers.map(p => {
                const provider = String(p.provider || '').trim();
                const providerId = providerDomId(provider);
                const inputId = `provider-key-input-${providerId}`;
                const toggleId = `provider-key-toggle-${providerId}`;
                const clearId = `provider-key-clear-${providerId}`;
                const saveId = `provider-key-save-${providerId}`;
                const errorId = `provider-key-error-${providerId}`;
                const hintId = `provider-key-hint-${providerId}`;
                const configured = !!p.configured;
                const masked = p.masked || '';
                return `
                    <div class="provider-key-card" data-provider="${escapeHtml(provider)}">
                        <div class="provider-key-header">
                            <div class="provider-key-title">${escapeHtml(p.label || p.provider)}</div>
                            <span class="badge ${configured ? 'success' : ''} provider-key-badge">${configured ? '已配置' : '未配置'}</span>
                        </div>
                        <div class="provider-key-input-row">
                            <div class="provider-key-input-group">
                                <input id="${inputId}" type="password" class="env-value provider-key-input" value="" placeholder="输入新密钥..." autocomplete="new-password" name="pk-${escapeHtml(provider)}" oninput="onProviderKeyInput('${providerId}')" onkeydown="(function(e){ if(e && e.key === 'Enter'){ e.preventDefault(); saveProviderKey('${providerId}'); } })(event)">
                                <button id="${toggleId}" class="btn-icon" onclick="toggleProviderKeyVisibility('${providerId}')" title="显示/隐藏">
                                    ${typeof getIcon === 'function' ? getIcon('eye') : '👁️'}
                                </button>
                                ${configured ? `
                                    <button id="${clearId}" class="btn-icon provider-key-clear" onclick="clearProviderKey('${providerId}')" title="清除密钥">
                                        ${typeof getIcon === 'function' ? getIcon('trash') : '🗑️'}
                                    </button>
                                ` : ''}
                            </div>
                            <button id="${saveId}" class="btn-primary provider-key-save" onclick="saveProviderKey('${providerId}')" disabled>保存</button>
                        </div>
                        <div class="provider-key-hint" id="${hintId}">
                            当前：${configured ? (masked ? escapeHtml(masked) : '已配置') : '未配置'}
                        </div>
                        <div class="provider-key-error" id="${errorId}" style="display:none"></div>
                    </div>
                `;
            }).join('');

            if (!items) return '<div class="empty-state">暂无可配置的提供商</div>';

            return `
                <div class="provider-keys-hint">
                    密钥会写入项目根目录的 <code>.env</code> 文件（不会提交到 Git），保存后将会自动刷新页面;<br>
                    为确保系统能够流畅运行,建议使用的Key的RPM&gt;20(一分钟内向模型提供方最多发起的请求数)
                </div>
                <div class="provider-keys-grid">${items}</div>
            `;
        };

        try {
            const res = await fetch('/api/providers/keys');
            const data = res.ok ? await res.json() : {};
            const providers = Array.isArray(data.providers) ? data.providers : [];
            list.innerHTML = renderProviderKeys(providers);

            providers.forEach(p => {
                updateSaveDisabled(p.provider);
                const els = getProviderRowEls(p.provider);
                if (els.input) {
                    els.input.value = '';
                }
                if (els.toggle && typeof getIcon === 'function') {
                    els.toggle.innerHTML = getIcon('eye');
                }
                if (els.error) {
                    els.error.textContent = '';
                    els.error.style.display = 'none';
                }
            });
        } catch (e) {
            list.innerHTML = `
                <div class="error-state">
                    <div style="font-weight:600;margin-bottom:0.35rem">加载失败</div>
                    <div style="font-size:0.85rem;opacity:0.9">请检查服务是否启动，或稍后重试。</div>
                    <div style="margin-top:0.65rem">
                        <button class="btn-secondary btn-small" onclick="openProviderKeysModal()">重试</button>
                    </div>
                </div>
            `;
        }
    };

    window.closeProviderKeysModal = function () {
        const modal = document.getElementById('providerKeysModal');
        if (modal) modal.style.display = 'none';
    };

    window.setProviderKey = async function (provider, value, options = {}) {
        const prov = normalizeProviderName(provider);
        if (!prov) return;
        if (savingProviders.has(prov)) return;
        savingProviders.add(prov);

        const els = getProviderRowEls(prov);
        setRowError(prov, '');
        if (els.input) els.input.disabled = true;
        if (els.toggle) els.toggle.disabled = true;
        if (els.clear) els.clear.disabled = true;
        if (els.save) {
            updateSaveDisabled(prov);
            if (typeof setButtonLoading === 'function') {
                setButtonLoading(els.save, true);
            }
        }

        try {
            const res = await fetch('/api/providers/keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: prov, value })
            });
            if (!res.ok) {
                let msg = `保存失败 (HTTP ${res.status})`;
                try {
                    const err = await res.json();
                    if (err && err.detail) msg = String(err.detail);
                } catch (_) { }
                throw new Error(msg);
            }

            const actionText = options && options.source === 'clear' ? '已清除' : '已保存';
            showToast(`密钥${actionText}`, 'success');

            openProviderKeysModal();

            try {
                const providerStatusContent = document.getElementById('provider-status-content');
                const providerAvailableBadge = document.getElementById('provider-available-badge');
                const sres = await fetch('/api/providers/status');
                if (sres.ok) {
                    const providers = await sres.json();
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
            } catch (_) { }

            try {
                if (typeof updateHealthStatus === 'function') {
                    await updateHealthStatus();
                }
            } catch (_) { }

            try {
                await refreshOptionsAfterKeyChange(prov);
            } catch (_) { }
        } catch (e) {
            const msg = e && e.message ? String(e.message) : '更新失败';
            setRowError(prov, msg);
            showToast(msg, 'error');
        } finally {
            savingProviders.delete(prov);
            if (els.input) {
                els.input.disabled = false;
            }
            if (els.toggle) {
                els.toggle.disabled = false;
            }
            if (els.clear) {
                els.clear.disabled = false;
            }
            if (els.save) {
                if (typeof setButtonLoading === 'function') {
                    setButtonLoading(els.save, false);
                }
                updateSaveDisabled(prov);
            }
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
