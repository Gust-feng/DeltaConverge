/**
 * diff.js - Diff 分析页面模块
 */

const DIFF_CACHE_TTL_MS = 60 * 1000;
const diffAnalysisCache = new Map();
const diffFileCache = new Map();

const DIFF_REQUEST_TIMEOUT_MS = 30000;

let activeDiffItemEl = null;

function fetchWithTimeout(url, options = {}, timeoutMs = DIFF_REQUEST_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => {
        try { controller.abort(); } catch (_) { }
    }, timeoutMs);

    const merged = { ...options, signal: controller.signal };
    return fetch(url, merged)
        .finally(() => {
            clearTimeout(timer);
        });
}

async function refreshDiffAnalysis(options = {}) {
    const diffFileList = document.getElementById('diff-file-list');
    if (!diffFileList) return;
    
    if (!window.currentProjectRoot) {
        diffFileList.innerHTML = '<div class="empty-state">请先在仪表盘或审查页面选择项目</div>';
        return;
    }
    
    const force = !!(options && options.force);
    const key = window.currentProjectRoot;
    const now = Date.now();

    if (force) {
        try { diffAnalysisCache.delete(key); } catch (_) { }
        try {
            const prefix = `${window.currentProjectRoot}::`;
            for (const k of diffFileCache.keys()) {
                if (typeof k === 'string' && k.startsWith(prefix)) {
                    diffFileCache.delete(k);
                }
            }
        } catch (_) { }
    }

    const cached = diffAnalysisCache.get(key);
    if (!force && cached && cached.data && (now - cached.ts) < DIFF_CACHE_TTL_MS) {
        window.currentDiffMode = cached.data.mode;
        renderDiffFileList(cached.data.files);
        return;
    }

    diffFileList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);">Loading diff...</div>';

    if (!force && cached && cached.promise && (now - cached.ts) < DIFF_CACHE_TTL_MS) {
        try {
            await cached.promise;
        } catch (_) { }
        return;
    }

    const promise = (async () => {
        let reqMode = 'working';
        try {
            const sres = await fetchWithTimeout('/api/diff/status?project_root=' + encodeURIComponent(window.currentProjectRoot));
            if (sres && sres.ok) {
                const st = await sres.json();
                if (st && st.has_staged_changes) reqMode = 'staged';
                else if (st && st.has_working_changes) reqMode = 'working';
            }
        } catch (_) { }

        const res = await fetchWithTimeout('/api/diff/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: window.currentProjectRoot, mode: reqMode })
        });

        if (!res.ok) throw new Error('HTTP ' + res.status);

        const data = await res.json();
        let errorMsg = null;

        if (data && data.status && data.status.error) {
            errorMsg = data.status.error;
        } else if (data && data.summary && data.summary.error) {
            errorMsg = data.summary.error;
        }

        if (errorMsg) {
            if (errorMsg.indexOf('not a git repository') >= 0) {
                diffFileList.innerHTML = '<div class="empty-state">此目录不是 Git 仓库</div>';
            } else if (errorMsg.indexOf('No changes detected') >= 0) {
                diffFileList.innerHTML = '<div class="empty-state">无文件变更（工作区干净）</div>';
            } else {
                diffFileList.innerHTML = '<div class="empty-state">' + escapeHtml(errorMsg) + '</div>';
            }
            diffAnalysisCache.delete(key);
            return;
        }

        window.currentDiffMode = reqMode;
        const files = (data && data.files) ? data.files : [];
        diffAnalysisCache.set(key, { ts: Date.now(), data: { mode: reqMode, files }, promise: null });
        renderDiffFileList(files);

        if (options && options.reload_active && window.currentDiffActivePath) {
            const p = window.currentDiffActivePath;
            let el = null;
            try {
                const list = document.getElementById('diff-file-list');
                if (list) {
                    const items = list.querySelectorAll('.file-list-item');
                    for (const item of items) {
                        let raw = item.getAttribute('data-path');
                        if (!raw) continue;
                        try { raw = decodeURIComponent(raw); } catch (_) { }
                        if (raw === p) { el = item; break; }
                    }
                }
            } catch (_) { }
            loadFileDiff(p, el, { force: true });
        }
    })();

    diffAnalysisCache.set(key, { ts: now, data: null, promise });

    try {
        await promise;
    } catch (e) {
        const latest = diffAnalysisCache.get(key);
        if (latest && latest.promise === promise) {
            diffAnalysisCache.delete(key);
        }
        console.error('Refresh diff error:', e);
        const msg = (e && e.name === 'AbortError') ? '请求超时，请稍后重试' : (e && e.message ? e.message : 'Unknown error');
        diffFileList.innerHTML = '<div style="padding:1rem;color:red;">Error: ' + escapeHtml(msg) + '</div>';
    }
}

function resetDiffState() {
    try { diffAnalysisCache.clear(); } catch (_) { }
    try { diffFileCache.clear(); } catch (_) { }
    activeDiffItemEl = null;
    try { window.currentDiffText = null; } catch (_) { }

    const diffFileList = document.getElementById('diff-file-list');
    if (diffFileList) {
        diffFileList.innerHTML = '<div class="empty-state">请先在仪表盘或审查页面选择项目</div>';
    }
    const diffContentArea = document.getElementById('diff-content-area');
    if (diffContentArea) {
        diffContentArea.innerHTML = '<div class="empty-state">请选择左侧文件查看差异</div>';
    }
}

function renderDiffFileList(files) {
    const diffFileList = document.getElementById('diff-file-list');
    if (!diffFileList) return;
    
    if (!files || files.length === 0) {
        diffFileList.innerHTML = '<div class="empty-state">无文件变更</div>';
        return;
    }

    // Fast render via single innerHTML + event delegation
    const html = files.map(file => {
        const requestPath = typeof file === 'string' ? file : (file.path || 'Unknown File');
        const displayPath = (typeof file === 'object' && file.display_path) ? file.display_path : requestPath;
        const changeType = typeof file === 'object' ? file.change_type : 'modify';

        let icon = getIcon('file');
        let statusClass = 'status-modify';
        if (changeType === 'add') { icon = getIcon('plus'); statusClass = 'status-add'; }
        else if (changeType === 'delete') { icon = getIcon('trash'); statusClass = 'status-delete'; }
        else if (changeType === 'rename') { icon = getIcon('edit'); statusClass = 'status-rename'; }

        const fileName = displayPath.split('/').pop();
        const dirPath = displayPath.substring(0, displayPath.lastIndexOf('/'));

        const encodedPath = encodeURIComponent(requestPath);
        return `
            <div class="file-list-item" data-path="${encodedPath}">
                <div class="file-item-row">
                    <span class="file-icon ${statusClass}">${icon}</span>
                    <div class="file-info">
                        <div class="file-name" title="${escapeHtml(displayPath)}">${escapeHtml(fileName)}</div>
                        <div class="file-path" title="${escapeHtml(dirPath)}">${escapeHtml(dirPath)}</div>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    diffFileList.innerHTML = html;

    // Reset active state pointer after re-render
    activeDiffItemEl = null;

    if (!diffFileList._boundClick) {
        diffFileList._boundClick = true;
        diffFileList.addEventListener('click', (e) => {
            const item = e.target.closest('.file-list-item');
            if (!item || !diffFileList.contains(item)) return;
            const raw = item.getAttribute('data-path');
            if (!raw) return;
            let p = raw;
            try { p = decodeURIComponent(raw); } catch (_) { }
            loadFileDiff(p, item);
        });
    }
}

async function loadFileDiff(filePath, clickedEl = null, options = {}) {
    const diffContentArea = document.getElementById('diff-content-area');
    const diffFileList = document.getElementById('diff-file-list');
    if (!diffContentArea) return;
    
    if (!window.currentProjectRoot) {
        diffContentArea.innerHTML = '<div style="padding:1rem;color:red;">请先选择项目文件夹</div>';
        return;
    }
    
    diffContentArea.innerHTML = '<div class="empty-state">Loading...</div>';
    
    if (diffFileList && clickedEl) {
        if (activeDiffItemEl && activeDiffItemEl !== clickedEl) {
            activeDiffItemEl.classList.remove('active');
        }
        clickedEl.classList.add('active');
        activeDiffItemEl = clickedEl;
    }

    try { window.currentDiffActivePath = filePath; } catch (_) { }

    try {
        const cacheKey = `${window.currentProjectRoot}::${window.currentDiffMode}::${filePath}`;
        const now = Date.now();
        const force = !!(options && options.force);
        if (force) {
            try { diffFileCache.delete(cacheKey); } catch (_) { }
        }
        const cached = force ? null : diffFileCache.get(cacheKey);

        let data = null;
        if (cached && cached.data && (now - cached.ts) < DIFF_CACHE_TTL_MS) {
            data = cached.data;
        } else {
            const inFlight = cached && cached.promise && (now - cached.ts) < DIFF_CACHE_TTL_MS;
            const promise = inFlight ? cached.promise : (async () => {
                const ts = Date.now();
                const res = await fetchWithTimeout(`/api/diff/file/${encodeURIComponent(filePath)}?project_root=${encodeURIComponent(window.currentProjectRoot)}&mode=${window.currentDiffMode}&_ts=${ts}`);
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const d = await res.json();
                diffFileCache.set(cacheKey, { ts: Date.now(), data: d, promise: null });
                return d;
            })();

            if (!inFlight) {
                diffFileCache.set(cacheKey, { ts: now, data: null, promise });
            }

            try {
                data = await promise;
            } catch (e) {
                const latest = diffFileCache.get(cacheKey);
                if (latest && latest.promise === promise) {
                    diffFileCache.delete(cacheKey);
                }
                throw e;
            }
        }

        if (data.error) {
            diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">${escapeHtml(data.error)}</div>`;
            return;
        }

        const diffText = data.diff_text || data.diff_content || "";
        
        if (window.Diff2HtmlUI && diffText.trim()) {
            const currentViewMode = window.currentDiffViewMode || 'side-by-side';
            
            diffContentArea.innerHTML = `
                <div class="diff-header">
                    <h3 title="${escapeHtml(filePath)}">${escapeHtml(filePath)}</h3>
                    <div class="diff-controls">
                        <label class="${currentViewMode === 'line-by-line' ? 'active' : ''}">
                            <input type="radio" name="diff-view" value="line-by-line" ${currentViewMode === 'line-by-line' ? 'checked' : ''} onclick="toggleDiffView('line-by-line')">
                            <span class="view-option">Unified</span>
                        </label>
                        <label class="${currentViewMode === 'side-by-side' ? 'active' : ''}">
                            <input type="radio" name="diff-view" value="side-by-side" ${currentViewMode === 'side-by-side' ? 'checked' : ''} onclick="toggleDiffView('side-by-side')">
                            <span class="view-option">Split</span>
                        </label>
                    </div>
                </div>
                <div id="diff-ui-container" style="padding: 0;"></div>
            `;
            
            window.currentDiffText = diffText;
            renderDiff2Html(diffText, currentViewMode);
            
        } else {
            const formattedDiff = diffText ? diffText.replace(/\r\n/g, '\n') : "No content";
            diffContentArea.innerHTML = `
                <div style="padding:1rem;">
                    <h3>${escapeHtml(filePath)}</h3>
                    <pre style="background:var(--bg-secondary);padding:1rem;overflow:auto;"><code>${escapeHtml(formattedDiff)}</code></pre>
                </div>
            `;
        }

    } catch (e) {
        console.error("Load file diff error:", e);
        const msg = (e && e.name === 'AbortError') ? '请求超时，请稍后重试' : (e && e.message ? e.message : 'Unknown error');
        diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">Error: ${escapeHtml(msg)}</div>`;
    }
}

function renderDiff2Html(diffText, outputFormat) {
    const targetElement = document.getElementById('diff-ui-container');
    if (!targetElement || !window.Diff2HtmlUI) return;
    
    const configuration = {
        drawFileList: false,
        fileListToggle: false,
        fileContentToggle: false,
        matching: 'lines',
        outputFormat: outputFormat,
        synchronisedScroll: true,
        highlight: true,
        renderNothingWhenEmpty: false,
    };
    
    const diff2htmlUi = new Diff2HtmlUI(targetElement, diffText, configuration);
    diff2htmlUi.draw();
    diff2htmlUi.highlightCode();
}

function toggleDiffView(mode) {
    window.currentDiffViewMode = mode;
    
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

// Export to window
window.refreshDiffAnalysis = refreshDiffAnalysis;
window.renderDiffFileList = renderDiffFileList;
window.loadFileDiff = loadFileDiff;
window.renderDiff2Html = renderDiff2Html;
window.toggleDiffView = toggleDiffView;
window.resetDiffState = resetDiffState;
