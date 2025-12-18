/**
 * session.js - 会话管理模块
 */

const LAST_SESSION_REMINDER_ID = 'lastSessionReminderCard';

function renderReportPlaceholder(container) {
    if (!container) return;
    if (container.dataset && container.dataset.reportPlaceholder === 'hero') return;
    if (container.dataset) container.dataset.reportPlaceholder = 'hero';
    container.innerHTML = `
        <div class="empty-state">
            <div class="hero-animation" style="display:flex;">
                <svg class="hero-icon" viewBox="0 0 100 100" aria-hidden="true">
                    <path class="hero-path p1" d="M50 15 L85 35 L85 75 L50 95 L15 75 L15 35 Z" fill="none" stroke="currentColor" stroke-width="0.8"></path>
                    <path class="hero-path p2" d="M50 25 L75 40 L75 70 L50 85 L25 70 L25 40 Z" fill="none" stroke="currentColor" stroke-width="1.2"></path>
                    <circle class="hero-path c1" cx="50" cy="55" r="8" fill="none" stroke="currentColor" stroke-width="1.5"></circle>
                    <line class="hero-path l1" x1="50" y1="15" x2="50" y2="47" stroke="currentColor" stroke-width="1"></line>
                    <line class="hero-path l2" x1="50" y1="63" x2="50" y2="95" stroke="currentColor" stroke-width="1"></line>
                </svg>
                <div class="hero-project-name" data-text="DeltaConverge">DeltaConverge</div>
            </div>
        </div>
    `;
}

function getMessageContainer() {
    return document.getElementById('messageContainer');
}

function removeLastSessionReminder() {
    const card = document.getElementById(LAST_SESSION_REMINDER_ID);
    if (card) card.remove();
}

function renderLastSessionReminder(sessionData) {
    const messageContainer = getMessageContainer();
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
        continueBtn.onclick = () => loadSession(sessionId);
    }
    const dismissBtn = card.querySelector('.reminder-dismiss');
    if (dismissBtn) {
        dismissBtn.onclick = () => {
            removeLastSessionReminder();
            clearLastSessionId();
        };
    }

    messageContainer.prepend(card);
}

async function showLastSessionReminder() {
    if (window.currentSessionId) return;
    const lastSid = getLastSessionId();
    if (!lastSid) return;
    if (document.getElementById(LAST_SESSION_REMINDER_ID)) return;

    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(lastSid)}`);
        if (!res.ok) throw new Error('not found');
        const data = await res.json();

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

        const messages = data.messages || [];
        const hasReport = messages.some(m => m.role === 'assistant' && m.content);
        if (hasReport) {
            clearLastSessionId();
            return;
        }

        const events = data.workflow_events || [];
        if (events.length === 0) {
            return;
        }

        renderLastSessionReminder(data);
    } catch (e) {
        console.warn('Failed to fetch last session reminder:', e);
        clearLastSessionId();
    }
}

async function loadSessions() {
    const sessionListEl = document.getElementById('sessionList');
    if (!sessionListEl) return;

    sessionListEl.innerHTML = '<div class="loading-state">加载中...</div>';

    try {
        const projectRoot = window.currentProjectRoot;
        const url = projectRoot
            ? `/api/sessions/list?project_root=${encodeURIComponent(projectRoot)}`
            : '/api/sessions/list';

        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const sessions = data.sessions || [];

        if (!sessions || sessions.length === 0) {
            sessionListEl.innerHTML = '<div class="empty-state">暂无历史会话</div>';
            return;
        }

        sessionListEl.innerHTML = '';
        const lastSid = getLastSessionId();

        sessions.forEach(s => {
            const div = document.createElement("div");
            const isActive = s.session_id === window.currentSessionId;
            const isLast = s.session_id === lastSid;
            const isRunning = s.session_id === getRunningSessionId();
            const classes = ['session-item'];
            if (isActive) classes.push('active');
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

            // 生成状态徽章
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

        showLastSessionReminder();
    } catch (e) {
        console.error("Load sessions error:", e);
        sessionListEl.innerHTML = '<div class="error-state">加载失败</div>';
    }
}

async function loadSession(sid) {
    const messageContainer = document.getElementById('messageContainer');

    // Case 1: Clicking on running task session -> restore display
    if (isReviewRunning() && getRunningSessionId() === sid) {
        window.currentSessionId = sid;
        setViewingHistory(false);
        updateSessionActiveState(sid);
        switchPage('review');
        setLayoutState(LayoutState.COMPLETED);
        restoreRunningUISnapshot();
        showToast("已返回正在进行的审查任务", "info");
        startSessionPolling(sid);
        return;
    }

    // Case 2: Loading a different session while task is running
    if (isReviewRunning() && getRunningSessionId() !== sid) {
        saveRunningUISnapshot();
    }

    stopSessionPolling();
    window.currentSessionId = sid;
    setLastSessionId(sid);
    removeLastSessionReminder();
    updateSessionActiveState(sid);

    try {
        const res = await fetch(`/api/sessions/${sid}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const messages = data.messages || [];
        const metadata = data.metadata || {};
        const workflowEvents = data.workflow_events || [];

        // Update project path
        if (metadata.project_root) {
            updateProjectPath(metadata.project_root);
        }

        // Check if this is a completed review
        let lastAssistantMessage = null;
        for (let i = messages.length - 1; i >= 0; i--) {
            if (messages[i].role === 'assistant' && messages[i].content) {
                lastAssistantMessage = messages[i];
                break;
            }
        }

        const isCompletedReview = !!lastAssistantMessage;

        // Mark as viewing history if not the running session
        if (getRunningSessionId() !== sid) {
            setViewingHistory(true);
        } else {
            setViewingHistory(false);
        }

        // Switch to review page
        switchPage('review');

        // Clear message container and show welcome message
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

        // Handle completed review
        if (isCompletedReview) {
            setLayoutState(LayoutState.COMPLETED);

            const reportContainer = document.getElementById('reportContainer');
            if (reportContainer && lastAssistantMessage.content) {
                if (reportContainer.dataset) {
                    delete reportContainer.dataset.reportPlaceholder;
                }
                reportContainer.innerHTML = marked.parse(lastAssistantMessage.content);
            }
        } else if (workflowEvents.length > 0) {
            // 有workflow但没有最终报告：左侧不显示任何中间状态/解释，仅显示占位
            setLayoutState(LayoutState.COMPLETED);

            const reportContainer = document.getElementById('reportContainer');
            if (reportContainer) {
                renderReportPlaceholder(reportContainer);
            }
        } else {
            // 完全空的会话
            setLayoutState(LayoutState.INITIAL);
        }

        // 统一处理workflow显示（无论完成与否）
        const workflowEntries = document.getElementById('workflowEntries');
        if (workflowEntries && workflowEvents.length > 0) {
            workflowEntries.innerHTML = '';
            if (typeof replayWorkflowEvents === 'function') {
                replayWorkflowEvents(workflowEntries, workflowEvents);
            }
            if (typeof ScannerUI !== 'undefined' && typeof replayScannerEvents === 'function') {
                replayScannerEvents(workflowEvents);
            }
        }

    } catch (e) {
        console.error("Load session error:", e);
        showToast("加载会话失败: " + e.message, "error");
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

    SessionState.pollTimerId = setInterval(async () => {
        try {
            const res = await fetch(`/api/sessions/${sid}/status`);
            if (res.ok) {
                const status = await res.json();
                if (status.completed) {
                    stopSessionPolling();
                    loadSession(sid);
                }
            }
        } catch (e) {
            console.error("Session polling error:", e);
        }
    }, 3000);
}

function updateSessionActiveState(activeSessionId) {
    const items = document.querySelectorAll('.session-item');
    items.forEach(item => {
        if (item.dataset.sessionId === activeSessionId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}

function clearReviewPanels() {
    const workflowEntries = document.getElementById('workflowEntries');
    const monitorContent = document.getElementById('monitorContent');
    const reportContainer = document.getElementById('reportContainer');
    if (workflowEntries) workflowEntries.innerHTML = '';
    if (monitorContent) monitorContent.innerHTML = '';
    if (reportContainer) renderReportPlaceholder(reportContainer);
}

async function renameSession(sid, oldName) {
    const newName = prompt('请输入新的会话名称:', oldName);
    if (!newName || newName === oldName) return;
    try {
        const res = await fetch('/api/sessions/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sid, new_name: newName })
        });
        if (!res.ok) throw new Error('Rename failed');
        await loadSessions();
    } catch (e) {
        showToast('重命名失败: ' + e.message, 'error');
    }
}

async function deleteSession(sid) {
    if (!confirm('确定要删除此会话吗？此操作无法撤销。')) return;
    try {
        const res = await fetch('/api/sessions/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sid })
        });
        if (!res.ok) throw new Error('Delete failed');

        if (window.currentSessionId === sid) {
            returnToNewWorkspace();
        }

        if (typeof getRunningSessionId === 'function' && getRunningSessionId() === sid) {
            if (typeof endReviewTask === 'function') endReviewTask();
        }

        await loadSessions();
        showToast('会话已删除', 'success');
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

function generateSessionId() {
    return 'sess_' + Date.now();
}

async function createAndRefreshSession(projectRoot = null, switchToPage = false) {
    const newId = generateSessionId();

    if (typeof setViewingHistory === 'function') setViewingHistory(false);
    if (typeof setLayoutState === 'function') setLayoutState(LayoutState.INITIAL);

    const messageContainer = document.getElementById('messageContainer');
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

    clearReviewPanels();
    if (typeof resetProgress === 'function') resetProgress();
    if (switchToPage && typeof switchPage === 'function') switchPage('review');

    try {
        const res = await fetch('/api/sessions/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: newId,
                project_root: projectRoot || window.currentProjectRoot
            })
        });

        if (res.ok) {
            window.currentSessionId = newId;
            if (typeof setLastSessionId === 'function') setLastSessionId(newId);
            await loadSessions();
            updateSessionActiveState(newId);
            showToast('已创建新会话', 'success');
        } else {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
    } catch (e) {
        console.error('Failed to create session:', e);
        showToast('创建会话失败: ' + e.message, 'error');
        window.currentSessionId = newId;
    }

    return newId;
}

function returnToNewWorkspace() {
    if (typeof isReviewRunning === 'function' && isReviewRunning()) {
        if (typeof saveRunningUISnapshot === 'function') saveRunningUISnapshot();
        showToast('审查任务继续在后台运行，可从历史记录返回', 'info');
    }

    stopSessionPolling();
    window.currentSessionId = null;

    if (typeof setLayoutState === 'function') setLayoutState(LayoutState.INITIAL);

    const messageContainer = document.getElementById('messageContainer');
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

    clearReviewPanels();
    if (typeof resetProgress === 'function') resetProgress();
    if (typeof setViewingHistory === 'function') setViewingHistory(false);
    updateSessionActiveState(null);
    if (typeof updateBackgroundTaskIndicator === 'function') updateBackgroundTaskIndicator();

    const historyDrawer = document.getElementById('historyDrawer');
    if (historyDrawer) historyDrawer.classList.remove('open');
}

function toggleHistoryDrawer() {
    const historyDrawer = document.getElementById('historyDrawer');
    if (!historyDrawer) return;
    const isOpening = !historyDrawer.classList.contains('open');
    historyDrawer.classList.toggle('open');
    if (isOpening) {
        loadSessions();
    }
}

function goToBackgroundTask() {
    const runningSessionId = typeof getRunningSessionId === 'function' ? getRunningSessionId() : null;
    if (runningSessionId) {
        loadSession(runningSessionId);
    }
}

function exitHistoryMode() {
    returnToNewWorkspace();
}

function switchToBackgroundTask() {
    goToBackgroundTask();
}

window.loadSessions = loadSessions;
window.loadSession = loadSession;
window.stopSessionPolling = stopSessionPolling;
window.startSessionPolling = startSessionPolling;
window.updateSessionActiveState = updateSessionActiveState;
window.renameSession = renameSession;
window.deleteSession = deleteSession;
window.generateSessionId = generateSessionId;
window.createAndRefreshSession = createAndRefreshSession;
window.returnToNewWorkspace = returnToNewWorkspace;
window.exitHistoryMode = exitHistoryMode;
window.toggleHistoryDrawer = toggleHistoryDrawer;
window.goToBackgroundTask = goToBackgroundTask;
window.switchToBackgroundTask = switchToBackgroundTask;
window.showLastSessionReminder = showLastSessionReminder;
window.removeLastSessionReminder = removeLastSessionReminder;

