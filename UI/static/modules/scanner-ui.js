/**
 * Scanner Workflow UI Module
 * 
 * Handles the display of scanner execution progress and results in the workflow panel.
 * This module manages scanner state, renders scanner cards, and handles scanner events.
 * 
 * Requirements: 5.1, 5.2 - Modular scanner UI components with centralized event handling
 */

const ScannerUI = (function() {
    'use strict';

    // --- State Management ---
    const state = {
        /** @type {Map<string, ScannerState>} Map of scanner name to state */
        scanners: new Map(),
        /** @type {boolean} Whether any scanner is currently running */
        isScanning: false,
        /** @type {ScannerSummary|null} Summary data after all scanners complete */
        summary: null
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
        }
        
        // Reset state on init
        reset();
        
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
        
        // Clear DOM
        if (cardsContainerEl) {
            cardsContainerEl.innerHTML = '';
        }
        if (summaryContainerEl) {
            summaryContainerEl.style.display = 'none';
            summaryContainerEl.innerHTML = '';
        }
        if (progressIndicatorEl) {
            updateProgressIndicator(false);
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
            collapsed: false
        };
        
        state.scanners.set(scannerName, scannerState);
        state.isScanning = true;
        
        // Update UI
        renderScannerCard(scannerState);
        updateProgressIndicator(true);
        
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
        
        console.log(`[ScannerUI] Scanner error: ${scannerName}, error: ${scannerState.error}`);
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
        
        // Update UI
        state.isScanning = false;
        updateProgressIndicator(false);
        renderSummaryCard(state.summary);
        
        console.log('[ScannerUI] Summary received:', state.summary);
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
        
        cardEl.className = `scanner-card ${statusClass} ${collapsedClass}`;
        cardEl.innerHTML = `
            <div class="scanner-card-header" onclick="ScannerUI.toggleScannerDetails('${scanner.name}')">
                <span class="scanner-name">${escapeHtml(scanner.name)}</span>
                <span class="scanner-status ${statusClass}">${statusText}</span>
                <span class="scanner-chevron">▼</span>
            </div>
            <div class="scanner-card-body">
                ${scanner.file ? `<div class="scanner-file">扫描: ${escapeHtml(scanner.file)}</div>` : ''}
                ${scanner.duration_ms !== undefined ? `<div class="scanner-duration">耗时: ${formatDuration(scanner.duration_ms)}</div>` : ''}
                ${scanner.issue_count !== undefined ? `<div class="scanner-issues">问题: ${scanner.issue_count}</div>` : ''}
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

        const hasErrors = summary.by_severity.error > 0;
        const noIssues = summary.total_issues === 0;
        
        let summaryHTML = '';
        
        if (noIssues) {
            summaryHTML = `
                <div class="summary-header success">✓ 扫描完成</div>
                <div class="summary-message">未发现代码问题</div>
            `;
        } else {
            summaryHTML = `
                <div class="summary-header ${hasErrors ? 'has-errors' : ''}">扫描完成</div>
                <div class="summary-stats">
                    <span class="stat error ${hasErrors ? 'highlight' : ''}">${summary.by_severity.error} 错误</span>
                    <span class="stat warning">${summary.by_severity.warning} 警告</span>
                    <span class="stat info">${summary.by_severity.info} 提示</span>
                </div>
                <div class="summary-total">共 ${summary.total_issues} 个问题</div>
            `;
        }
        
        summaryContainerEl.innerHTML = summaryHTML;
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
        
        // Show/hide the entire section
        if (containerEl) {
            containerEl.style.display = state.scanners.size > 0 || isActive ? 'block' : 'none';
        }
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
            scanner.error = `扫描超时 (>${Math.round(timeoutMs/1000)}s)`;
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

    /**
     * Get all scanner names currently tracked.
     * @returns {string[]} Array of scanner names
     */
    function getScannerNames() {
        return Array.from(state.scanners.keys());
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
        toggleScannerDetails,
        getState,
        getScannerNames,
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
