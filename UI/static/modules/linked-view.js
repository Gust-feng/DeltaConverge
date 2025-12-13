/**
 * linked-view.js - 关联视图切换模块
 * 在审查报告面板中切换 "审查报告" 和 "代码变更" 视图
 */

// 当前视图模式
window.currentReportViewMode = 'report';

window.reportDiffUnits = null;
window.reportStaticScanLinked = null;
window.reportDiffSelectedFile = null;
window.reportDiffFiles = null;

function normalizeReportPath(p) {
    let s = String(p || '').trim();
    if (!s) return '';
    s = s.replace(/\\/g, '/');
    if (s.startsWith('a/')) s = s.slice(2);
    else if (s.startsWith('b/')) s = s.slice(2);
    if (s.startsWith('./')) s = s.slice(2);
    if (s.startsWith('/')) s = s.slice(1);
    return s;
}

function normalizeSeverityValue(sev) {
    const s = String(sev || '').toLowerCase();
    if (s === 'error' || s === 'fatal') return 'error';
    if (s === 'warning' || s === 'warn') return 'warning';
    if (s === 'info' || s === 'information') return 'info';
    return 'info';
}

function summarizeIssues(issues) {
    const c = { error: 0, warning: 0, info: 0 };
    if (!Array.isArray(issues)) return c;
    for (const it of issues) {
        const sev = normalizeSeverityValue(it && it.severity);
        if (sev === 'error') c.error += 1;
        else if (sev === 'warning') c.warning += 1;
        else c.info += 1;
    }
    return c;
}

function issueSummaryClass(counts) {
    if (!counts) return '';
    if (counts.error > 0) return 'has-error';
    if (counts.warning > 0) return 'has-warning';
    if (counts.info > 0) return 'has-info';
    return 'clean';
}

function renderSeverityBadges(counts, emptyText = '') {
    const badges = [];
    if (counts && counts.error) badges.push(`<span class="severity-badge error">ERROR ${escapeHtml(String(counts.error))}</span>`);
    if (counts && counts.warning) badges.push(`<span class="severity-badge warning">WARN ${escapeHtml(String(counts.warning))}</span>`);
    if (counts && counts.info) badges.push(`<span class="severity-badge info">INFO ${escapeHtml(String(counts.info))}</span>`);
    if (!badges.length && emptyText) {
        badges.push(`<span class="diff-unit-status clean">${escapeHtml(String(emptyText))}</span>`);
    }
    return badges.join('');
}

function renderDiffLines(diffText) {
    const text = String(diffText || '').replace(/\r\n/g, '\n');
    const lines = text.split('\n');
    if (lines.length && lines[lines.length - 1] === '') {
        lines.pop();
    }
    return lines.map(line => {
        const first = line ? line[0] : '';
        let cls = 'diff-line';
        if (first === '+') cls += ' diff-add';
        else if (first === '-') cls += ' diff-del';
        else cls += ' diff-ctx';
        return `<span class="${cls}">${escapeHtml(line)}</span>`;
    }).join('');
}

function getFileIssueSummary(filePath) {
    const counts = { error: 0, warning: 0, info: 0 };
    const linked = window.reportStaticScanLinked || {};
    const unitIssues = linked.unit_issues || null;
    const units = Array.isArray(window.reportDiffUnits) ? window.reportDiffUnits : [];
    if (!unitIssues || !units.length) return counts;
    const targetKey = normalizeReportPath(filePath);
    for (const u of units) {
        if (normalizeReportPath(u.file_path) !== targetKey) continue;
        const unitId = u.unit_id || u.id;
        if (!unitId) continue;
        const c = summarizeIssues(unitIssues[unitId]);
        counts.error += c.error;
        counts.warning += c.warning;
        counts.info += c.info;
    }
    return counts;
}

async function refreshReportDiffLinked() {
    const sid = window.currentSessionId;
    if (!sid) return;
    try {
        const resp = await fetch(`/api/static-scan/linked?session_id=${encodeURIComponent(sid)}`);
        if (resp.ok) {
            window.reportStaticScanLinked = await resp.json();
            if (window.reportStaticScanLinked && Array.isArray(window.reportStaticScanLinked.diff_units)) {
                window.reportDiffUnits = window.reportStaticScanLinked.diff_units;
            }
            if (window.currentReportViewMode === 'diff' && Array.isArray(window.reportDiffFiles)) {
                try { renderReportDiffFileList(window.reportDiffFiles); } catch (e) { }
            }
            if (window.currentReportViewMode === 'diff' && window.reportDiffSelectedFile) {
                await loadReportFileDiff(window.reportDiffSelectedFile);
            }
        }
    } catch (e) {
    }
}

/**
 * 切换报告视图模式
 * @param {string} mode - 'report' 或 'diff'
 */
function switchReportView(mode) {
    const reportContainer = document.getElementById('reportContainer');
    const diffViewContainer = document.getElementById('diffViewContainer');
    const viewToggleReport = document.getElementById('viewToggleReport');
    const viewToggleDiff = document.getElementById('viewToggleDiff');
    const rightPanel = document.getElementById('rightPanel');
    const reportPanel = document.getElementById('reportPanel');

    if (!reportContainer || !diffViewContainer) {
        console.warn('[LinkedView] 容器元素未找到');
        return;
    }

    window.currentReportViewMode = mode;

    if (mode === 'report') {
        viewToggleReport?.classList.add('active');
        viewToggleDiff?.classList.remove('active');

        // 播放渐出动画
        if (diffViewContainer.style.display !== 'none') {
            diffViewContainer.classList.add('exiting');
            // 等待动画完成后再切换显示
            setTimeout(() => {
                diffViewContainer.classList.remove('exiting');
                reportContainer.style.display = '';
                diffViewContainer.style.display = 'none';
            }, 280);
        } else {
            reportContainer.style.display = '';
            diffViewContainer.style.display = 'none';
        }

        // 展开右侧面板（先恢复宽度，再渐显内容）
        if (rightPanel) {
            rightPanel.style.overflow = 'hidden';
            rightPanel.style.width = '';  // 恢复默认宽度
            // 延迟显示内容，等宽度动画完成
            setTimeout(() => {
                rightPanel.style.opacity = '';
                rightPanel.style.overflow = '';
            }, 300);
        }
        // 恢复报告面板宽度
        if (reportPanel) {
            reportPanel.style.width = '';  // 恢复默认65%
        }

    } else if (mode === 'diff') {
        reportContainer.style.display = 'none';
        diffViewContainer.style.display = '';
        diffViewContainer.classList.add('entering');
        setTimeout(() => {
            diffViewContainer.classList.remove('entering');
        }, 350);

        viewToggleReport?.classList.remove('active');
        viewToggleDiff?.classList.add('active');

        // 收起右侧面板（先淡出内容，再收缩宽度，避免文字挤压）
        if (rightPanel) {
            rightPanel.style.opacity = '0';
            rightPanel.style.overflow = 'hidden';
            // 延迟收缩宽度，等淡出动画完成
            setTimeout(() => {
                rightPanel.style.width = '0';
            }, 200);
        }
        // 扩展报告面板宽度
        if (reportPanel) {
            reportPanel.style.width = '100%';
        }

        // 加载diff文件列表
        loadReportDiffFiles();
    }

    console.log(`[LinkedView] 切换到 ${mode} 视图`);
}

/**
 * 加载Diff文件列表到报告面板
 * - 历史会话: 从session.diff_files读取
 * - 实时审查: 使用实时API获取
 */
async function loadReportDiffFiles() {
    const fileListEl = document.getElementById('reportDiffFileList');
    if (!fileListEl) return;

    fileListEl.innerHTML = '<div class="empty-state">加载中...</div>';

    const currentSessionId = window.currentSessionId;

    if (currentSessionId) {
        try {
            const sessionRes = await fetch(`/api/sessions/${encodeURIComponent(currentSessionId)}`);
            if (sessionRes.ok) {
                const sessionData = await sessionRes.json();
                const diffFiles = sessionData.diff_files || [];
                const diffUnits = sessionData.diff_units || [];
                let linked = sessionData.static_scan_linked || null;
                try {
                    if (linked && typeof linked === 'object' && Object.keys(linked).length === 0) {
                        linked = null;
                    }
                } catch (_) { }

                if (diffFiles.length > 0) {
                    window.reportDiffMode = 'snapshot';
                    window.reportDiffProjectRoot = sessionData.metadata?.project_root || window.currentProjectRoot;
                    if (linked && Array.isArray(linked.diff_units) && linked.diff_units.length) {
                        window.reportDiffUnits = linked.diff_units;
                    } else {
                        window.reportDiffUnits = Array.isArray(diffUnits) ? diffUnits : [];
                    }
                    window.reportStaticScanLinked = linked;
                    window.reportDiffFiles = diffFiles;
                    renderReportDiffFileList(diffFiles);
                    console.log('[LinkedView] 使用会话快照中的文件列表');
                    return;
                }

                if (sessionData.metadata?.project_root) {
                    window.reportDiffProjectRoot = sessionData.metadata.project_root;
                }
            }
        } catch (e) {
            console.warn('[LinkedView] 读取会话数据失败:', e);
        }
    }

    // 回退到实时获取（新审查或会话中没有快照）
    const projectRoot = window.reportDiffProjectRoot || window.currentProjectRoot;

    if (!projectRoot) {
        fileListEl.innerHTML = '<div class="empty-state">请先选择项目</div>';
        return;
    }

    try {
        // 获取diff模式
        let reqMode = 'working';
        try {
            const sres = await fetch('/api/diff/status?project_root=' + encodeURIComponent(projectRoot));
            if (sres && sres.ok) {
                const st = await sres.json();
                if (st && st.has_staged_changes) reqMode = 'staged';
                else if (st && st.has_working_changes) reqMode = 'working';
            }
        } catch (_) { }

        // 获取文件列表
        const res = await fetch('/api/diff/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: projectRoot, mode: reqMode })
        });

        if (!res.ok) throw new Error('HTTP ' + res.status);

        const data = await res.json();

        // 检查错误
        let errorMsg = null;
        if (data && data.status && data.status.error) {
            errorMsg = data.status.error;
        } else if (data && data.summary && data.summary.error) {
            errorMsg = data.summary.error;
        }

        if (errorMsg) {
            if (errorMsg.indexOf('not a git repository') >= 0) {
                fileListEl.innerHTML = '<div class="empty-state">此目录不是 Git 仓库</div>';
            } else if (errorMsg.indexOf('No changes detected') >= 0) {
                fileListEl.innerHTML = '<div class="empty-state">无文件变更</div>';
            } else {
                fileListEl.innerHTML = '<div class="empty-state">' + escapeHtml(errorMsg) + '</div>';
            }
            return;
        }

        window.reportDiffMode = reqMode;
        window.reportDiffProjectRoot = projectRoot;
        const files = (data && data.files) ? data.files : [];
        window.reportDiffFiles = files;
        renderReportDiffFileList(files);
        console.log('[LinkedView] 使用实时API获取的文件列表');

    } catch (e) {
        console.error('[LinkedView] 加载文件列表失败:', e);
        fileListEl.innerHTML = '<div class="empty-state" style="color:red;">加载失败: ' + escapeHtml(e.message) + '</div>';
    }
}

/**
 * 渲染Diff文件列表
 */
function renderReportDiffFileList(files) {
    const fileListEl = document.getElementById('reportDiffFileList');
    if (!fileListEl) return;

    if (!files || files.length === 0) {
        fileListEl.innerHTML = '<div class="empty-state">无文件变更</div>';
        return;
    }

    fileListEl.innerHTML = '';
    files.forEach((file, index) => {
        const div = document.createElement('div');
        div.className = 'file-list-item';
        div.style.animationDelay = `${index * 40}ms`;

        const requestPath = typeof file === 'string' ? file : (file.path || "Unknown File");
        const displayPath = (typeof file === 'object' && file.display_path) ? file.display_path : requestPath;
        const changeType = typeof file === 'object' ? file.change_type : "modify";

        let icon = typeof getIcon === 'function' ? getIcon('file') : '📄';
        let statusClass = 'status-modify';
        if (changeType === 'add') {
            icon = typeof getIcon === 'function' ? getIcon('plus') : '➕';
            statusClass = 'status-add';
        } else if (changeType === 'delete') {
            icon = typeof getIcon === 'function' ? getIcon('trash') : '🗑️';
            statusClass = 'status-delete';
        }

        const fileName = displayPath.split('/').pop();
        const dirPath = displayPath.substring(0, displayPath.lastIndexOf('/'));

        const linked = window.reportStaticScanLinked || {};
        const hasMapping = !!linked.unit_issues;
        const fileCounts = hasMapping ? getFileIssueSummary(requestPath) : { error: 0, warning: 0, info: 0 };
        const fileClass = hasMapping ? issueSummaryClass(fileCounts) : '';
        if (fileClass && fileClass !== 'clean') {
            div.classList.add(fileClass);
        }
        let badgeHtml = '';
        if (hasMapping) {
            const compact = [];
            if (fileCounts.error) compact.push(`<span class="severity-badge error">E${escapeHtml(String(fileCounts.error))}</span>`);
            if (fileCounts.warning) compact.push(`<span class="severity-badge warning">W${escapeHtml(String(fileCounts.warning))}</span>`);
            if (fileCounts.info) compact.push(`<span class="severity-badge info">I${escapeHtml(String(fileCounts.info))}</span>`);
            badgeHtml = compact.join('');
        }

        div.innerHTML = `
            <div class="file-item-row">
                <span class="file-icon ${statusClass}">${icon}</span>
                <div class="file-info">
                    <div class="file-name" title="${escapeHtml(displayPath)}">${escapeHtml(fileName)}</div>
                    <div class="file-path" title="${escapeHtml(dirPath)}">${escapeHtml(dirPath)}</div>
                </div>
                <div class="file-issue-badges">${badgeHtml}</div>
            </div>
        `;

        div.dataset.path = requestPath;
        div.onclick = () => loadReportFileDiff(requestPath);
        fileListEl.appendChild(div);
    });
}

/**
 * 加载单个文件的Diff内容
 */
async function loadReportFileDiff(filePath) {
    const diffContentEl = document.getElementById('reportDiffContent');
    const fileListEl = document.getElementById('reportDiffFileList');
    if (!diffContentEl) return;

    window.reportDiffSelectedFile = filePath;

    // 使用快照中保存的project_root，回退到当前项目
    const projectRoot = window.reportDiffProjectRoot || window.currentProjectRoot;

    if (!projectRoot) {
        diffContentEl.innerHTML = '<div style="padding:1rem;color:red;">请先选择项目</div>';
        return;
    }

    diffContentEl.innerHTML = '<div class="empty-state">加载中...</div>';

    // 高亮当前选中项
    if (fileListEl) {
        const items = fileListEl.querySelectorAll('.file-list-item');
        items.forEach(i => {
            if (i.dataset.path === filePath) i.classList.add('active');
            else i.classList.remove('active');
        });
    }

    try {
        const units = Array.isArray(window.reportDiffUnits) ? window.reportDiffUnits : [];
        const targetKey = normalizeReportPath(filePath);
        const fileUnits = units.filter(u => normalizeReportPath(u.file_path) === targetKey);

        if (fileUnits.length > 0) {
            fileUnits.sort((a, b) => {
                const ra = a.hunk_range || {};
                const rb = b.hunk_range || {};
                const sa = Number(ra.new_start || 0);
                const sb = Number(rb.new_start || 0);
                return sa - sb;
            });

            if ((!window.reportStaticScanLinked || !window.reportStaticScanLinked.unit_issues) && window.currentSessionId) {
                try {
                    const linkResp = await fetch(`/api/static-scan/linked?session_id=${encodeURIComponent(window.currentSessionId)}`);
                    if (linkResp.ok) {
                        window.reportStaticScanLinked = await linkResp.json();
                        if (window.reportStaticScanLinked && Array.isArray(window.reportStaticScanLinked.diff_units)) {
                            window.reportDiffUnits = window.reportStaticScanLinked.diff_units;
                        }
                    }
                } catch (_) { }
            }

            const linked = window.reportStaticScanLinked || {};
            const unitIssues = linked.unit_issues || {};

            const renderIssueInline = (issue) => {
                const severity = normalizeSeverityValue(issue.severity);
                const line = issue.line || issue.start_line || '-';
                const column = issue.column || '-';
                const message = issue.message || 'No description';
                const ruleId = issue.rule_id || issue.rule || '';
                const scanner = issue.scanner || '';
                return `
                    <div class="issue-card severity-${escapeHtml(severity)}">
                        <div class="issue-header">
                            <span class="severity-badge ${escapeHtml(severity)}">${escapeHtml(severity)}</span>
                            <span class="issue-location">行 ${escapeHtml(String(line))}${column !== '-' ? `:${escapeHtml(String(column))}` : ''}</span>
                            ${ruleId ? `<span class="issue-rule" title="${escapeHtml(String(ruleId))}">${escapeHtml(String(ruleId))}</span>` : ''}
                        </div>
                        <div class="issue-message">${escapeHtml(String(message))}</div>
                        ${scanner ? `<div class="issue-scanner">via ${escapeHtml(String(scanner))}</div>` : ''}
                    </div>
                `;
            };

            const renderUnitBlock = (u) => {
                const unitId = u.unit_id || u.id || '';
                const hr = u.hunk_range || {};
                const start = Number(hr.new_start || 0);
                const len = Number(hr.new_lines || 0);
                const end = start > 0 ? (start + Math.max(len, 1) - 1) : start;
                const diffText = u.unified_diff_with_lines || u.unified_diff || '';

                const issues = Array.isArray(unitIssues[unitId]) ? unitIssues[unitId] : [];
                const counts = summarizeIssues(issues);
                const unitClass = (linked && linked.unit_issues) ? issueSummaryClass(counts) : 'waiting';
                const metaBadges = (linked && linked.unit_issues)
                    ? renderSeverityBadges(counts, 'CLEAN')
                    : `<span class="diff-unit-status waiting">SCANNING</span>`;
                let issuesHtml = '';
                if (!linked || !linked.unit_issues) {
                    issuesHtml = `<div class="diff-unit-issues-empty">静态分析：等待扫描完成</div>`;
                } else if (issues.length) {
                    issuesHtml = issues.slice(0, 50).map(renderIssueInline).join('');
                } else {
                    issuesHtml = `<div class="diff-unit-issues-empty">静态分析：未发现命中问题</div>`;
                }

                return `
                    <div class="diff-unit ${escapeHtml(String(unitClass))}" data-unit-id="${escapeHtml(String(unitId))}">
                        <div class="diff-unit-meta">
                            <span class="diff-unit-range">L${escapeHtml(String(start))}-${escapeHtml(String(end))}</span>
                            <div class="diff-unit-badges">${metaBadges}</div>
                        </div>
                        <pre class="diff-unit-code"><code>${renderDiffLines(diffText)}</code></pre>
                        <div class="diff-unit-issues">
                            ${issuesHtml}
                        </div>
                    </div>
                `;
            };

            diffContentEl.innerHTML = `
                <div class="diff-header" style="padding: 1rem; border-bottom: 1px solid var(--border);">
                    <h3 title="${escapeHtml(filePath)}" style="margin: 0; font-size: 0.95rem;">${escapeHtml(filePath)}</h3>
                </div>
                <div class="diff-units-container">
                    ${fileUnits.map(renderUnitBlock).join('')}
                </div>
            `;
            return;
        }

        const mode = window.reportDiffMode === 'snapshot' ? 'working' : (window.reportDiffMode || 'working');
        const res = await fetch(`/api/diff/file/${encodeURIComponent(filePath)}?project_root=${encodeURIComponent(projectRoot)}&mode=${mode}`);

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();

        if (data.error) {
            diffContentEl.innerHTML = `<div style="padding:1rem;color:red;">${escapeHtml(data.error)}</div>`;
            return;
        }

        const diffText = data.diff_text || data.diff_content || "";

        if (window.Diff2HtmlUI && diffText.trim()) {
            diffContentEl.innerHTML = `
                <div class="diff-header" style="padding: 1rem; border-bottom: 1px solid var(--border);">
                    <h3 title="${escapeHtml(filePath)}" style="margin: 0; font-size: 0.95rem;">${escapeHtml(filePath)}</h3>
                </div>
                <div id="report-diff-ui-container" style="padding: 0;"></div>
            `;

            const configuration = {
                drawFileList: false,
                fileListToggle: false,
                fileContentToggle: false,
                matching: 'lines',
                outputFormat: 'side-by-side',
                synchronisedScroll: true,
                highlight: true,
                renderNothingWhenEmpty: false,
            };

            const targetElement = document.getElementById('report-diff-ui-container');
            if (targetElement) {
                const diff2htmlUi = new Diff2HtmlUI(targetElement, diffText, configuration);
                diff2htmlUi.draw();
                diff2htmlUi.highlightCode();
            }
        } else {
            const formattedDiff = diffText ? diffText.replace(/\r\n/g, '\n') : "No content";
            diffContentEl.innerHTML = `
                <div style="padding:1rem;">
                    <h3 style="margin: 0 0 1rem 0;">${escapeHtml(filePath)}</h3>
                    <pre style="background:var(--bg-secondary, #f4f4f5);padding:1rem;overflow:auto;border-radius:8px;"><code>${escapeHtml(formattedDiff)}</code></pre>
                </div>
            `;
        }

    } catch (e) {
        console.error("[LinkedView] 加载文件Diff失败:", e);
        diffContentEl.innerHTML = `<div style="padding:1rem;color:red;">Error: ${escapeHtml(e.message)}</div>`;
    }
}

// 导出到全局
window.switchReportView = switchReportView;
window.loadReportDiffFiles = loadReportDiffFiles;
window.loadReportFileDiff = loadReportFileDiff;
window.refreshReportDiffLinked = refreshReportDiffLinked;

console.log('[LinkedView] 模块已加载');
