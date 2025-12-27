/**
 * Scanner Workflow UI Module
 * 
 * Handles the display of scanner execution progress and results in the workflow panel.
 * This module manages scanner state, renders scanner cards, and handles scanner events.
 * 
 * Requirements: 5.1, 5.2 - Modular scanner UI components with centralized event handling
 */

const ScannerUI = (function () {
    'use strict';

    // --- State Management ---
    const state = {
        scanners: new Map(),
        isScanning: false,
        summary: null,
        issues: [],
        issuesBySeverity: { error: [], warning: null, info: null },
        issuesPaging: {
            error: { offset: 0, has_more: false, loading: false },
            warning: { offset: 0, has_more: false, loading: false },
            info: { offset: 0, has_more: false, loading: false }
        },
        currentSeverityFilter: 'all',
        collapsedFileGroups: new Set(),
        scannedFiles: new Map(),
        scannersUsed: new Set(),
        overviewCollapsed: {
            scanners: false,
            files: false,
            used_scanners: true
        }
    };

    /**
     * @typedef {Object} ScannerState
     * @property {string} name - Scanner name (e.g., "pylint", "flake8")
     * @property {"pending"|"running"|"completed"|"error"} status - Current status
     * @property {string} [file] - Current file being scanned
     * @property {number} [startTime] - Start timestamp
     * @property {number} [duration_ms] - Execution duration in milliseconds
     * @property {number} [issue_count] - Total issues found
     * @property {number} [error_count] - Error-level issues found
     * @property {string} [error] - Error message if status is "error"
     * @property {boolean} collapsed - Whether the card is collapsed
     */

    /**
     * @typedef {Object} ScannerSummary
     * @property {number} total_issues - Total issues across all scanners
     * @property {{error: number, warning: number, info: number}} by_severity - Issues by severity
     * @property {number} scanners_executed - Number of scanners that ran
     * @property {number} scanners_failed - Number of scanners that failed
     * @property {Array} critical_issues - List of critical issues
     */

    // --- DOM References ---
    let containerEl = null;
    let cardsContainerEl = null;
    let summaryContainerEl = null;
    let progressIndicatorEl = null;
    let timerEl = null;
    let stageMetaEl = null;
    let scanStartTime = null;
    let scanTimerInterval = null;
    let preparingEl = null;
    let issuesListEl = null;
    let tabsContainerEl = null;
    let issuesListClickBound = false;

    // --- Initialization ---

    /**
     * Initialize the ScannerUI module.
     * @param {HTMLElement} [container] - Optional container element for scanner UI
     */
    function init(container) {
        // Find or use provided container
        containerEl = container || document.querySelector('.scanner-workflow-section');

        if (containerEl) {
            cardsContainerEl = containerEl.querySelector('.scanner-cards');
            summaryContainerEl = containerEl.querySelector('.scanner-summary');
            progressIndicatorEl = containerEl.querySelector('.scanner-progress-header');
            timerEl = progressIndicatorEl ? progressIndicatorEl.querySelector('.scanner-timer') : null;
            stageMetaEl = containerEl.querySelector('#scannerStageMeta') || document.getElementById('scannerStageMeta');
            issuesListEl = containerEl.querySelector('.scanner-issues-list');
            tabsContainerEl = containerEl.querySelector('.scanner-tabs');

            if (issuesListEl && !issuesListClickBound) {
                issuesListEl.addEventListener('click', (e) => {
                    const header = e.target.closest('.file-group-header');
                    if (!header) return;
                    const group = header.closest('.scanner-file-group');
                    if (!group) return;
                    group.classList.toggle('collapsed');
                    const fileKey = header.dataset.file;
                    if (fileKey) {
                        if (group.classList.contains('collapsed')) {
                            state.collapsedFileGroups.add(fileKey);
                        } else {
                            state.collapsedFileGroups.delete(fileKey);
                        }
                    }
                });
                issuesListClickBound = true;
            }

            // Setup tab click handlers
            if (tabsContainerEl) {
                tabsContainerEl.addEventListener('click', (e) => {
                    const tab = e.target.closest('.scanner-tab');
                    if (tab) {
                        const severity = tab.dataset.severity;
                        switchSeverityTab(severity);
                    }
                });
            }
        }

        // Reset state on init
        reset();

        if (tabsContainerEl && issuesListEl) {
            switchSeverityTab(state.currentSeverityFilter || 'all');

            renderStageMeta();
        }

        console.log('[ScannerUI] Initialized');
    }

    /**
     * Reset the scanner UI state and clear displays.
     */
    function reset() {
        // Clear state
        state.scanners.clear();
        state.isScanning = false;
        state.summary = null;
        state.issues = [];
        state.issuesBySeverity = { error: [], warning: null, info: null };
        state.issuesPaging = {
            error: { offset: 0, has_more: false, loading: false },
            warning: { offset: 0, has_more: false, loading: false },
            info: { offset: 0, has_more: false, loading: false }
        };
        state.currentSeverityFilter = 'all';
        state.collapsedFileGroups.clear();
        state.scannedFiles.clear();
        state.scannersUsed.clear();
        state.overviewCollapsed.scanners = false;
        state.overviewCollapsed.files = false;
        state.overviewCollapsed.used_scanners = true;

        stopScanTimer();
        scanStartTime = null;
        const metaEl = stageMetaEl || (typeof document !== 'undefined' ? document.getElementById('scannerStageMeta') : null);
        if (metaEl) metaEl.textContent = '';

        // Clear DOM
        if (cardsContainerEl) {
            cardsContainerEl.innerHTML = '';
        }
        if (summaryContainerEl) {
            summaryContainerEl.style.display = 'none';
            summaryContainerEl.innerHTML = '';
        }
        if (issuesListEl) {
            issuesListEl.innerHTML = '';
        }
        if (progressIndicatorEl) {
            updateProgressIndicator(false);
        }
        if (preparingEl) {
            try { preparingEl.remove(); } catch (_) { }
            preparingEl = null;
        }

        console.log('[ScannerUI] Reset');
    }

    // --- Event Handlers ---

    /**
     * Handle scanner progress events from the backend.
     * @param {Object} event - Scanner progress event
     * @param {string} event.status - "start" | "complete" | "error"
     * @param {string} event.scanner - Scanner name
     * @param {string} [event.file] - File being scanned (for "start")
     * @param {number} [event.timestamp] - Start timestamp (for "start")
     * @param {number} [event.duration_ms] - Duration in ms (for "complete")
     * @param {number} [event.issue_count] - Issue count (for "complete")
     * @param {number} [event.error_count] - Error count (for "complete")
     * @param {string} [event.error] - Error message (for "error")
     */
    function handleScannerProgress(event) {
        if (!event || !event.scanner) {
            console.warn('[ScannerUI] Invalid scanner progress event:', event);
            return;
        }

        const scannerName = event.scanner;
        const status = event.status;

        switch (status) {
            case 'start':
                handleScannerStart(scannerName, event);
                break;
            case 'complete':
                handleScannerComplete(scannerName, event);
                break;
            case 'error':
                handleScannerError(scannerName, event);
                break;
            default:
                console.warn('[ScannerUI] Unknown scanner status:', status);
        }
    }

    /**
     * Handle scanner start event.
     * @param {string} scannerName - Scanner name
     * @param {Object} event - Event data
     */
    function handleScannerStart(scannerName, event) {
        // Create or update scanner state
        const scannerState = {
            name: scannerName,
            status: 'running',
            file: event.file || '',
            startTime: event.timestamp || Date.now(),
            collapsed: true
        };

        state.scanners.set(scannerName, scannerState);
        state.isScanning = true;

        // Update UI
        renderScannerCard(scannerState);
        updateProgressIndicator(true);
        // Ensure timer running
        startScanTimer();

        renderStageMeta();

        if (state.currentSeverityFilter === 'all') {
            renderOverview();
        }

        console.log(`[ScannerUI] Scanner started: ${scannerName}`);
    }

    /**
     * Handle scanner complete event.
     * @param {string} scannerName - Scanner name
     * @param {Object} event - Event data
     */
    function handleScannerComplete(scannerName, event) {
        const scannerState = state.scanners.get(scannerName) || { name: scannerName, collapsed: false };

        // Update state
        scannerState.status = 'completed';
        scannerState.duration_ms = event.duration_ms || 0;
        scannerState.issue_count = event.issue_count || 0;
        scannerState.error_count = event.error_count || 0;

        state.scanners.set(scannerName, scannerState);

        // Check if all scanners completed
        checkAllScannersCompleted();

        // Update UI
        updateScannerStatus(scannerName, 'completed');

        if (state.currentSeverityFilter === 'all') {
            renderOverview();
        }

        console.log(`[ScannerUI] Scanner completed: ${scannerName}, issues: ${scannerState.issue_count}`);
    }

    /**
     * Handle scanner error event.
     * @param {string} scannerName - Scanner name
     * @param {Object} event - Event data
     */
    function handleScannerError(scannerName, event) {
        const scannerState = state.scanners.get(scannerName) || { name: scannerName, collapsed: false };

        // Update state
        scannerState.status = 'error';
        scannerState.error = event.error || 'Unknown error';

        state.scanners.set(scannerName, scannerState);

        // Check if all scanners completed
        checkAllScannersCompleted();

        // Update UI
        updateScannerStatus(scannerName, 'error');

        if (state.currentSeverityFilter === 'all') {
            renderOverview();
        }

        console.log(`[ScannerUI] Scanner error: ${scannerName}, error: ${scannerState.error}`);
    }

    /**
     * Update the currently scanning file for a scanner (without creating new cards).
     * @param {string} scannerName - Scanner name
     * @param {string} file - Current file being scanned
     * @param {string} [language] - Language of the file
     */
    function updateScanningFile(scannerName, file, language) {
        const scannerState = state.scanners.get(scannerName);
        if (!scannerState) return;

        // Update current file info
        scannerState.currentFile = file;
        scannerState.currentLanguage = language;

        // Track files progress
        if (!scannerState.filesProgress) {
            scannerState.filesProgress = [];
        }

        // Update UI - just update the file display, not recreate card
        const cardEl = cardsContainerEl?.querySelector(`[data-scanner="${scannerName}"]`);
        if (cardEl) {
            const fileEl = cardEl.querySelector('.scanner-current-file');
            if (fileEl) {
                const shortFile = file.split(/[/\\]/).pop();
                fileEl.textContent = shortFile;
                fileEl.title = file;
            }
        }
    }

    /**
     * Update file progress for a scanner.
     * @param {string} scannerName - Scanner name  
     * @param {Object} fileInfo - File completion info
     */
    function updateFileProgress(scannerName, fileInfo) {
        const scannerState = state.scanners.get(scannerName);
        if (!scannerState) return;

        if (fileInfo && fileInfo.file) {
            const fp = String(fileInfo.file);
            state.scannedFiles.set(fp, {
                file: fp,
                issues_count: Number(fileInfo.issues_count || 0),
                language: fileInfo.language,
                duration_ms: fileInfo.duration_ms
            });
        }

        // Accumulate stats
        if (!scannerState.filesCompleted) scannerState.filesCompleted = 0;
        if (!scannerState.totalIssues) scannerState.totalIssues = 0;
        if (!scannerState.totalDuration) scannerState.totalDuration = 0;
        if (!scannerState.languages) scannerState.languages = new Set();

        scannerState.filesCompleted++;
        scannerState.totalIssues += fileInfo.issues_count || 0;
        scannerState.totalDuration += fileInfo.duration_ms || 0;
        if (fileInfo.language) scannerState.languages.add(fileInfo.language);

        // Update progress display
        const cardEl = cardsContainerEl?.querySelector(`[data-scanner="${scannerName}"]`);
        if (cardEl) {
            const progressEl = cardEl.querySelector('.scanner-files-progress');
            if (progressEl && fileInfo.progress !== undefined) {
                progressEl.textContent = `${Math.round(fileInfo.progress * 100)}%`;
            }
        }

        if (state.currentSeverityFilter === 'all') {
            renderOverview();
        }

        renderStageMeta();
    }

    /**
     * Toggle scanner section collapsed state.
     */
    function toggleSection() {
        const section = document.getElementById('scannerWorkflowSection');
        if (section) {
            section.classList.toggle('collapsed');
        }
    }

    /**
     * Handle scanner issues summary event.
     * @param {Object} event - Scanner summary event
     */
    function handleScannerSummary(event) {
        if (!event) {
            console.warn('[ScannerUI] Invalid scanner summary event');
            return;
        }

        // Store summary data
        state.summary = {
            total_issues: event.total_issues || 0,
            by_severity: event.by_severity || { error: 0, warning: 0, info: 0 },
            scanners_executed: state.scanners.size,
            scanners_failed: countFailedScanners(),
            critical_issues: event.critical_issues || []
        };

        if (Array.isArray(event.scanners_used)) {
            for (const s of event.scanners_used) {
                if (s) state.scannersUsed.add(String(s));
            }
        }
        if (Number.isFinite(Number(event.files_scanned))) {
            state.summary.files_scanned = Number(event.files_scanned);
        }
        if (Number.isFinite(Number(event.files_total))) {
            state.summary.files_total = Number(event.files_total);
        }
        if (Number.isFinite(Number(event.duration_ms))) {
            state.summary.duration_ms = Number(event.duration_ms);
        }

        // Store issues for filtering
        state.issues = event.critical_issues || [];
        state.issuesBySeverity.error = state.issues;
        state.issuesPaging.error.offset = state.issues.length;
        const totalErrorCount = (state.summary && state.summary.by_severity)
            ? Number(state.summary.by_severity.error || 0)
            : 0;
        state.issuesPaging.error.has_more = Number.isFinite(totalErrorCount) && totalErrorCount > state.issues.length;
        state.issuesPaging.error.loading = false;
        state.issuesBySeverity.warning = null;
        state.issuesBySeverity.info = null;
        state.issuesPaging.warning = { offset: 0, has_more: false, loading: false };
        state.issuesPaging.info = { offset: 0, has_more: false, loading: false };

        // Update UI
        state.isScanning = false;
        updateProgressIndicator(false);
        stopScanTimer();
        renderSummaryCard(state.summary);

        // Update tab counts
        updateTabCounts(state.summary.by_severity);

        switchSeverityTab(state.currentSeverityFilter || 'all');

        console.log('[ScannerUI] Summary received:', state.summary);
    }

    async function fetchIssuesPage(severity, offset, limit) {
        const sessionId = (typeof window !== 'undefined' && window.currentSessionId) ? window.currentSessionId : '';
        if (!sessionId) throw new Error('missing_session_id');
        const url = `/api/static-scan/issues?session_id=${encodeURIComponent(sessionId)}&severity=${encodeURIComponent(severity)}&offset=${encodeURIComponent(String(offset || 0))}&limit=${encodeURIComponent(String(limit || 50))}`;
        const resp = await fetch(url, { method: 'GET' });
        if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(txt || `http_${resp.status}`);
        }
        return await resp.json();
    }

    function renderIssuesFetchPlaceholder(severity, loading, message) {
        if (!issuesListEl) return;
        const sevLabel = getSeverityLabel(severity);
        const btnText = loading ? '加载中...' : `加载${sevLabel}`;
        const disabled = loading ? 'disabled' : '';
        issuesListEl.innerHTML = `
            <div class="scanner-issues-empty">
                <svg class="icon"><use href="#icon-info"></use></svg>
                <span>${escapeHtml(message || '该级别默认不下发明细')}</span>
                <button class="btn-primary scanner-load-btn" ${disabled} onclick="ScannerUI.loadIssuesForSeverity('${severity}')">${btnText}</button>
            </div>
        `;
    }

    function renderLoadMoreButton(severity, hasMore, loading) {
        if (!hasMore) return '';
        const disabled = loading ? 'disabled' : '';
        const text = loading ? '加载中...' : '加载更多';
        return `<div class="scanner-issues-loadmore"><button class="btn-primary" ${disabled} onclick="ScannerUI.loadMoreIssues('${severity}')">${text}</button></div>`;
    }

    async function loadIssuesForSeverity(severity) {
        const sev = String(severity || 'error');
        if (!state.issuesPaging[sev]) return;
        if (state.issuesPaging[sev].loading) return;
        state.issuesPaging[sev].loading = true;
        try {
            renderIssuesFetchPlaceholder(sev, true, '该级别默认不下发明细');
            const data = await fetchIssuesPage(sev, 0, 50);
            const list = Array.isArray(data.issues) ? data.issues : [];
            state.issuesBySeverity[sev] = list;
            state.issuesPaging[sev].offset = (data.offset || 0) + list.length;
            state.issuesPaging[sev].has_more = !!data.has_more;
        } catch (e) {
            state.issuesBySeverity[sev] = [];
            state.issuesPaging[sev].offset = 0;
            state.issuesPaging[sev].has_more = false;
            renderIssuesFetchPlaceholder(sev, false, '加载失败');
            return;
        } finally {
            state.issuesPaging[sev].loading = false;
        }

        if (state.currentSeverityFilter === sev) {
            const issues = state.issuesBySeverity[sev] || [];
            renderIssuesList(issues);
            if (issuesListEl) {
                const extra = renderLoadMoreButton(sev, state.issuesPaging[sev].has_more, state.issuesPaging[sev].loading);
                if (extra) issuesListEl.insertAdjacentHTML('beforeend', extra);
            }
        }
    }

    async function loadMoreIssues(severity) {
        const sev = String(severity || 'error');
        const paging = state.issuesPaging[sev];
        if (!paging || paging.loading || !paging.has_more) return;
        paging.loading = true;

        // 记录加载前的文件集合，用于判断哪些是新加载的
        const existingIssues = Array.isArray(state.issuesBySeverity[sev]) ? state.issuesBySeverity[sev] : [];
        const existingFiles = new Set();
        existingIssues.forEach(issue => {
            const file = issue.file || issue.file_path || 'Unknown';
            existingFiles.add(encodeURIComponent(file));
        });

        try {
            // 一次加载2页（100条）
            const data = await fetchIssuesPage(sev, paging.offset || 0, 100);
            const list = Array.isArray(data.issues) ? data.issues : [];
            state.issuesBySeverity[sev] = existingIssues.concat(list);
            paging.offset = (data.offset || paging.offset || 0) + list.length;
            paging.has_more = !!data.has_more;

            // 将新加载的文件默认设为折叠状态
            list.forEach(issue => {
                const file = issue.file || issue.file_path || 'Unknown';
                const fileKey = encodeURIComponent(file);
                if (!existingFiles.has(fileKey)) {
                    state.collapsedFileGroups.add(fileKey);
                }
            });
        } catch (e) {
            paging.has_more = false;
        } finally {
            paging.loading = false;
        }

        if (state.currentSeverityFilter === sev) {
            const issues = state.issuesBySeverity[sev] || [];
            renderIssuesList(issues);
            if (issuesListEl) {
                const extra = renderLoadMoreButton(sev, state.issuesPaging[sev].has_more, state.issuesPaging[sev].loading);
                if (extra) issuesListEl.insertAdjacentHTML('beforeend', extra);
            }
        }
    }

    // --- Rendering Methods ---

    /**
     * Render a scanner card in the UI.
     * @param {ScannerState} scanner - Scanner state object
     * @returns {HTMLElement} The created card element
     */
    function renderScannerCard(scanner) {
        if (!cardsContainerEl) return null;

        // Check if card already exists
        let cardEl = cardsContainerEl.querySelector(`[data-scanner="${scanner.name}"]`);

        if (!cardEl) {
            // Create new card
            cardEl = document.createElement('div');
            cardEl.className = 'scanner-card';
            cardEl.dataset.scanner = scanner.name;
            cardsContainerEl.appendChild(cardEl);
        }

        // Build card HTML
        const statusClass = getStatusClass(scanner.status);
        const statusText = getStatusText(scanner.status);
        const collapsedClass = scanner.collapsed ? 'collapsed' : '';

        // Prepare display values
        const filesDisplay = scanner.filesCompleted !== undefined && scanner.file
            ? `${scanner.filesCompleted}/${scanner.file.replace(' files', '')} 文件`
            : scanner.file || '';

        const languagesDisplay = scanner.languages && scanner.languages.size > 0
            ? Array.from(scanner.languages).join(', ')
            : '';

        const currentFileDisplay = scanner.currentFile
            ? scanner.currentFile.split(/[/\\]/).pop()
            : '';

        cardEl.className = `scanner-card ${statusClass} ${collapsedClass}`;
        cardEl.innerHTML = `
            <div class="scanner-card-header" onclick="ScannerUI.toggleScannerDetails('${scanner.name}')">
                <span class="scanner-name">${escapeHtml(scanner.name === 'static_scan' ? '静态分析' : scanner.name)}</span>
                <span class="scanner-status ${statusClass}">${statusText}</span>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="scanner-card-body">
                ${filesDisplay ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">扫描文件</span>
                    <span class="scanner-value">${escapeHtml(filesDisplay)}</span>
                </div>` : ''}
                
                ${currentFileDisplay && scanner.status === 'running' ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">当前文件</span>
                    <span class="scanner-value font-mono scanner-current-file" title="${escapeHtml(scanner.currentFile || '')}">${escapeHtml(currentFileDisplay)}</span>
                </div>` : ''}
                
                ${languagesDisplay ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">语言</span>
                    <span class="scanner-value">${escapeHtml(languagesDisplay)}</span>
                </div>` : ''}
                
                ${scanner.duration_ms !== undefined ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">耗时</span>
                    <span class="scanner-value">${formatDuration(scanner.duration_ms)}</span>
                </div>` : ''}
                
                ${scanner.issue_count !== undefined ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">发现问题</span>
                    <span class="scanner-value badge ${scanner.issue_count > 0 ? (scanner.error_count > 0 ? 'high' : 'medium') : 'low'}">${scanner.issue_count}</span>
                </div>` : ''}
                
                ${scanner.error_count !== undefined && scanner.error_count > 0 ? `
                <div class="scanner-detail-row">
                    <span class="scanner-label">严重错误</span>
                    <span class="scanner-value badge high">${scanner.error_count}</span>
                </div>` : ''}
                
                ${scanner.error ? `<div class="scanner-error">${escapeHtml(scanner.error)}</div>` : ''}
            </div>
        `;

        return cardEl;
    }

    /**
     * Update the status display of a scanner card.
     * @param {string} scannerName - Scanner name
     * @param {string} status - New status
     */
    function updateScannerStatus(scannerName, status) {
        const scanner = state.scanners.get(scannerName);
        if (scanner) {
            renderScannerCard(scanner);
        }
    }

    /**
     * Render the summary card.
     * @param {ScannerSummary} summary - Summary data
     * @returns {HTMLElement} The created summary element
     */
    function renderSummaryCard(summary) {
        if (!summaryContainerEl) return null;

        const noIssues = summary.total_issues === 0;

        // 如果有扫描器卡片，只显示简洁的状态提示
        if (state.scanners.size > 0) {
            if (noIssues) {
                summaryContainerEl.innerHTML = `
                    <div class="summary-inline success">✓ 未发现问题</div>
                `;
            } else {
                // 有问题时不显示汇总卡片，问题会显示在 issues-list 中
                summaryContainerEl.innerHTML = '';
                summaryContainerEl.style.display = 'none';
                return summaryContainerEl;
            }
        } else {
            // 如果没有扫描器卡片（fallback 情况），显示完整汇总
            const hasErrors = summary.by_severity.error > 0;
            if (noIssues) {
                summaryContainerEl.innerHTML = `
                    <div class="summary-header success">✓ 扫描完成</div>
                    <div class="summary-message">未发现代码问题</div>
                `;
            } else {
                summaryContainerEl.innerHTML = `
                    <div class="summary-header ${hasErrors ? 'has-errors' : ''}">扫描完成</div>
                    <div class="summary-stats">
                        <span class="stat error ${hasErrors ? 'highlight' : ''}">${summary.by_severity.error} 错误</span>
                        <span class="stat warning">${summary.by_severity.warning} 警告</span>
                        <span class="stat info">${summary.by_severity.info} 提示</span>
                    </div>
                    <div class="summary-total">共 ${summary.total_issues} 个问题</div>
                `;
            }
        }

        summaryContainerEl.style.display = 'block';

        return summaryContainerEl;
    }

    /**
     * Toggle the collapsed state of a scanner card.
     * @param {string} scannerName - Scanner name
     */
    function toggleScannerDetails(scannerName) {
        const scanner = state.scanners.get(scannerName);
        if (!scanner) return;

        // Toggle collapsed state
        scanner.collapsed = !scanner.collapsed;
        state.scanners.set(scannerName, scanner);

        // Update card DOM
        const cardEl = cardsContainerEl?.querySelector(`[data-scanner="${scannerName}"]`);
        if (cardEl) {
            cardEl.classList.toggle('collapsed', scanner.collapsed);
        }
    }

    // --- Helper Methods ---

    /**
     * Update the progress indicator visibility.
     * @param {boolean} isActive - Whether scanning is active
     */
    function updateProgressIndicator(isActive) {
        if (!progressIndicatorEl) return;

        const statusBadge = progressIndicatorEl.querySelector('.scanner-status-badge');
        if (statusBadge) {
            statusBadge.textContent = isActive ? '进行中' : '已完成';
            statusBadge.className = `scanner-status-badge ${isActive ? 'running' : 'completed'}`;
        }
        // Ensure timer element exists
        if (progressIndicatorEl) {
            if (!timerEl) {
                timerEl = document.createElement('span');
                timerEl.className = 'scanner-timer';
                timerEl.textContent = '00:00';
                progressIndicatorEl.appendChild(timerEl);
            }
            timerEl.style.display = isActive ? 'inline' : 'inline';
        }

        // Show the section when there are scanners or actively scanning
        // But do NOT hide it - let external code control hiding
        if (containerEl && (state.scanners.size > 0 || isActive)) {
            containerEl.style.display = 'block';
        }
    }

    function renderStageMeta() {
        try {
            const metaEl = stageMetaEl || (typeof document !== 'undefined' ? document.getElementById('scannerStageMeta') : null);
            if (!metaEl) return;

            const parts = [];

            const durationMs = (state.summary && Number.isFinite(Number(state.summary.duration_ms)))
                ? Number(state.summary.duration_ms)
                : (scanStartTime ? (Date.now() - scanStartTime) : null);
            if (durationMs !== null && Number.isFinite(Number(durationMs))) {
                parts.push(`耗时 ${formatDuration(Number(durationMs))}`);
            }

            let filesScanned = null;
            let filesTotal = null;

            if (state.summary && Number.isFinite(Number(state.summary.files_scanned))) filesScanned = Number(state.summary.files_scanned);
            if (state.summary && Number.isFinite(Number(state.summary.files_total))) filesTotal = Number(state.summary.files_total);

            if (filesScanned === null && state.scannedFiles && state.scannedFiles.size) filesScanned = state.scannedFiles.size;

            if (filesTotal === null) {
                const staticScanner = state.scanners.get('static_scan');
                if (staticScanner && staticScanner.file) {
                    const m = String(staticScanner.file).match(/^(\d+)\s+files\b/i);
                    if (m) filesTotal = Number(m[1]);
                }
            }

            if (filesScanned !== null && Number.isFinite(Number(filesScanned))) {
                const tail = (filesTotal !== null && Number.isFinite(Number(filesTotal))) ? `/${Number(filesTotal)}` : '';
                parts.push(`文件 ${Number(filesScanned)}${tail}`);
            } else if (filesTotal !== null && Number.isFinite(Number(filesTotal))) {
                parts.push(`文件 0/${Number(filesTotal)}`);
            }

            metaEl.textContent = parts.join(' · ');
        } catch (_) { }
    }

    // Timer helpers (module scope)
    function startScanTimer() {
        try {
            if (scanTimerInterval) clearInterval(scanTimerInterval);
            scanStartTime = Date.now();
            if (!timerEl && progressIndicatorEl) {
                timerEl = document.createElement('span');
                timerEl.className = 'scanner-timer';
                progressIndicatorEl.appendChild(timerEl);
            }
            if (timerEl) timerEl.textContent = '00:00';
            scanTimerInterval = setInterval(() => {
                const elapsed = Date.now() - (scanStartTime || Date.now());
                const sec = Math.floor(elapsed / 1000);
                const m = Math.floor(sec / 60).toString().padStart(2, '0');
                const s = (sec % 60).toString().padStart(2, '0');
                if (timerEl) timerEl.textContent = `${m}:${s}`;
                renderStageMeta();
            }, 1000);

            renderStageMeta();
        } catch (_) { /* ignore */ }
    }

    function stopScanTimer() {
        try {
            if (scanTimerInterval) {
                clearInterval(scanTimerInterval);
                scanTimerInterval = null;
            }
        } catch (_) { /* ignore */ }
    }

    /**
     * Check if all scanners have completed.
     */
    function checkAllScannersCompleted() {
        let allCompleted = true;

        for (const scanner of state.scanners.values()) {
            if (scanner.status === 'running' || scanner.status === 'pending') {
                allCompleted = false;
                break;
            }
        }

        if (allCompleted && state.scanners.size > 0) {
            state.isScanning = false;
            updateProgressIndicator(false);
            stopScanTimer();
        }
    }

    /**
     * Count the number of failed scanners.
     * @returns {number} Number of failed scanners
     */
    function countFailedScanners() {
        let count = 0;
        for (const scanner of state.scanners.values()) {
            if (scanner.status === 'error') {
                count++;
            }
        }
        return count;
    }

    /**
     * Get CSS class for scanner status.
     * @param {string} status - Scanner status
     * @returns {string} CSS class name
     */
    function getStatusClass(status) {
        switch (status) {
            case 'running': return 'running';
            case 'completed': return 'completed';
            case 'error': return 'error';
            default: return 'pending';
        }
    }

    /**
     * Get display text for scanner status.
     * @param {string} status - Scanner status
     * @returns {string} Display text
     */
    function getStatusText(status) {
        switch (status) {
            case 'running': return '扫描中...';
            case 'completed': return '完成';
            case 'error': return '错误';
            default: return '等待中';
        }
    }

    /**
     * Format duration in milliseconds to human-readable string.
     * @param {number} ms - Duration in milliseconds
     * @returns {string} Formatted duration
     */
    function formatDuration(ms) {
        if (ms < 1000) {
            return `${ms}ms`;
        }
        return `${(ms / 1000).toFixed(1)}s`;
    }

    /**
     * Escape HTML special characters.
     * @param {string} str - String to escape
     * @returns {string} Escaped string
     */
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // --- Edge Case Handling ---

    /**
     * Handle scanner timeout - mark scanner as error if running too long.
     * @param {string} scannerName - Scanner name
     * @param {number} timeoutMs - Timeout in milliseconds (default 60000)
     */
    function handleScannerTimeout(scannerName, timeoutMs = 60000) {
        const scanner = state.scanners.get(scannerName);
        if (!scanner || scanner.status !== 'running') return;

        const elapsed = Date.now() - (scanner.startTime || Date.now());
        if (elapsed > timeoutMs) {
            scanner.status = 'error';
            scanner.error = `扫描超时 (>${Math.round(timeoutMs / 1000)}s)`;
            state.scanners.set(scannerName, scanner);
            updateScannerStatus(scannerName, 'error');
            checkAllScannersCompleted();
            console.warn(`[ScannerUI] Scanner ${scannerName} timed out after ${elapsed}ms`);
        }
    }

    /**
     * Check all running scanners for timeout.
     * @param {number} timeoutMs - Timeout in milliseconds
     */
    function checkAllTimeouts(timeoutMs = 60000) {
        for (const [name, scanner] of state.scanners) {
            if (scanner.status === 'running') {
                handleScannerTimeout(name, timeoutMs);
            }
        }
    }

    /**
     * Handle network disconnection - show warning state.
     */
    function handleDisconnection() {
        if (state.isScanning) {
            // Mark all running scanners as potentially stale
            for (const [name, scanner] of state.scanners) {
                if (scanner.status === 'running') {
                    const cardEl = cardsContainerEl?.querySelector(`[data-scanner="${name}"]`);
                    if (cardEl) {
                        cardEl.classList.add('disconnected');
                    }
                }
            }
            console.warn('[ScannerUI] Network disconnection detected during scanning');
        }
    }

    /**
     * Handle network reconnection - remove warning state.
     */
    function handleReconnection() {
        const cards = cardsContainerEl?.querySelectorAll('.scanner-card.disconnected');
        if (cards) {
            cards.forEach(card => card.classList.remove('disconnected'));
        }
        console.log('[ScannerUI] Network reconnected');
    }

    // --- Public API ---

    /**
     * Get the current state (for testing purposes).
     * @returns {Object} Current state
     */
    function getState() {
        return {
            scanners: new Map(state.scanners),
            isScanning: state.isScanning,
            summary: state.summary ? { ...state.summary } : null
        };
    }

    // Begin scanning: show header and start timer even before events arrive
    function beginScanning() {
        if (progressIndicatorEl) {
            // Show preparing state first (no events yet)
            const statusBadge = progressIndicatorEl.querySelector('.scanner-status-badge');
            if (statusBadge) {
                statusBadge.textContent = '准备中';
                statusBadge.className = 'scanner-status-badge preparing';
            }
            // Ensure section visible but collapsed by default
            containerEl.style.display = 'block';
            containerEl.classList.add('collapsed');
        }
        // Add preparing placeholder card
        if (cardsContainerEl && !preparingEl) {
            preparingEl = document.createElement('div');
            preparingEl.className = 'scanner-preparing';
            preparingEl.innerHTML = `
                <div class="preparing-head">
                    <div class="spinner-small"></div>
                    <span class="preparing-title">正在准备扫描环境...</span>
                </div>
                <div class="preparing-body">预计需要几十秒，请稍候</div>
            `;
            cardsContainerEl.innerHTML = ''; // clear any residual
            cardsContainerEl.appendChild(preparingEl);
        }
        startScanTimer();
        renderStageMeta();
    }

    function endScanning() {
        stopScanTimer();
        updateProgressIndicator(false);
    }

    /**
     * Get all scanner names currently tracked.
     * @returns {string[]} Array of scanner names
     */
    function getScannerNames() {
        return Array.from(state.scanners.keys());
    }

    // --- Tab and Issues List Functions ---

    /**
     * Update tab counts based on severity breakdown.
     * @param {{error: number, warning: number, info: number}} bySeverity - Issue counts by severity
     */
    function updateTabCounts(bySeverity) {
        if (!tabsContainerEl) return;

        const computedTotal = (bySeverity.error || 0) + (bySeverity.warning || 0) + (bySeverity.info || 0);
        const total = (state.summary && Number.isFinite(Number(state.summary.total_issues)))
            ? Number(state.summary.total_issues)
            : computedTotal;

        const allTab = tabsContainerEl.querySelector('[data-severity="all"] .tab-count');
        const errorTab = tabsContainerEl.querySelector('[data-severity="error"] .tab-count');
        const warningTab = tabsContainerEl.querySelector('[data-severity="warning"] .tab-count');
        const infoTab = tabsContainerEl.querySelector('[data-severity="info"] .tab-count');

        if (allTab) allTab.textContent = total;
        if (errorTab) errorTab.textContent = bySeverity.error || 0;
        if (warningTab) warningTab.textContent = bySeverity.warning || 0;
        if (infoTab) infoTab.textContent = bySeverity.info || 0;
    }

    function getOverviewCounts() {
        const by = (state.summary && state.summary.by_severity) ? state.summary.by_severity : { error: 0, warning: 0, info: 0 };
        const computedTotal = (by.error || 0) + (by.warning || 0) + (by.info || 0);
        const total = (state.summary && Number.isFinite(Number(state.summary.total_issues)))
            ? Number(state.summary.total_issues)
            : computedTotal;
        return {
            bySeverity: by,
            total
        };
    }

    function renderOverview() {
        if (!issuesListEl) return;

        renderStageMeta();
        const scanners = Array.from(state.scanners.values());
        scanners.sort((a, b) => {
            const sa = String(a.name || '');
            const sb = String(b.name || '');
            return sa.localeCompare(sb);
        });

        const files = Array.from(state.scannedFiles.values());
        files.sort((a, b) => {
            const ia = Number(a.issues_count || 0);
            const ib = Number(b.issues_count || 0);
            if (ib !== ia) return ib - ia;
            return String(a.file || '').localeCompare(String(b.file || ''));
        });

        const usedScannerNames = state.scannersUsed.size
            ? Array.from(state.scannersUsed)
            : scanners.map(s => s.name).filter(Boolean);

        const usedScanners = usedScannerNames
            .filter(n => n && n !== 'static_scan');

        const scannersCollapsed = !!state.overviewCollapsed.scanners;
        const filesCollapsed = !!state.overviewCollapsed.files;
        const usedScannersCollapsed = !!state.overviewCollapsed.used_scanners;

        const scannersHeaderRight = `
            <span class="issue-count">${scanners.length || 0}</span>
        `;

        const filesHeaderRight = `
            <span class="issue-count">${files.length}</span>
        `;

        let scannersBody = '';
        if (!scanners.length && usedScannerNames.length) {
            scannersBody = `
                <div class="scanner-overview-list">
                    ${usedScannerNames.map(n => `
                        <div class="scanner-overview-row">
                            <div class="scanner-overview-main">
                                <span class="scanner-overview-name">${escapeHtml(n === 'static_scan' ? '静态分析' : n)}</span>
                            </div>
                            <div class="scanner-overview-right">
                                <span class="scanner-status pending">等待中</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        } else if (scanners.length) {
            scannersBody = `
                <div class="scanner-overview-list">
                    ${scanners.map(s => {
                const statusClass = getStatusClass(s.status);
                const statusText = getStatusText(s.status);
                const details = [];
                const currentFile = s.currentFile ? String(s.currentFile).split(/[/\\]/).pop() : '';
                if (currentFile && s.status === 'running') details.push(`当前 ${currentFile}`);
                if (s.languages && s.languages.size > 0) details.push(`语言 ${Array.from(s.languages).join(', ')}`);
                if (Number.isFinite(Number(s.duration_ms))) details.push(`耗时 ${formatDuration(Number(s.duration_ms))}`);
                if (Number.isFinite(Number(s.issue_count))) details.push(`问题 ${Number(s.issue_count)}`);
                if (Number.isFinite(Number(s.error_count)) && Number(s.error_count) > 0) details.push(`错误 ${Number(s.error_count)}`);

                return `
                            <div class="scanner-overview-row">
                                <div class="scanner-overview-main">
                                    <span class="scanner-overview-name">${escapeHtml(s.name === 'static_scan' ? '静态分析' : s.name)}</span>
                                    ${details.length ? `<span class="scanner-overview-sub">${escapeHtml(details.join(' · '))}</span>` : ''}
                                </div>
                                <div class="scanner-overview-right">
                                    <span class="scanner-status ${statusClass}">${escapeHtml(statusText)}</span>
                                </div>
                            </div>
                        `;
            }).join('')}
                </div>
            `;
        } else {
            scannersBody = `
                <div class="scanner-overview-empty">暂无扫描器数据</div>
            `;
        }

        const usedScannersBlock = usedScanners.length ? `
            <div class="scanner-overview-block nested ${usedScannersCollapsed ? 'collapsed' : ''}" data-overview-block="used_scanners">
                <div class="scanner-overview-block-header" data-overview-toggle="used_scanners">
                    <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                    <span class="block-title">扫描器</span>
                    <span class="block-right"><span class="issue-count">${usedScanners.length}</span></span>
                </div>
                <div class="scanner-overview-block-body">
                    <div class="scanner-overview-list">
                        ${usedScanners.map(n => `
                            <div class="scanner-overview-row">
                                <div class="scanner-overview-main">
                                    <span class="scanner-overview-name">${escapeHtml(n)}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        ` : '';

        let filesBody = '';
        if (!files.length) {
            filesBody = `
                <div class="scanner-overview-empty">暂无文件数据</div>
            `;
        } else {
            const errorFiles = new Set();
            try {
                const errors = Array.isArray(state.issuesBySeverity && state.issuesBySeverity.error)
                    ? state.issuesBySeverity.error
                    : [];
                for (const it of errors) {
                    const f = it && (it.file || it.file_path);
                    if (f) errorFiles.add(String(f));
                }
            } catch (_) {
            }

            filesBody = `
                <div class="scanner-files-list">
                    ${files.map(f => {
                const fp = String(f.file || '');
                const base = fp.split(/[/\\]/).pop() || fp;
                const issues = Number(f.issues_count || 0);
                const duration = Number(f.duration_ms);
                const durationText = Number.isFinite(duration) ? formatDuration(duration) : '-';

                const isErrorFile = errorFiles.has(fp);
                const issueTone = isErrorFile
                    ? 'is-error'
                    : (issues > 0 ? 'is-has' : 'is-zero');
                return `
                            <div class="scanner-file-row" title="${escapeHtml(fp)}">
                                <span class="file-name">${escapeHtml(base)}</span>
                                <span class="file-metrics">
                                    <span class="file-duration">
                                        <svg class="icon clock"><use href="#icon-clock"></use></svg>
                                        <span>${escapeHtml(durationText)}</span>
                                    </span>
                                    <span class="issue-count ${issueTone}">${issues}</span>
                                </span>
                            </div>
                        `;
            }).join('')}
                </div>
            `;
        }

        issuesListEl.innerHTML = `
            <div class="scanner-overview">
                <div class="scanner-overview-section">
                    <div class="scanner-overview-block ${scannersCollapsed ? 'collapsed' : ''}" data-overview-block="scanners">
                        <div class="scanner-overview-block-header" data-overview-toggle="scanners">
                            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                            <span class="block-title">扫描情况</span>
                            <span class="block-right">${scannersHeaderRight}</span>
                        </div>
                        <div class="scanner-overview-block-body">
                            ${usedScannersBlock}
                            ${scannersBody}
                        </div>
                    </div>

                    <div class="scanner-overview-block ${filesCollapsed ? 'collapsed' : ''}" data-overview-block="files">
                        <div class="scanner-overview-block-header" data-overview-toggle="files">
                            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                            <span class="block-title">扫描文件列表</span>
                            <span class="block-right">${filesHeaderRight}</span>
                        </div>
                        <div class="scanner-overview-block-body">
                            ${filesBody}
                        </div>
                    </div>
                </div>
            </div>
        `;

        const toggles = issuesListEl.querySelectorAll('[data-overview-toggle]');
        toggles.forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.getAttribute('data-overview-toggle');
                if (key === 'scanners') state.overviewCollapsed.scanners = !state.overviewCollapsed.scanners;
                if (key === 'files') state.overviewCollapsed.files = !state.overviewCollapsed.files;
                if (key === 'used_scanners') state.overviewCollapsed.used_scanners = !state.overviewCollapsed.used_scanners;
                renderOverview();
            });
        });
    }

    /**
     * Switch to a severity tab and filter issues.
     * @param {string} severity - 'all', 'error', 'warning', or 'info'
     */
    function switchSeverityTab(severity) {
        if (!tabsContainerEl) return;

        // Update active tab state
        state.currentSeverityFilter = severity;

        // Update tab UI
        const tabs = tabsContainerEl.querySelectorAll('.scanner-tab');
        tabs.forEach(tab => {
            if (tab.dataset.severity === severity) {
                tab.classList.add('active');
            } else {
                tab.classList.remove('active');
            }
        });

        // Filter and render issues
        let visibleCount = 0;
        if (severity === 'all') {
            if (cardsContainerEl) cardsContainerEl.style.display = 'none';
            renderOverview();
            visibleCount = (state.summary && Number.isFinite(Number(state.summary.total_issues)))
                ? Number(state.summary.total_issues)
                : (state.issues ? state.issues.length : 0);
        } else {
            if (cardsContainerEl) cardsContainerEl.style.display = 'none';
            if (severity === 'error') {
                const filteredIssues = state.issuesBySeverity.error || [];
                visibleCount = filteredIssues.length;
                renderIssuesList(filteredIssues);
                const extra = renderLoadMoreButton('error', state.issuesPaging.error.has_more, state.issuesPaging.error.loading);
                if (issuesListEl && extra) issuesListEl.insertAdjacentHTML('beforeend', extra);
            } else {
                const loaded = state.issuesBySeverity[severity];
                if (loaded === null) {
                    const by = (state.summary && state.summary.by_severity) ? state.summary.by_severity : {};
                    const cnt = Number(by[severity] || 0);
                    visibleCount = cnt;
                    if (cnt > 0) {
                        renderIssuesFetchPlaceholder(severity, false, '该级别默认不下发明细');
                    } else {
                        renderIssuesList([]);
                    }
                } else {
                    const list = Array.isArray(loaded) ? loaded : [];
                    visibleCount = list.length;
                    renderIssuesList(list);
                    const extra = renderLoadMoreButton(severity, state.issuesPaging[severity].has_more, state.issuesPaging[severity].loading);
                    if (issuesListEl && extra) issuesListEl.insertAdjacentHTML('beforeend', extra);
                }
            }
        }

        console.log(`[ScannerUI] Switched to ${severity} tab, showing ${visibleCount} issues`);
    }

    /**
     * Render the list of issues.
     * @param {Array} issues - Array of issue objects
     */
    function renderIssuesList(issues) {
        if (!issuesListEl) return;

        if (!issues || issues.length === 0) {
            // 没有问题时保持空白，避免与summary区域重复
            issuesListEl.innerHTML = '';
            return;
        }

        // Group issues by file for better organization
        const issuesByFile = new Map();
        issues.forEach(issue => {
            const file = issue.file || issue.file_path || 'Unknown';
            const list = issuesByFile.get(file) || [];
            list.push(issue);
            issuesByFile.set(file, list);
        });

        const severityRank = (sev) => {
            if (sev === 'error') return 0;
            if (sev === 'warning') return 1;
            if (sev === 'info') return 2;
            return 3;
        };

        const toInt = (v) => {
            const n = Number(v);
            return Number.isFinite(n) ? n : Number.MAX_SAFE_INTEGER;
        };

        const fileEntries = Array.from(issuesByFile.entries()).map(([file, fileIssues]) => {
            let errorCount = 0;
            let warningCount = 0;
            let infoCount = 0;
            for (const it of fileIssues) {
                const s = it.severity || 'info';
                if (s === 'error') errorCount++;
                else if (s === 'warning') warningCount++;
                else infoCount++;
            }
            return { file, fileIssues, errorCount, warningCount, infoCount, total: fileIssues.length };
        });

        fileEntries.sort((a, b) => {
            if (b.errorCount !== a.errorCount) return b.errorCount - a.errorCount;
            if (b.warningCount !== a.warningCount) return b.warningCount - a.warningCount;
            if (b.total !== a.total) return b.total - a.total;
            return String(a.file).localeCompare(String(b.file));
        });

        let html = '';
        for (const entry of fileEntries) {
            const file = entry.file;
            const fileIssues = entry.fileIssues;
            const fileName = file.split(/[/\\]/).pop() || file;
            const fileKey = encodeURIComponent(file);
            const collapsed = state.collapsedFileGroups.has(fileKey);

            const sortedIssues = [...fileIssues].sort((x, y) => {
                const sx = x.severity || 'info';
                const sy = y.severity || 'info';
                const sr = severityRank(sx) - severityRank(sy);
                if (sr !== 0) return sr;
                const lx = toInt(x.line || x.start_line);
                const ly = toInt(y.line || y.start_line);
                if (lx !== ly) return lx - ly;
                const cx = toInt(x.column);
                const cy = toInt(y.column);
                if (cx !== cy) return cx - cy;
                return String(x.rule_id || x.rule || '').localeCompare(String(y.rule_id || y.rule || ''));
            });

            html += `
                <div class="scanner-file-group ${collapsed ? 'collapsed' : ''}" data-file="${fileKey}">
                    <div class="file-group-header" data-file="${fileKey}">
                        <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                        <span class="file-name" title="${escapeHtml(file)}">${escapeHtml(fileName)}</span>
                        <span class="issue-counts">
                            ${entry.errorCount ? `<span class="count error">${entry.errorCount}</span>` : ''}
                            ${entry.warningCount ? `<span class="count warning">${entry.warningCount}</span>` : ''}
                            ${entry.infoCount ? `<span class="count info">${entry.infoCount}</span>` : ''}
                        </span>
                        <span class="issue-count">${entry.total}</span>
                    </div>
                    <div class="file-issues">
                        ${sortedIssues.map(issue => renderIssueCard(issue)).join('')}
                    </div>
                </div>
            `;
        }

        issuesListEl.innerHTML = html;
    }

    /**
     * Render a single issue card.
     * @param {Object} issue - Issue object
     * @returns {string} HTML string for the issue card
     */
    function renderIssueCard(issue) {
        const severity = issue.severity || 'info';
        const line = issue.line || issue.start_line || '-';
        const column = issue.column || '-';
        const message = issue.message || 'No description';
        const ruleId = issue.rule_id || issue.rule || '';
        const scanner = issue.scanner || '';

        return `
            <div class="issue-card severity-${severity}">
                <div class="issue-header">
                    <span class="severity-badge ${severity}">${getSeverityLabel(severity)}</span>
                    <span class="issue-location">行 ${line}${column !== '-' ? `:${column}` : ''}</span>
                    ${ruleId ? `<span class="issue-rule" title="${escapeHtml(ruleId)}">${escapeHtml(ruleId)}</span>` : ''}
                </div>
                <div class="issue-message">${escapeHtml(message)}</div>
                ${scanner ? `<div class="issue-scanner">via ${escapeHtml(scanner)}</div>` : ''}
            </div>
        `;
    }

    /**
     * Get display label for severity.
     * @param {string} severity - Severity level
     * @returns {string} Display label
     */
    function getSeverityLabel(severity) {
        switch (severity) {
            case 'error': return '错误';
            case 'warning': return '警告';
            case 'info': return '信息';
            default: return severity;
        }
    }

    // Expose public API
    return {
        init,
        reset,
        handleScannerProgress,
        handleScannerSummary,
        renderScannerCard,
        renderSummaryCard,
        updateScannerStatus,
        updateScanningFile,
        updateFileProgress,
        toggleScannerDetails,
        getState,
        getScannerNames,
        beginScanning,
        endScanning,
        switchSeverityTab,
        loadIssuesForSeverity,
        loadMoreIssues,
        toggleSection,
        // Edge case handling
        handleScannerTimeout,
        checkAllTimeouts,
        handleDisconnection,
        handleReconnection
    };
})();

// Export for use in main.js (if using modules) or make globally available
if (typeof window !== 'undefined') {
    window.ScannerUI = ScannerUI;
}

// Export for Node.js/testing environments
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ScannerUI;
}
