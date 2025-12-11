/**
 * session.js - 会话管理模块
 */

const LAST_SESSION_REMINDER_ID = 'lastSessionReminderCard';

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
        const res = await fetch('/api/sessions/list');
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
                reportContainer.innerHTML = marked.parse(lastAssistantMessage.content);
            }
        } else if (workflowEvents.length > 0) {
            // 中断的会话：有workflow但没有最终报告
            setLayoutState(LayoutState.COMPLETED);

            const reportContainer = document.getElementById('reportContainer');
            if (reportContainer) {
                // 查找错误信息
                let errorMessage = '';
                for (let i = workflowEvents.length - 1; i >= 0; i--) {
                    const evt = workflowEvents[i];
                    if (evt.type === 'error' && evt.message) {
                        errorMessage = evt.message;
                        break;
                    }
                }

                const errorDetail = errorMessage
                    ? `<p class="error-detail"><strong>错误原因：</strong>${escapeHtml(errorMessage)}</p>`
                    : '';

                reportContainer.innerHTML = `
                    <div class="interrupted-session-notice">
                        <div class="notice-icon">${getIcon('alert-triangle')}</div>
                        <div class="notice-content">
                            <h3>会话已中断</h3>
                            <p>此会话在执行过程中被中断，未能生成最终审查报告。</p>
                            ${errorDetail}
                            <p class="notice-hint">您可以在左侧工作流面板中查看已完成的工作进度。</p>
                        </div>
                    </div>
                `;
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

async function renameSession(sid, oldName) {
    const newName = prompt('请输入新名称:', oldName);
    if (!newName || newName === oldName) return;

    try {
        const res = await fetch('/api/sessions/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sid, new_name: newName })
        });
        if (!res.ok) throw new Error('Rename failed');
        loadSessions();
        showToast('重命名成功', 'success');
    } catch (e) {
        showToast('重命名失败', 'error');
    }
}

async function deleteSession(sid) {
    if (!confirm('确定要删除此会话吗？')) return;

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

        if (getRunningSessionId() === sid) {
            endReviewTask();
        }

        loadSessions();
        showToast('会话已删除', 'success');
    } catch (e) {
        showToast('删除失败', 'error');
    }
}

function generateSessionId() {
    return 'sess_' + Date.now();
}

async function createAndRefreshSession(projectRoot = null, switchToPage = false) {
    const newId = generateSessionId();

    // 退出历史浏览模式并重置布局
    setViewingHistory(false);
    setLayoutState(LayoutState.INITIAL);
    resetProgress();

    const workflowEntries = document.getElementById('workflowEntries');
    const monitorContent = document.getElementById('monitorContent');
    const reportContainer = document.getElementById('reportContainer');
    if (workflowEntries) workflowEntries.innerHTML = '';
    if (monitorContent) monitorContent.innerHTML = '';
    if (reportContainer) {
        reportContainer.innerHTML = '<div class="waiting-state"><p>等待审查结果...</p></div>';
    }

    if (projectRoot) {
        updateProjectPath(projectRoot);
    }

    if (switchToPage) {
        switchPage('review');
    }

    // 调用后端创建会话，保持与 main.js 一致
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
            setLastSessionId(newId);
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
        // 失败时仅在前端设置，兼容旧逻辑
        window.currentSessionId = newId;
    }

    return newId;
}

function returnToNewWorkspace() {
    stopSessionPolling();
    window.currentSessionId = null;

    setLayoutState(LayoutState.INITIAL);
    resetProgress();

    const workflowEntries = document.getElementById('workflowEntries');
    const monitorContent = document.getElementById('monitorContent');
    const reportContainer = document.getElementById('reportContainer');

    if (workflowEntries) workflowEntries.innerHTML = '';
    if (monitorContent) monitorContent.innerHTML = '';
    if (reportContainer) reportContainer.innerHTML = '<div class="waiting-state"><p>等待审查结果...</p></div>';

    updateProjectPath('');
    setViewingHistory(false);
    updateSessionActiveState(null);
    updateBackgroundTaskIndicator();

    const historyDrawer = document.getElementById('historyDrawer');
    if (historyDrawer) historyDrawer.classList.remove('open');
}

function toggleHistoryDrawer() {
    const historyDrawer = document.getElementById('historyDrawer');
    if (historyDrawer) {
        const isOpening = !historyDrawer.classList.contains("open");
        historyDrawer.classList.toggle("open");
        if (isOpening) {
            loadSessions();
        }
    }
}

function goToBackgroundTask() {
    const runningSessionId = getRunningSessionId();
    if (runningSessionId) {
        loadSession(runningSessionId);
    }
}

// Aliases
function exitHistoryMode() {
    returnToNewWorkspace();
}

function switchToBackgroundTask() {
    goToBackgroundTask();
}

// Export to window
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
