/**
 * diff.js - Diff 分析页面模块
 */

const DIFF_CACHE_TTL_MS = 60 * 1000;
const diffAnalysisCache = new Map();
const diffFileCache = new Map();

const DIFF_REQUEST_TIMEOUT_MS = 30000;
const MAX_DIFF_LINES_WARNING = 5000; // 超过此行数显示警告
const MAX_DIFF_LINES_BLOCK = 20000; // 超过此行数阻止渲染
const MAX_DIFF_CHARS_WARNING = 200000; // 200KB 字符数警告阈值
const MAX_DIFF_CHARS_BLOCK = 500000; // 500KB 字符数阻止阈值

let activeDiffItemEl = null;
let manualDiffMode = null; // 用户手动选择的模式,null表示使用自动检测

// Commit范围状态 (用于历史提交模式)
let currentCommitFrom = null;
let currentCommitTo = 'HEAD';
// Commit模式相关状态
let commitHistoryData = [];
let selectedCommitFrom = null;
let selectedCommitTo = 'HEAD';
let userExplicitlySelectedTo = false; // 用户是否明确选择了结束提交
let isEditingCommitRange = false; // 用户是否正在编辑提交范围
let commitModeFilesCache = null; // 缓存commit模式加载的文件列表

// 显示彩蛋到 diff 内容区域
// 显示彩蛋到 diff 内容区域
let isFirstEasterEggLoad = true;
let lastEasterEggType = 'default';
let lastEasterEggData = null;

/**
 * 显示彩蛋到 diff 内容区域
 * @param {boolean|string} typeOrIsEmpty - 布尔值代表 isEmpty，字符串代表 type
 * @param {string} diffMode - 当前的 diff 模式
 * @param {object} data - 额外数据（如 commit ranges）
 */
function showDiffContentEasterEgg(typeOrIsEmpty = false, diffMode = 'working', data = null) {
    const contentArea = document.getElementById('diff-content-area');
    if (contentArea && window.EasterEgg) {
        // 兼容旧调用（布尔值）和新调用（字符串类型）
        let type;
        if (typeof typeOrIsEmpty === 'string') {
            type = typeOrIsEmpty;
        } else {
            type = typeOrIsEmpty ? 'no-changes' : 'default';
        }

        // 如果类型变化、数据变化或首次加载，使用动画
        const dataChanged = JSON.stringify(data) !== JSON.stringify(lastEasterEggData);
        const shouldAnimate = isFirstEasterEggLoad || (lastEasterEggType !== type) || dataChanged;

        if (shouldAnimate) {
            window.EasterEgg.init(contentArea, true, type, diffMode, data);
            isFirstEasterEggLoad = false;
        } else {
            // 状态没变，只显示静态以避免干扰
            window.EasterEgg.init(contentArea, false, type, diffMode, data);
        }

        lastEasterEggType = type;
        lastEasterEggData = data;
    } else if (contentArea) {
        contentArea.innerHTML = '<div class="empty-state">请选择文件查看 Diff</div>';
    }
}

// 获取当前diff设置 (供审查时使用)
function getCurrentDiffSettings() {
    return {
        mode: manualDiffMode || 'auto',
        commit_from: manualDiffMode === 'commit' ? currentCommitFrom : null,
        commit_to: manualDiffMode === 'commit' ? currentCommitTo : null,
    };
}

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

function updateDiffStatusHint(mode, fileCount) {
    const hintBox = document.getElementById('diff-status-hint');
    const hintText = document.getElementById('diff-status-text');
    if (!hintBox || !hintText) return;

    hintBox.style.display = 'flex';

    let msg = '';
    // Color logic could be added here by modifying style

    // 特殊处理：commit模式但未选择提交范围
    if (mode === 'commit' && !selectedCommitFrom) {
        msg = '请选择历史提交范围';
        hintBox.style.background = 'rgba(156, 163, 175, 0.1)';
        hintBox.style.border = '1px solid rgba(156, 163, 175, 0.2)';
        hintText.textContent = msg;
        updateReviewModeBadge(mode);
        return;
    }

    if (fileCount === 0) {
        if (mode === 'commit') {
            msg = '所选提交范围无文件变更';
        } else if (mode === 'pr') {
            msg = '当前仓库无 PR 变更';
        } else if (mode === 'staged') {
            msg = '暂存区无文件变更';
        } else if (mode === 'working') {
            msg = '工作区无未暂存变更';
        } else {
            msg = '当前无变更，无需审查';
        }
        hintBox.style.background = 'rgba(156, 163, 175, 0.1)';
        hintBox.style.border = '1px solid rgba(156, 163, 175, 0.2)';
    } else {
        if (mode === 'staged') {
            msg = `暂存区 ${fileCount} 个文件，建议审查后提交`;
            hintBox.style.background = 'rgba(16, 185, 129, 0.1)';
            hintBox.style.border = '1px solid rgba(16, 185, 129, 0.2)';
        } else if (mode === 'working') {
            msg = `工作区 ${fileCount} 个文件未暂存`;
            hintBox.style.background = 'rgba(245, 158, 11, 0.1)';
            hintBox.style.border = '1px solid rgba(245, 158, 11, 0.2)';
        } else if (mode === 'commit') {
            msg = `历史提交包含 ${fileCount} 个文件变更`;
            hintBox.style.background = 'rgba(59, 130, 246, 0.1)';
            hintBox.style.border = '1px solid rgba(59, 130, 246, 0.2)';
        } else if (mode === 'pr') {
            msg = `PR 包含 ${fileCount} 个文件变更`;
            hintBox.style.background = 'rgba(168, 85, 247, 0.1)';
            hintBox.style.border = '1px solid rgba(168, 85, 247, 0.2)';
        } else {
            msg = `检测到 ${fileCount} 个文件变更`;
            hintBox.style.background = 'rgba(59, 130, 246, 0.1)';
            hintBox.style.border = '1px solid rgba(59, 130, 246, 0.2)';
        }
    }
    hintText.textContent = msg;

    // Also update the header badge
    updateReviewModeBadge(mode);
}

function updateReviewModeBadge(mode) {
    const dropdown = document.getElementById('headerModeDropdown');
    const trigger = document.getElementById('headerModeTrigger');
    const textSpan = document.getElementById('headerModeText');

    if (dropdown && trigger && textSpan) {
        dropdown.style.display = 'inline-flex';

        const modeNames = {
            'auto': '自动检测',
            'working': '工作区模式',
            'staged': '暂存区模式',
            'pr': 'PR 模式',
            'commit': '历史提交模式'
        };
        const text = modeNames[mode] || '自动检测';
        textSpan.textContent = text;

        // Reset classes
        trigger.className = 'dropdown-trigger mode-badge';

        // Add specific mode class
        if (mode === 'staged') {
            trigger.classList.add('mode-staged');
        } else if (mode === 'working') {
            trigger.classList.add('mode-working');
        } else if (mode === 'commit') {
            trigger.classList.add('mode-commit');
        } else if (mode === 'pr') {
            trigger.classList.add('mode-pr');
        } else if (mode === 'loading') {
            trigger.classList.add('mode-loading');
            textSpan.textContent = '检测中...';
        } else {
            trigger.classList.add('mode-default');
        }

        // Highlight selected item in menu
        const menu = document.getElementById('headerModeMenu');
        if (menu) {
            menu.querySelectorAll('.dropdown-item').forEach(item => {
                if (item.dataset.mode === mode) item.classList.add('selected');
                else item.classList.remove('selected');
            });
        }
    }
}

// 初始化顶部导航栏的模式切换下拉菜单
let headerModeDropdownInitialized = false;
function initHeaderModeDropdown() {
    if (headerModeDropdownInitialized) return;

    const trigger = document.getElementById('headerModeTrigger');
    const menu = document.getElementById('headerModeMenu');
    const dropdown = document.getElementById('headerModeDropdown');

    if (!trigger || !menu || !dropdown) return;

    headerModeDropdownInitialized = true;
    console.log('[Diff] Initializing header mode dropdown');

    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.classList.toggle('open');
    });

    menu.addEventListener('click', (e) => {
        const item = e.target.closest('.dropdown-item');
        if (!item) return;

        const mode = item.getAttribute('data-mode');
        selectDiffMode(mode);
        dropdown.classList.remove('open');
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
    const now = Date.now();

    // 确定当前要使用的模式
    let targetMode = 'working';
    if (manualDiffMode && manualDiffMode !== 'auto') {
        targetMode = manualDiffMode;
    }

    // 对于commit模式，不走普通的diff分析流程
    if (targetMode === 'commit') {
        window.currentDiffMode = 'commit';
        updateReviewModeBadge('commit');

        // 显示commit选择面板
        const commitPanel = document.getElementById('commitSelectorPanel');
        if (commitPanel) commitPanel.style.display = 'block';

        // 如果有缓存的commit模式文件列表，恢复显示
        if (commitModeFilesCache && commitModeFilesCache.files && commitModeFilesCache.files.length > 0) {
            updateDiffStatusHint('commit', commitModeFilesCache.files.length);
            renderDiffFileList(commitModeFilesCache.files, {
                isCommitMode: true,
                diffText: commitModeFilesCache.diffText
            });
        } else {
            // 没有缓存数据，显示提示
            diffFileList.innerHTML = '<div class="empty-state">请选择提交范围后点击"查看"</div>';
        }
        return;
    }

    // 缓存键需要包含模式，避免模式切换时使用错误的缓存
    const key = `${window.currentProjectRoot}::${targetMode}`;

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
        updateDiffStatusHint(cached.data.mode, cached.data.files.length);
        renderDiffFileList(cached.data.files);
        if (cached.data.files.length > 0 && !window.currentDiffActivePath) {
            showDiffContentEasterEgg(false);
        }
        return;
    }
    // 显示骨架屏加载动画
    diffFileList.innerHTML = `
        <div class="diff-loading-skeleton">
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title"></div>
                    <div class="skeleton-line subtitle"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title" style="width:75%"></div>
                    <div class="skeleton-line subtitle" style="width:50%"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title" style="width:55%"></div>
                    <div class="skeleton-line subtitle" style="width:35%"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
            <div class="skeleton-item">
                <div class="skeleton-icon"></div>
                <div class="skeleton-content">
                    <div class="skeleton-line title" style="width:65%"></div>
                    <div class="skeleton-line subtitle" style="width:45%"></div>
                </div>
                <div class="skeleton-badge"></div>
            </div>
        </div>
        </div>
    `;

    // 如果右侧内容区为空，显示彩蛋
    // 这样在首次加载时（isFirstEasterEggLoad=true）会播放动画
    const contentArea = document.getElementById('diff-content-area');
    if (contentArea && (!contentArea.innerHTML || contentArea.innerHTML.trim() === '' || contentArea.querySelector('.empty-state'))) {
        showDiffContentEasterEgg();
    }

    if (!force && cached && cached.promise && (now - cached.ts) < DIFF_CACHE_TTL_MS) {
        try {
            await cached.promise;
        } catch (_) { }
        return;
    }

    const promise = (async () => {
        updateReviewModeBadge('loading'); // Show loading state immediately
        let reqMode = targetMode;

        // 如果是auto模式，使用自动检测
        if (!manualDiffMode || manualDiffMode === 'auto') {
            try {
                const sres = await fetchWithTimeout('/api/diff/status?project_root=' + encodeURIComponent(window.currentProjectRoot));
                if (sres && sres.ok) {
                    const st = await sres.json();
                    // 按优先级选择模式: staged > working > pr
                    if (st && st.has_staged_changes) {
                        reqMode = 'staged';
                    } else if (st && st.has_working_changes) {
                        reqMode = 'working';
                    } else if (st && st.has_pr_changes) {
                        reqMode = 'pr';
                    }
                }
            } catch (_) { }
        }

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
                updateDiffStatusHint(reqMode, 0);
            } else if (errorMsg.indexOf('No changes detected') >= 0 || errorMsg.indexOf('No PR') >= 0 || errorMsg.indexOf('no pull request') >= 0) {
                diffFileList.innerHTML = '<div class="empty-state">未检测到所选模式的差异</div>';
                updateDiffStatusHint(reqMode, 0);
                showDiffContentEasterEgg(true, reqMode);
            } else {
                diffFileList.innerHTML = '<div class="empty-state">' + escapeHtml(errorMsg) + '</div>';
                // 即使有错误也更新状态提示
                updateDiffStatusHint(reqMode, 0);
                if (diffFileList.innerHTML.indexOf('empty-state') !== -1) {
                    showDiffContentEasterEgg(true, reqMode);
                }
            }
            diffAnalysisCache.delete(key);
            return;
        }

        window.currentDiffMode = reqMode;
        const files = (data && data.files) ? data.files : [];
        updateDiffStatusHint(reqMode, files.length); // Update status hint
        diffAnalysisCache.set(key, { ts: Date.now(), data: { mode: reqMode, files }, promise: null });
        renderDiffFileList(files);

        // 如果有文件，且当前没有选中的文件在查看（即刚加载完列表），确保彩蛋显示为"请选择文件"状态
        // 这会触发从 "无变更" -> "请选择文件" 的动画
        if (files.length > 0 && !window.currentDiffActivePath) {
            showDiffContentEasterEgg(false);
        }

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
        // 更新状态提示为错误状态
        const hintBox = document.getElementById('diff-status-hint');
        const hintText = document.getElementById('diff-status-text');
        if (hintBox && hintText) {
            hintText.textContent = '加载失败';
            hintBox.style.background = 'rgba(239, 68, 68, 0.1)';
            hintBox.style.border = '1px solid rgba(239, 68, 68, 0.2)';
        }
    }
}

function resetDiffState() {
    try { diffAnalysisCache.clear(); } catch (_) { }
    try { diffFileCache.clear(); } catch (_) { }
    activeDiffItemEl = null;
    try { window.currentDiffText = null; } catch (_) { }
    try { window.currentDiffActivePath = null; } catch (_) { }

    // 重置历史提交模式相关状态（关键：切换项目时必须重置）
    currentCommitFrom = null;
    currentCommitTo = 'HEAD';
    selectedCommitFrom = null;
    selectedCommitTo = 'HEAD';
    commitHistoryData = [];
    commitModeFilesCache = null;
    userExplicitlySelectedTo = false;
    isEditingCommitRange = false;

    // 重置历史提交选择器 UI
    const commitFromText = document.getElementById('commitFromText');
    const commitToText = document.getElementById('commitToText');
    if (commitFromText) commitFromText.textContent = '选择起始提交...';
    if (commitToText) commitToText.textContent = 'HEAD (最新)';

    // 清空提交历史菜单
    const fromMenu = document.getElementById('commitFromMenu');
    const toMenu = document.getElementById('commitToMenu');
    if (fromMenu) fromMenu.innerHTML = '';
    if (toMenu) toMenu.innerHTML = '';

    const diffFileList = document.getElementById('diff-file-list');
    if (diffFileList) {
        diffFileList.innerHTML = '<div class="empty-state">请先在仪表盘或审查页面选择项目</div>';
    }
    const diffContentArea = document.getElementById('diff-content-area');
    if (diffContentArea) {
        diffContentArea.innerHTML = '<div class="empty-state">请选择左侧文件查看差异</div>';
    }
}

/**
 * 重置 diff 内容区域状态（用于模式切换时）
 * 只有当前有选中文件时才清空面板，避免打断正在播放的彩蛋动画
 * @param {string} mode - 目标模式
 * @returns {boolean} 是否需要重新显示彩蛋（true = 之前有选中文件，现在需要切换到彩蛋）
 */
function resetDiffContentArea(mode) {
    // 检查当前是否有选中的文件
    const hadActiveFile = !!(window.currentDiffActivePath || window.currentDiffText);

    // 清空当前 diff 数据
    window.currentDiffText = null;
    window.currentDiffActivePath = null;

    // 清除文件列表中的活动状态
    if (activeDiffItemEl) {
        activeDiffItemEl.classList.remove('active');
        activeDiffItemEl = null;
    }

    // 只有当之前有选中文件时，才需要清空右侧面板
    if (hadActiveFile) {
        const diffContentArea = document.getElementById('diff-content-area');
        if (diffContentArea) {
            // 直接清空，让后续的 showDiffContentEasterEgg 重新渲染
            diffContentArea.innerHTML = '';
        }
        console.log('[Diff] Content area reset for mode:', mode, '(had active file)');
    } else {
        console.log('[Diff] Mode switch to:', mode, '(keeping easter egg)');
    }

    return hadActiveFile;
}

function renderDiffFileList(files) {
    const diffFileList = document.getElementById('diff-file-list');
    if (!diffFileList) return;

    if (!files || files.length === 0) {
        diffFileList.innerHTML = '<div class="empty-state">无文件变更</div>';
        // 显示空状态彩蛋
        showDiffContentEasterEgg(true, window.currentDiffMode || 'working');
        return;
    }

    // Fast render via single innerHTML + event delegation
    const html = files.map(file => {
        const requestPath = typeof file === 'string' ? file : (file.path || 'Unknown File');
        const displayPath = (typeof file === 'object' && file.display_path) ? file.display_path : requestPath;
        const changeType = typeof file === 'object' ? file.change_type : 'modify';

        // 使用 Git 标准状态字母
        let icon = getIcon('file');
        let statusClass = 'status-modify';
        let statusLetter = 'M';

        if (changeType === 'add') {
            statusClass = 'status-add';
            statusLetter = 'A';
        } else if (changeType === 'delete') {
            statusClass = 'status-delete';
            statusLetter = 'D';
        } else if (changeType === 'rename') {
            statusClass = 'status-rename';
            statusLetter = 'R';
        }

        const fileName = displayPath.split('/').pop();
        const dirPath = displayPath.substring(0, displayPath.lastIndexOf('/'));

        const encodedPath = encodeURIComponent(requestPath);
        return `
            <div class="file-list-item ${statusClass}" data-path="${encodedPath}">
                <div class="file-item-row">
                    <span class="file-icon">${icon}</span>
                    <div class="file-info">
                        <div class="file-name" title="${escapeHtml(displayPath)}">${escapeHtml(fileName)}</div>
                        <div class="file-path" title="${escapeHtml(dirPath)}">${escapeHtml(dirPath)}</div>
                    </div>
                    <span class="file-status-badge ${statusClass}">${statusLetter}</span>
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
                let url = `/api/diff/file/${encodeURIComponent(filePath)}?project_root=${encodeURIComponent(window.currentProjectRoot)}&mode=${window.currentDiffMode}&_ts=${ts}`;
                if (window.currentDiffMode === 'commit' && typeof currentCommitFrom !== 'undefined') {
                    url += `&commit_from=${encodeURIComponent(currentCommitFrom)}`;
                    if (currentCommitTo) {
                        url += `&commit_to=${encodeURIComponent(currentCommitTo)}`;
                    }
                }
                const res = await fetchWithTimeout(url);
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

    // 性能保护：检查diff大小（行数和字符数）
    const lineCount = (diffText.match(/\n/g) || []).length;
    const charCount = diffText.length;
    const fileSizeKB = Math.round(charCount / 1024);

    // 阻止渲染：超过任一阈值
    if (lineCount > MAX_DIFF_LINES_BLOCK || charCount > MAX_DIFF_CHARS_BLOCK) {
        targetElement.innerHTML = `
            <div class="diff-size-warning" style="padding: 2rem; text-align: center; color: #dc2626;">
                <svg class="icon" style="width:48px;height:48px;margin-bottom:1rem;"><use href="#icon-alert-triangle"></use></svg>
                <h3>文件过大，无法显示</h3>
                <p>此差异包含 ${lineCount.toLocaleString()} 行，约 ${fileSizeKB.toLocaleString()} KB，超过了安全渲染限制。</p>
                <p style="color: var(--text-muted);">建议使用命令行工具（如 git diff）查看此文件的差异。</p>
                <button class="btn-secondary" style="margin-top: 1rem;" onclick="forceRenderLargeDiff()">
                    强制渲染（可能导致浏览器卡顿）
                </button>
            </div>
        `;
        // 保存当前diff数据以便强制渲染
        window._pendingLargeDiff = { diffText, outputFormat };
        return;
    }

    // 警告渲染：超过警告阈值但未达阻止阈值
    if (lineCount > MAX_DIFF_LINES_WARNING || charCount > MAX_DIFF_CHARS_WARNING) {
        const warningDiv = document.createElement('div');
        warningDiv.className = 'diff-size-warning';
        warningDiv.style.cssText = 'padding: 0.75rem 1rem; background: #fef3c7; border-bottom: 1px solid #fcd34d; color: #92400e; font-size: 0.85rem;';
        warningDiv.innerHTML = `⚠️ 此差异较大（${lineCount.toLocaleString()} 行，${fileSizeKB} KB），渲染可能较慢...`;
        targetElement.innerHTML = '';
        targetElement.appendChild(warningDiv);

        const diffContainer = document.createElement('div');
        targetElement.appendChild(diffContainer);

        // 延迟渲染，使用简化配置
        setTimeout(() => {
            const configuration = {
                drawFileList: false,
                fileListToggle: false,
                fileContentToggle: false,
                matching: 'none', // 禁用匹配以提高性能
                outputFormat: outputFormat,
                synchronisedScroll: false, // 禁用同步滚动以提高性能
                highlight: false, // 禁用高亮以提高性能
                renderNothingWhenEmpty: false,
            };
            try {
                const diff2htmlUi = new Diff2HtmlUI(diffContainer, diffText, configuration);
                diff2htmlUi.draw();
            } catch (e) {
                console.error('Render large diff failed:', e);
                diffContainer.innerHTML = '<div style="padding:1rem;color:red;">渲染失败，文件可能过大</div>';
            }
        }, 100);
        return;
    }

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

// 强制渲染大型diff（用户明确选择）
function forceRenderLargeDiff() {
    if (!window._pendingLargeDiff) return;

    const { diffText, outputFormat } = window._pendingLargeDiff;
    const targetElement = document.getElementById('diff-ui-container');
    if (!targetElement) return;

    targetElement.innerHTML = '<div style="padding:1rem;color:var(--text-muted);">正在渲染大型文件，请稍候...</div>';

    // 使用 requestIdleCallback 或 setTimeout 延迟渲染，避免阻塞UI
    const doRender = () => {
        try {
            const configuration = {
                drawFileList: false,
                fileListToggle: false,
                fileContentToggle: false,
                matching: 'none',
                outputFormat: outputFormat,
                synchronisedScroll: false,
                highlight: false, // 禁用高亮以提高性能
                renderNothingWhenEmpty: false,
            };

            targetElement.innerHTML = '';
            const diff2htmlUi = new Diff2HtmlUI(targetElement, diffText, configuration);
            diff2htmlUi.draw();
            window._pendingLargeDiff = null;
        } catch (e) {
            console.error('Force render failed:', e);
            targetElement.innerHTML = '<div style="padding:1rem;color:red;">渲染失败: ' + e.message + '</div>';
        }
    };

    // 使用 requestIdleCallback 如果可用，否则用 setTimeout
    if (window.requestIdleCallback) {
        requestIdleCallback(doRender, { timeout: 2000 });
    } else {
        setTimeout(doRender, 100);
    }
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

// 初始化diff模式选择器
let diffModeDropdownInitialized = false;
function initDiffModeDropdown() {
    // 防止重复初始化
    if (diffModeDropdownInitialized) return;

    const trigger = document.getElementById('diffModeDropdownTrigger');
    const menu = document.getElementById('diffModeDropdownMenu');
    const dropdown = document.getElementById('diffModeDropdown');

    if (!trigger || !menu || !dropdown) {
        console.log('[Diff] Dropdown elements not found, skipping init');
        return;
    }

    diffModeDropdownInitialized = true;
    console.log('[Diff] Initializing diff mode dropdown');

    // 点击触发器切换菜单
    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.classList.toggle('open');
    });

    // 点击菜单项
    menu.addEventListener('click', (e) => {
        const item = e.target.closest('.dropdown-item');
        if (!item) return;

        const mode = item.getAttribute('data-mode');
        selectDiffMode(mode);
        dropdown.classList.remove('open');
    });

    // 点击外部关闭
    document.addEventListener('click', (e) => {
        if (!dropdown.contains(e.target)) {
            dropdown.classList.remove('open');
        }
    });
}

// 选择diff模式
function selectDiffMode(mode) {
    if (mode === 'commit' && typeof switchPage === 'function') {
        switchPage('diff');
    }

    manualDiffMode = mode;
    window.currentDiffMode = manualDiffMode;

    // 更新显示文本
    const modeNames = {
        'auto': '自动检测',
        'working': '工作区',
        'staged': '暂存区',
        'pr': 'PR模式',
        'commit': '历史提交'
    };

    const text = document.getElementById('selectedDiffModeText');
    if (text) {
        text.textContent = modeNames[mode] || '自动检测';
    }

    // 处理commit模式的面板显示
    const commitPanel = document.getElementById('commitSelectorPanel');
    const diffFileList = document.getElementById('diff-file-list');
    const diffContentArea = document.getElementById('diff-content-area');

    if (commitPanel) {
        if (mode === 'commit') {
            commitPanel.style.display = 'block';

            // [模式切换] 重置右侧面板状态（只有之前有选中文件时才清空）
            const needShowEasterEgg = resetDiffContentArea(mode);

            // 如果有缓存数据，恢复显示而不是清空
            if (commitModeFilesCache && commitModeFilesCache.files && commitModeFilesCache.files.length > 0) {
                updateDiffStatusHint('commit', commitModeFilesCache.files.length);
                renderDiffFileList(commitModeFilesCache.files, {
                    isCommitMode: true,
                    diffText: commitModeFilesCache.diffText
                });
                // 只有之前有选中文件时才需要重新显示彩蛋
                if (needShowEasterEgg) {
                    showDiffContentEasterEgg('default', 'commit');
                }
            } else {
                // 没有缓存，显示提示并更新状态提示
                updateDiffStatusHint('commit', 0);
                if (diffFileList) diffFileList.innerHTML = '<div class="empty-state">请选择提交范围后点击"查看"</div>';
                // 切换到 commit 模式的特殊彩蛋需要显示（无论之前是什么状态）
                showDiffContentEasterEgg('waiting-commit', 'commit');
            }
            // 立即更新主界面徽章
            updateReviewModeBadge('commit');
            loadCommitHistory();  // 自动加载commit历史
            return; // commit模式不自动刷新,需要用户选择后手动加载
        } else {
            commitPanel.style.display = 'none';
            // 切换离开commit模式时，清除缓存和状态
            commitModeFilesCache = null;
            selectedCommitFrom = null;
            selectedCommitTo = 'HEAD';
            currentCommitFrom = null;  // 关键：清除发送到 API 的 commit 变量
            currentCommitTo = 'HEAD';
            userExplicitlySelectedTo = false;
        }
    }

    // [模式切换] 重置右侧面板状态（只有之前有选中文件时才清空）
    const needShowEasterEgg = resetDiffContentArea(mode);

    // 立即显示加载状态，防止残留旧消息
    const hintBox = document.getElementById('diff-status-hint');
    const hintText = document.getElementById('diff-status-text');
    if (hintBox && hintText) {
        hintText.textContent = '正在加载...';
        hintBox.style.background = 'rgba(156, 163, 175, 0.1)';
        hintBox.style.border = '1px solid rgba(156, 163, 175, 0.2)';
    }

    // 只有之前有选中文件时才需要重新显示彩蛋
    if (needShowEasterEgg) {
        showDiffContentEasterEgg('default', mode === 'auto' ? 'working' : mode);
    }

    // 刷新diff分析
    refreshDiffAnalysis({ force: true, reload_active: false });
}

// ========== Commit模式相关函数 ==========

// 切换Commit下拉菜单显示
function toggleCommitDropdown(dropdownId) {
    const dropdown = document.getElementById(dropdownId);
    if (!dropdown) return;

    // 阻止事件冒泡, 防止触发全局关闭
    if (window.event) window.event.stopPropagation();

    // 关闭其他打开的菜单
    document.querySelectorAll('.custom-dropdown.open').forEach(el => {
        if (el.id !== dropdownId) el.classList.remove('open');
    });

    dropdown.classList.toggle('open');
}

// 全局点击事件监听：点击外部关闭下拉菜单
document.addEventListener('click', function (event) {
    if (!event.target.closest('.custom-dropdown')) {
        document.querySelectorAll('.custom-dropdown.open').forEach(el => {
            el.classList.remove('open');
        });
    }
});

// 展开/收起Commit消息
function toggleCommitItem(event, btn) {
    event.stopPropagation(); // 阻止触发选择
    const item = btn.closest('.commit-item');
    if (item) {
        item.classList.toggle('expanded');
    }
}

// 渲染Commit菜单项 (通用)
function renderCommitHtml(commit, clickHandlerName) {
    const shortHash = commit.hash?.substring(0, 7) || '';
    const msg = (commit.message || '').trim();
    // 只取第一行显示在标题行，或者如果展开则显示全部
    const firstLine = msg.split('\n')[0];
    const dateStr = commit.date ? new Date(commit.date).toLocaleDateString() : '';

    // 判断是否有更多内容（多行或长度超过限制）
    const isLong = msg.length > 50 || msg.includes('\n');
    const expandBtn = isLong
        ? `<div class="commit-expand-btn" onclick="toggleCommitItem(event, this)" title="展开完整消息">
             <svg class="icon" style="width:12px;height:12px;"><use href="#icon-chevron-down"></use></svg>
           </div>`
        : '';

    return `
        <div class="commit-item" data-hash="${commit.hash}">
            <div class="commit-content-clickable" onclick="${clickHandlerName}('${commit.hash}')">
                <div class="commit-info-row">
                    <span class="commit-hash">${shortHash}</span>
                    <span class="commit-date">${dateStr}</span>
                </div>
            </div>
            <div class="commit-msg-row">
                 <div class="commit-msg" onclick="${clickHandlerName}('${commit.hash}')" title="${escapeHtml(msg)}">${escapeHtml(msg)}</div>
                 ${expandBtn}
            </div>
        </div>
    `;
}

// 加载commit历史
async function loadCommitHistory() {
    const fromMenu = document.getElementById('commitFromMenu');
    const toMenu = document.getElementById('commitToMenu');
    const fromText = document.getElementById('commitFromText');
    const toText = document.getElementById('commitToText');

    if (!fromMenu || !toMenu) return;

    // 显示加载状态
    fromText.textContent = '加载中...';

    try {
        const res = await fetch('/api/git/commits', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_root: window.currentProjectRoot,
                limit: 50
            })
        });
        if (!res.ok) throw new Error('Failed to load commits');

        const data = await res.json();
        commitHistoryData = data.commits || [];

        // 渲染起始菜单
        let fromHtml = '';
        commitHistoryData.forEach(commit => {
            fromHtml += renderCommitHtml(commit, 'onSelectCommitFrom');
        });
        fromMenu.innerHTML = fromHtml;
        fromText.textContent = '选择起始提交...';

        // 渲染结束菜单 (默认包含HEAD)
        renderToMenu();

    } catch (e) {
        console.error('Failed to load commit history:', e);
        fromText.textContent = '加载失败';
    }
}

// 渲染结束菜单 (基于起始commit过滤)
function renderToMenu() {
    const toMenu = document.getElementById('commitToMenu');
    const toText = document.getElementById('commitToText');
    if (!toMenu) return;

    let toHtml = `
        <div class="commit-item" onclick="onSelectCommitTo('HEAD')">
            <div class="commit-content-clickable">
                <div class="commit-info-row">
                    <span class="commit-hash">HEAD</span>
                    <span class="commit-tag">当前工作区</span>
                </div>
            </div>
             <div class="commit-msg-row">
                <div class="commit-msg">最新状态</div>
             </div>
        </div>
    `;

    // 如果选择了起始commit，只显示它之前的commit (索引更小)
    let startIndex = -1;
    if (selectedCommitFrom) {
        startIndex = commitHistoryData.findIndex(c => c.hash === selectedCommitFrom);
    }

    const limitIndex = startIndex === -1 ? commitHistoryData.length : startIndex;

    for (let i = 0; i < limitIndex; i++) {
        const commit = commitHistoryData[i];
        toHtml += renderCommitHtml(commit, 'onSelectCommitTo');
    }

    toMenu.innerHTML = toHtml;
}

// 选择起始Commit
function onSelectCommitFrom(hash) {
    selectedCommitFrom = hash;
    const commit = commitHistoryData.find(c => c.hash === hash);
    const textEl = document.getElementById('commitFromText');
    if (textEl && commit) {
        textEl.textContent = `${commit.hash.substring(0, 7)} - ${commit.message.split('\n')[0]}`;
    }

    // 关闭菜单
    document.getElementById('commitFromDropdown').classList.remove('open');

    // 重置并更新结束菜单
    // 如果当前的结束commit比起始commit更早（在列表中索引更大），则需重置
    // 简单起见，每次改变起始，结束若不合法则重置为HEAD
    const fromIndex = commitHistoryData.findIndex(c => c.hash === hash);
    const toIndex = selectedCommitTo === 'HEAD' ? -1 : commitHistoryData.findIndex(c => c.hash === selectedCommitTo);

    if (toIndex > fromIndex && toIndex !== -1) {
        // reset to HEAD
        onSelectCommitTo('HEAD');
    }

    renderToMenu();

    // 智能自动加载：
    // - 如果用户已经明确选择了结束提交，且不在编辑模式，则自动加载
    // - 编辑模式下需要用户点击"查看变更"按钮
    if (userExplicitlySelectedTo && !isEditingCommitRange) {
        loadCommitRangeDiff();
    }
}

// 选择结束Commit
function onSelectCommitTo(hash) {
    selectedCommitTo = hash;
    const textEl = document.getElementById('commitToText');
    if (textEl) {
        if (hash === 'HEAD') {
            textEl.textContent = 'HEAD (最新)';
        } else {
            const commit = commitHistoryData.find(c => c.hash === hash);
            if (commit) {
                textEl.textContent = `${commit.hash.substring(0, 7)} - ${commit.message.split('\n')[0]}`;
            }
        }
    }
    document.getElementById('commitToDropdown').classList.remove('open');

    // 标记用户已明确选择了结束提交
    userExplicitlySelectedTo = true;

    // 智能自动加载：
    // - 如果不在编辑模式（首次选择），选择To后自动加载
    // - 如果在编辑模式，需要用户点击"查看变更"按钮
    if (selectedCommitFrom && !isEditingCommitRange) {
        loadCommitRangeDiff();
    }
}

// 加载commit范围的diff
async function loadCommitRangeDiff() {
    if (!selectedCommitFrom) {
        alert('请选择起始Commit');
        return;
    }

    const commitFrom = selectedCommitFrom;
    const commitTo = selectedCommitTo || 'HEAD';

    const fileListEl = document.getElementById('diff-file-list');
    const contentArea = document.getElementById('diff-content-area');

    if (fileListEl) fileListEl.innerHTML = '<div class="empty-state">加载中...</div>';
    // 使用彩蛋显示加载状态，而不是简单的"加载中"文本
    showDiffContentEasterEgg('commit-selected', 'commit', { from: commitFrom, to: commitTo });

    try {
        const res = await fetch('/api/diff/commit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_root: window.currentProjectRoot,
                commit_from: commitFrom,
                commit_to: commitTo
            })
        });

        const data = await res.json();

        if (!data.success) {
            fileListEl.innerHTML = `<div class="empty-state" style="color:#ef4444;">${escapeHtml(data.error || '加载失败')}</div>`;
            updateDiffStatusHint('commit', 0);
            return;
        }

        if (!data.files || data.files.length === 0) {
            fileListEl.innerHTML = '<div class="empty-state">该范围内没有文件变更</div>';
            contentArea.innerHTML = '<div class="empty-state">没有变更内容</div>';
            updateDiffStatusHint('commit', 0);
            return;
        }

        // 渲染文件列表
        const filesForRender = data.files.map(f => ({
            path: f.path || f.target_file,
            language: 'unknown',
            // 优先使用后端返回的 change_type，否则使用行数判断作为后备
            change_type: f.change_type || (
                f.added_lines > 0 && f.removed_lines === 0 ? 'add' :
                    f.removed_lines > 0 && f.added_lines === 0 ? 'delete' : 'modify'
            ),
            lines_added: f.added_lines || 0,
            lines_removed: f.removed_lines || 0,
        }));

        // 保存commit范围到全局状态(供审查时使用)
        currentCommitFrom = commitFrom;
        currentCommitTo = commitTo;

        // 缓存commit模式的文件列表，以便页面切换后恢复
        commitModeFilesCache = {
            files: filesForRender,
            diffText: data.diff_text,
            commitFrom: commitFrom,
            commitTo: commitTo
        };

        updateDiffStatusHint('commit', filesForRender.length);
        renderDiffFileList(filesForRender, { isCommitMode: true, diffText: data.diff_text });

        showDiffContentEasterEgg('commit-selected', 'commit', { from: commitFrom, to: commitTo });

        // 加载成功后折叠选择器，更新摘要
        collapseCommitSelector(commitFrom, commitTo);

    } catch (e) {
        console.error('Failed to load commit diff:', e);
        fileListEl.innerHTML = `<div class="empty-state" style="color:#ef4444;">请求失败: ${e.message}</div>`;
    }
}

// 简单的HTML转义
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// 折叠提交选择器，显示摘要
function collapseCommitSelector(fromHash, toHash) {
    const card = document.getElementById('commitRangeCard');
    const summaryFrom = document.getElementById('summaryFromHash');
    const summaryTo = document.getElementById('summaryToHash');

    if (card) {
        // 更新摘要显示
        if (summaryFrom) {
            summaryFrom.textContent = fromHash ? fromHash.substring(0, 7) : '---';
        }
        if (summaryTo) {
            summaryTo.textContent = toHash === 'HEAD' ? 'HEAD' : (toHash ? toHash.substring(0, 7) : 'HEAD');
        }

        // 添加折叠效果
        card.classList.add('collapsed');

        // 清除编辑状态
        isEditingCommitRange = false;
    }
}

// 展开提交选择器
function expandCommitSelector() {
    const card = document.getElementById('commitRangeCard');
    if (card) {
        card.classList.remove('collapsed');

        // 设置编辑状态，防止自动折叠
        isEditingCommitRange = true;

        // 重置选择状态，要求用户重新选择两个提交
        userExplicitlySelectedTo = false;
    }
}

// Export to window
window.refreshDiffAnalysis = refreshDiffAnalysis;
window.renderDiffFileList = renderDiffFileList;
window.loadFileDiff = loadFileDiff;
window.renderDiff2Html = renderDiff2Html;
window.toggleDiffView = toggleDiffView;
window.resetDiffState = resetDiffState;
window.initDiffModeDropdown = initDiffModeDropdown;
window.initHeaderModeDropdown = initHeaderModeDropdown;
window.selectDiffMode = selectDiffMode;
window.loadCommitHistory = loadCommitHistory;
window.loadCommitRangeDiff = loadCommitRangeDiff;
window.onCommitFromChange = onCommitFromChange;
window.getCurrentDiffSettings = getCurrentDiffSettings;
window.collapseCommitSelector = collapseCommitSelector;
window.expandCommitSelector = expandCommitSelector;
window.showDiffContentEasterEgg = showDiffContentEasterEgg;
