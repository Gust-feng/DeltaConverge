/**
 * review.js - 审查核心逻辑模块
 * 包含 startReview, sendMessage, handleSSEResponse 等核心函数
 */

// 思考计时器
let thoughtTimerInterval = null;

async function startReview() {
    if (!window.currentProjectRoot) {
        showToast("请先选择项目文件夹！", "error");
        return;
    }

    switchPage('review');

    const startReviewBtn = document.getElementById('startReviewBtn');
    const reportContainer = document.getElementById('reportContainer');

    if (startReviewBtn) {
        startReviewBtn.disabled = true;
        startReviewBtn.innerHTML = '<span class="spinner"></span>';
    }

    const reviewProjectPath = document.getElementById('reviewProjectPath');
    if (reviewProjectPath) {
        reviewProjectPath.textContent = window.currentProjectRoot;
        reviewProjectPath.title = window.currentProjectRoot;
    }

    setLayoutState(LayoutState.COMPLETED);
    if (reportContainer) {
        reportContainer.innerHTML = '<div class="empty-state"><p>正在生成审查报告，大约需要 3-5 分钟</p></div>';
    }

    const workflowEntries = document.getElementById('workflowEntries');
    if (workflowEntries) {
        workflowEntries.innerHTML = '';
    }

    resetProgress();
    setProgressStep('init', 'completed');
    setProgressStep('analysis', 'active');

    startReviewTimer();

    if (!window.currentSessionId) {
        window.currentSessionId = generateSessionId();
        setLastSessionId(window.currentSessionId);
    }

    startReviewTask(window.currentSessionId);
    SessionState.reviewStreamActive = true;

    const tools = Array.from(document.querySelectorAll('#toolListContainer input:checked')).map(cb => cb.value);
    const autoApproveInput = document.getElementById('autoApprove');
    const autoApprove = autoApproveInput ? autoApproveInput.checked : false;

    try {
        const response = await fetch("/api/review/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                project_root: window.currentProjectRoot,
                model: window.currentModelValue,
                tools: tools,
                agents: null,
                autoApprove: autoApprove,
                session_id: window.currentSessionId,
                enableStaticScan: false,
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        await handleSSEResponse(response, window.currentSessionId);

    } catch (e) {
        console.error("Start review error:", e);
        addSystemMessage("启动审查失败: " + escapeHtml(e.message));

        setLayoutState(LayoutState.INITIAL);
        SessionState.reviewStreamActive = false;
        endReviewTask();

        if (startReviewBtn) {
            startReviewBtn.disabled = false;
            startReviewBtn.innerHTML = getIcon('send');
        }
    }
}

async function sendMessage() {
    const promptInput = document.getElementById('prompt');
    if (!promptInput) return;
    const text = promptInput.value.trim();
    if (!text) return;

    promptInput.value = "";
    addMessage("user", escapeHtml(text));

    if (!window.currentSessionId) {
        window.currentSessionId = generateSessionId();
        setLastSessionId(window.currentSessionId);
    }

    const tools = Array.from(document.querySelectorAll('#toolListContainer input:checked')).map(cb => cb.value);
    const autoApproveInput = document.getElementById('autoApprove');
    const autoApprove = autoApproveInput ? autoApproveInput.checked : false;

    try {
        const response = await fetch("/api/chat/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: window.currentSessionId,
                message: text,
                project_root: window.currentProjectRoot,
                model: window.currentModelValue,
                tools: tools,
                autoApprove: autoApprove
            })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        await handleSSEResponse(response, window.currentSessionId);

    } catch (e) {
        console.error("Send message error:", e);
        addMessage("system", `<p>发送失败: ${escapeHtml(e.message)}</p>`);
    }
}

function routeEvent(evt) {
    return 'workflow';
}

async function handleSSEResponse(response, expectedSessionId = null) {
    if (!response.body) {
        console.error("Response body is null");
        return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const workflowContent = document.querySelector('#workflowPanel .workflow-content');
    const workflowEntries = document.getElementById('workflowEntries') || workflowContent;
    if (workflowEntries) workflowEntries.innerHTML = '';

    const monitorContainer = document.querySelector('#monitorPanel .workflow-content');
    const monitorEntries = document.getElementById('monitorContent') || monitorContainer;
    if (monitorEntries) monitorEntries.innerHTML = '';

    if (typeof ScannerUI !== 'undefined') {
        try { ScannerUI.reset(); } catch (e) { }
    }

    const monitorPanel = document.getElementById('monitorPanel');
    if (monitorPanel) {
        monitorPanel.classList.remove('ok', 'error');
        const titleEl = monitorPanel.querySelector('.panel-title');
        if (titleEl) titleEl.textContent = '日志';
    }

    const reportCanvasContainer = document.getElementById('reportContainer');
    const startReviewBtn = document.getElementById('startReviewBtn');

    let finalReportContent = '';
    let pendingChunkContent = '';
    let streamEnded = false;
    const sid = expectedSessionId || window.currentSessionId;
    stopSessionPolling();
    SessionState.reviewStreamActive = true;

    let currentStage = null;
    let fallbackSeen = false;
    let errorSeen = false;
    let currentChunkEl = null;
    let currentThoughtEl = null;
    let thoughtStartTime = null;
    const toolCallEntries = new Map();

    function getStageInfo(stage) {
        const stageMap = {
            'intent': { title: '意图分析', icon: 'bot', color: '#6366f1' },
            'planner': { title: '审查规划', icon: 'plan', color: '#8b5cf6' },
            'review': { title: '代码审查', icon: 'review', color: '#10b981' },
            'default': { title: '处理中', icon: 'settings', color: '#64748b' }
        };
        return stageMap[stage] || stageMap['default'];
    }

    function createStageHeader(stage) {
        const info = getStageInfo(stage);
        const header = document.createElement('div');
        header.className = 'workflow-stage-section';
        header.dataset.stage = stage;
        header.innerHTML = `
            <div class="stage-header collapsible" onclick="toggleStageSection(this)">
                <div class="stage-indicator" style="--stage-color: ${info.color}">
                    ${getIcon(info.icon)}
                    <span>${info.title}</span>
                </div>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="stage-content"></div>
        `;
        return header;
    }

    function getCurrentStageContent() {
        const sections = workflowEntries.querySelectorAll('.workflow-stage-section');
        const lastSection = sections[sections.length - 1];
        return lastSection ? lastSection.querySelector('.stage-content') : workflowEntries;
    }

    function startThoughtTimer(timerEl) {
        thoughtStartTime = Date.now();
        if (thoughtTimerInterval) clearInterval(thoughtTimerInterval);
        thoughtTimerInterval = setInterval(() => {
            if (timerEl && thoughtStartTime) {
                const elapsed = Math.floor((Date.now() - thoughtStartTime) / 1000);
                const mins = Math.floor(elapsed / 60);
                const secs = elapsed % 60;
                timerEl.textContent = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
            }
        }, 1000);
    }

    function stopThoughtTimer() {
        if (thoughtTimerInterval) {
            clearInterval(thoughtTimerInterval);
            thoughtTimerInterval = null;
        }
    }

    function liveFollowScroll() {
        const scrollContainer = document.querySelector('#workflowPanel .workflow-content');
        if (scrollContainer) scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }

    function liveFollowCollapse(el) {
        if (el && !el.classList.contains('collapsed')) el.classList.add('collapsed');
    }

    function truncateText(text, max = 240) {
        const safe = text == null ? '' : String(text);
        return safe.length > max ? `${safe.slice(0, max)}...` : safe;
    }

    function formatToolArgs(rawArgs) {
        if (rawArgs === undefined || rawArgs === null || rawArgs === '') {
            return '<span class="tool-args-empty">无参数</span>';
        }
        let parsed = rawArgs;
        if (typeof rawArgs === 'string') {
            try { parsed = JSON.parse(rawArgs); } catch (_) { }
        }
        if (typeof parsed === 'object') {
            const entries = Array.isArray(parsed) ? parsed.map((v, i) => [`#${i}`, v]) : Object.entries(parsed);
            const limited = entries.slice(0, 6);
            const pills = limited.map(([k, v]) => {
                const valueText = typeof v === 'object' ? JSON.stringify(v) : String(v ?? '');
                return `<span class="kv-pill"><span class="kv-key">${escapeHtml(truncateText(k, 40))}</span><span class="kv-value">${escapeHtml(truncateText(valueText, 160))}</span></span>`;
            }).join('');
            const more = entries.length > limited.length ? '<span class="kv-pill muted">...</span>' : '';
            return `<div class="kv-pills">${pills}${more}</div>`;
        }
        return `<code class="mono">${escapeHtml(truncateText(parsed, 200))}</code>`;
    }

    function getToolKey(evt) {
        if (evt.tool_call_id) return `id-${evt.tool_call_id}`;
        const callIdx = evt.call_index ?? 'x';
        const toolName = evt.tool_name || evt.tool || 'tool';
        const argsStr = typeof evt.arguments === 'string' ? evt.arguments : JSON.stringify(evt.arguments || '');
        let hash = 0;
        for (let i = 0; i < argsStr.length; i++) {
            hash = ((hash << 5) - hash) + argsStr.charCodeAt(i);
            hash = hash & hash;
        }
        return `${callIdx}-${toolName}-${hash}`;
    }

    function ensureToolCard(stageContent, evt) {
        const key = getToolKey(evt);
        const name = evt.tool_name || evt.tool || '未知工具';
        let entry = toolCallEntries.get(key);
        if (entry) return entry;

        const card = document.createElement('div');
        card.className = 'workflow-tool';
        card.dataset.callKey = key;
        card.innerHTML = `
            <div class="tool-head">
                <div class="tool-title">
                    ${getIcon('terminal')}
                    <div class="tool-title-text">
                        <span class="tool-name">${escapeHtml(name)}</span>
                        ${evt.call_index !== undefined && evt.call_index !== null ? `<span class="tool-badge">#${escapeHtml(String(evt.call_index))}</span>` : ''}
                    </div>
                </div>
                <span class="tool-status status-running">调用中</span>
            </div>
            <div class="tool-section tool-args">${formatToolArgs(evt.arguments || evt.detail)}</div>
            <div class="tool-section tool-output" style="display:none"></div>
            <div class="tool-section tool-meta" style="display:none"></div>
        `;
        stageContent.appendChild(card);

        entry = {
            key, card,
            statusEl: card.querySelector('.tool-status'),
            argsEl: card.querySelector('.tool-args'),
            outputEl: card.querySelector('.tool-output'),
            metaEl: card.querySelector('.tool-meta'),
            name,
        };
        toolCallEntries.set(key, entry);
        return entry;
    }

    function setToolStatus(entry, status, label) {
        if (!entry || !entry.statusEl) return;
        entry.statusEl.className = `tool-status status-${status}`;
        entry.statusEl.textContent = label;
    }

    function updateToolMeta(entry, evt) {
        if (!entry || !entry.metaEl) return;
        const chips = [];
        if (evt.duration_ms !== undefined && evt.duration_ms !== null) {
            chips.push(`<span class="meta-chip">耗时 ${Math.round(evt.duration_ms)}ms</span>`);
        }
        if (chips.length === 0) return;
        entry.metaEl.innerHTML = chips.join('');
        entry.metaEl.style.display = 'flex';
    }

    function renderToolContent(toolName, rawContent) {
        if (rawContent === undefined || rawContent === null || rawContent === '') {
            return '<span class="tool-empty">无返回内容</span>';
        }
        let data = rawContent;
        if (typeof rawContent === 'string') {
            try { data = JSON.parse(rawContent); } catch (_) { }
        }
        if (data && typeof data === 'object' && data.error) {
            return `<div class="tool-result error">${escapeHtml(String(data.error))}</div>`;
        }
        if (typeof data === 'object') {
            const jsonStr = JSON.stringify(data, null, 2);
            return `<pre class="tool-json"><code>${escapeHtml(truncateText(jsonStr, 3000))}</code></pre>`;
        }
        return `<pre class="tool-text"><code>${escapeHtml(truncateText(String(rawContent), 2000))}</code></pre>`;
    }

    function updateToolOutput(entry, evt) {
        if (!entry || !entry.outputEl) return;
        const hasError = !!evt.error;
        let body;
        if (hasError) {
            body = `<div class="tool-result error">${escapeHtml(String(evt.error))}</div>`;
        } else {
            body = `<div class="tool-result success">${renderToolContent(entry.name, evt.content)}</div>`;
        }
        entry.outputEl.innerHTML = body;
        entry.outputEl.style.display = 'block';
        setToolStatus(entry, hasError ? 'error' : 'success', hasError ? '失败' : '完成');
        updateToolMeta(entry, evt);
    }

    function getStageInfo(stage) {
        const stageMap = {
            'intent': { title: '意图分析', icon: 'bot', color: '#6366f1' },
            'planner': { title: '审查规划', icon: 'plan', color: '#8b5cf6' },
            'review': { title: '代码审查', icon: 'review', color: '#10b981' },
            'default': { title: '处理中', icon: 'settings', color: '#64748b' }
        };
        return stageMap[stage] || stageMap['default'];
    }

    function createStageHeader(stage) {
        const info = getStageInfo(stage);
        const header = document.createElement('div');
        header.className = 'workflow-stage-section';
        header.dataset.stage = stage;
        header.innerHTML = `
            <div class="stage-header collapsible" onclick="toggleStageSection(this)">
                <div class="stage-indicator" style="--stage-color: ${info.color}">
                    ${getIcon(info.icon)}
                    <span>${info.title}</span>
                </div>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="stage-content"></div>
        `;
        return header;
    }

    function getCurrentStageContent() {
        const sections = workflowEntries.querySelectorAll('.workflow-stage-section');
        const lastSection = sections[sections.length - 1];
        return lastSection ? lastSection.querySelector('.stage-content') : null;
    }

    function appendToWorkflow(evt) {
        if (!workflowEntries) return;

        const stage = evt.stage || 'review';

        if (stage !== currentStage) {
            currentStage = stage;
            currentChunkEl = null;
            currentThoughtEl = null;
            stopThoughtTimer();
            workflowEntries.appendChild(createStageHeader(stage));
        }

        const stageContent = getCurrentStageContent();

        if (evt.type === 'thought') {
            const thoughtText = (evt.content || '').trim();
            if (!thoughtText) return;
            if (!currentThoughtEl) {
                currentThoughtEl = document.createElement('div');
                currentThoughtEl.className = 'workflow-thought';
                currentThoughtEl.innerHTML = `
                    <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                        ${getIcon('bot')}
                        <span>思考过程</span>
                        <span class="thought-timer">0s</span>
                        <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                    </div>
                    <div class="thought-body"><pre class="thought-text"></pre></div>
                `;
                stageContent.appendChild(currentThoughtEl);
                const timerEl = currentThoughtEl.querySelector('.thought-timer');
                startThoughtTimer(timerEl);
            }
            const textEl = currentThoughtEl.querySelector('.thought-text');
            textEl.textContent = (textEl.textContent || '') + thoughtText;
            const thoughtBody = currentThoughtEl.querySelector('.thought-body');
            if (thoughtBody) thoughtBody.scrollTop = thoughtBody.scrollHeight;
            liveFollowScroll();
            return;
        }

        if (evt.type === 'chunk') {
            stopThoughtTimer();
            if (currentThoughtEl) liveFollowCollapse(currentThoughtEl);

            if (stage === 'review') {
                if (getLayoutState() !== LayoutState.COMPLETED) {
                    setLayoutState(LayoutState.COMPLETED);
                    setProgressStep('analysis', 'completed');
                    setProgressStep('planning', 'completed');
                    setProgressStep('reviewing', 'active');
                }

                const chunkContent = evt.content || '';
                pendingChunkContent += chunkContent;

                if (reportCanvasContainer) {
                    reportCanvasContainer.innerHTML = marked.parse(finalReportContent + pendingChunkContent);
                    reportCanvasContainer.scrollTop = reportCanvasContainer.scrollHeight;
                }
                return;
            }

            if (!currentChunkEl) {
                const wrapper = document.createElement('div');
                wrapper.className = 'workflow-chunk-wrapper collapsed';
                const chunkTitle = stage === 'planner' ? '上下文决策' : '输出内容';
                wrapper.innerHTML = `
                    <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                        ${getIcon('folder')}
                        <span>${chunkTitle}</span>
                        <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                    </div>
                    <div class="chunk-body">
                        <div class="workflow-chunk markdown-body"></div>
                    </div>
                `;
                stageContent.appendChild(wrapper);
                currentChunkEl = wrapper.querySelector('.workflow-chunk');
                currentChunkEl.dataset.fullText = '';
            }

            currentChunkEl.dataset.fullText += (evt.content || '');
            currentChunkEl.innerHTML = marked.parse(currentChunkEl.dataset.fullText);
            workflowEntries.scrollTop = workflowEntries.scrollHeight;
            return;
        }

        if (currentChunkEl) {
            const wrapper = currentChunkEl.closest('.workflow-chunk-wrapper');
            if (wrapper) liveFollowCollapse(wrapper);
        }
        currentChunkEl = null;
        if (currentThoughtEl) liveFollowCollapse(currentThoughtEl);
        stopThoughtTimer();

        if (evt.type === 'tool_start' || evt.type === 'tool_call_start' || evt.type === 'tool_result' || evt.type === 'tool_call_end') {
            currentThoughtEl = null;
            currentChunkEl = null;

            if (stage === 'review' && pendingChunkContent) {
                if (reportCanvasContainer) {
                    reportCanvasContainer.innerHTML = finalReportContent
                        ? marked.parse(finalReportContent)
                        : '<div class="waiting-state"><p>等待审查结果...</p></div>';
                }

                const trimmedContent = pendingChunkContent.trim();
                if (trimmedContent) {
                    const explanationEl = document.createElement('div');
                    explanationEl.className = 'workflow-tool-explanation';
                    explanationEl.innerHTML = `<div class="tool-explanation-content markdown-body">${marked.parse(trimmedContent)}</div>`;
                    stageContent.appendChild(explanationEl);
                }
                pendingChunkContent = '';
            }

            const entry = ensureToolCard(stageContent, evt);
            if (evt.type === 'tool_result') {
                updateToolOutput(entry, evt);
            } else if (evt.type === 'tool_call_end') {
                setToolStatus(entry, evt.success === false ? 'error' : 'success', evt.success === false ? '失败' : '完成');
                updateToolMeta(entry, evt);
            } else {
                if (entry.argsEl && (evt.arguments || evt.detail)) {
                    entry.argsEl.innerHTML = formatToolArgs(evt.arguments || evt.detail);
                }
                setToolStatus(entry, 'running', '调用中');
            }
            liveFollowScroll();
            return;
        }

        if (evt.content) {
            const block = document.createElement('div');
            block.className = 'workflow-block markdown-body';
            block.innerHTML = marked.parse(evt.content);
            stageContent.appendChild(block);
            workflowEntries.scrollTop = workflowEntries.scrollHeight;
        }
    }

    let saveStateTimer = null;
    function scheduleSaveState() {
        if (saveStateTimer) return;
        saveStateTimer = setTimeout(() => {
            saveRunningUISnapshot();
            saveStateTimer = null;
        }, 500);
    }

    const processEvent = (evt) => {
        scheduleSaveState();
        const stage = evt.stage || 'review';

        if (evt.type === 'thought' || evt.type === 'tool_start' || evt.type === 'chunk') {
            if (stage === 'intent') {
                setProgressStep('analysis', 'active');
            } else if (stage === 'review') {
                setProgressStep('analysis', 'completed');
                setProgressStep('planning', 'completed');
                setProgressStep('reviewing', 'active');
                if (getLayoutState() !== LayoutState.COMPLETED) {
                    setLayoutState(LayoutState.COMPLETED);
                }
            } else if (stage === 'planner') {
                setProgressStep('analysis', 'completed');
                setProgressStep('planning', 'active');
            }
        }

        if (evt.type === 'pipeline_stage_start') {
            const pipelineStage = evt.stage;
            if (pipelineStage === 'intent_analysis') setProgressStep('analysis', 'active');
            else if (pipelineStage === 'planner') { setProgressStep('analysis', 'completed'); setProgressStep('planning', 'active'); }
            else if (pipelineStage === 'fusion' || pipelineStage === 'context_provider' || pipelineStage === 'reviewer') {
                setProgressStep('analysis', 'completed');
                setProgressStep('planning', 'completed');
                setProgressStep('reviewing', 'active');
                if (getLayoutState() !== LayoutState.COMPLETED) setLayoutState(LayoutState.COMPLETED);
            }
            return;
        }

        if (evt.type === 'pipeline_stage_end') {
            const pipelineStage = evt.stage;
            if (pipelineStage === 'intent_analysis') setProgressStep('analysis', 'completed');
            else if (pipelineStage === 'planner') setProgressStep('planning', 'completed');
            else if (pipelineStage === 'reviewer') { setProgressStep('reviewing', 'completed'); setProgressStep('reporting', 'active'); }
            return;
        }

        if (evt.type === 'bundle_item') return;

        if (evt.type === 'scanner_progress') {
            if (typeof ScannerUI !== 'undefined') {
                ScannerUI.handleScannerProgress(evt);
                const scannerSection = document.getElementById('scannerWorkflowSection');
                if (scannerSection) scannerSection.classList.add('active');
                if (evt.status === 'start') setProgressStep('analysis', 'active');
            }
            return;
        }

        if (evt.type === 'scanner_issues_summary') {
            if (typeof ScannerUI !== 'undefined') ScannerUI.handleScannerSummary(evt);
            return;
        }

        if (evt.type === 'thought' || evt.type === 'tool_start' || evt.type === 'tool_result' || evt.type === 'tool_call_end' || evt.type === 'chunk' || evt.type === 'workflow_chunk' || evt.type === 'tool_call_start') {
            appendToWorkflow(evt);
            return;
        }

        if (evt.type === 'delta') {
            const stageContent = getCurrentStageContent();
            const reasoning = (evt.reasoning_delta || '').trim();
            const contentDelta = evt.content_delta || '';
            const callsRaw = evt.tool_calls_delta;
            const calls = Array.isArray(callsRaw) ? callsRaw : (callsRaw ? [callsRaw] : []);

            if (calls.length) {
                if (stage === 'review' && pendingChunkContent) {
                    if (reportCanvasContainer) {
                        reportCanvasContainer.innerHTML = finalReportContent
                            ? marked.parse(finalReportContent)
                            : '<div class="waiting-state"><p>等待审查结果...</p></div>';
                    }
                    const trimmedContent = pendingChunkContent.trim();
                    if (trimmedContent) {
                        const explanationEl = document.createElement('div');
                        explanationEl.className = 'workflow-tool-explanation';
                        explanationEl.innerHTML = `<div class="tool-explanation-content markdown-body">${marked.parse(trimmedContent)}</div>`;
                        stageContent.appendChild(explanationEl);
                    }
                    pendingChunkContent = '';
                }
                currentChunkEl = null;

                for (const call of calls) {
                    const fn = (typeof call.function === 'object') ? call.function : {};
                    const name = fn.name || call.name || '未知工具';
                    const argText = fn.arguments || '';
                    const entry = ensureToolCard(stageContent, {
                        tool_name: name,
                        arguments: argText,
                        call_index: call.index ?? call.call_index,
                    });
                    if (entry.argsEl) entry.argsEl.innerHTML = formatToolArgs(argText);
                    setToolStatus(entry, 'running', '调用中');
                }
            }

            if (reasoning) {
                if (!currentThoughtEl) {
                    currentThoughtEl = document.createElement('div');
                    currentThoughtEl.className = 'workflow-thought collapsed';
                    currentThoughtEl.innerHTML = `
                        <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                            ${getIcon('bot')}
                            <span>思考过程</span>
                            <span class="thought-timer">0s</span>
                            <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                        </div>
                        <div class="thought-body"><pre class="thought-text"></pre></div>
                    `;
                    stageContent.appendChild(currentThoughtEl);
                    const timerEl = currentThoughtEl.querySelector('.thought-timer');
                    startThoughtTimer(timerEl);
                }
                const textEl = currentThoughtEl.querySelector('.thought-text');
                textEl.textContent = (textEl.textContent || '') + reasoning;
            }

            if (contentDelta) {
                if (stage === 'review') {
                    if (getLayoutState() !== LayoutState.COMPLETED) {
                        setLayoutState(LayoutState.COMPLETED);
                        setProgressStep('analysis', 'completed');
                        setProgressStep('planning', 'completed');
                        setProgressStep('reviewing', 'active');
                    }
                    pendingChunkContent += contentDelta;
                    if (reportCanvasContainer) {
                        reportCanvasContainer.innerHTML = marked.parse(finalReportContent + pendingChunkContent);
                        reportCanvasContainer.scrollTop = reportCanvasContainer.scrollHeight;
                    }
                } else {
                    if (!currentChunkEl) {
                        const wrapper = document.createElement('div');
                        wrapper.className = 'workflow-chunk-wrapper collapsed';
                        wrapper.innerHTML = `
                            <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                                ${getIcon('folder')}
                                <span>输出内容</span>
                                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                            </div>
                            <div class="chunk-body">
                                <div class="workflow-chunk markdown-body"></div>
                            </div>
                        `;
                        stageContent.appendChild(wrapper);
                        currentChunkEl = wrapper.querySelector('.workflow-chunk');
                        currentChunkEl.dataset.fullText = '';
                    }
                    currentChunkEl.dataset.fullText += contentDelta;
                    currentChunkEl.innerHTML = marked.parse(currentChunkEl.dataset.fullText);
                }
            }

            workflowEntries.scrollTop = workflowEntries.scrollHeight;
            return;
        }

        if (evt.type === 'warning' && monitorEntries) {
            const s = evt.fallback_summary || {};
            const container = document.createElement('div');
            container.className = 'fallback-summary';
            container.innerHTML = `<div class="summary-header">${getIcon('clock')}<span>回退统计</span></div><div class="summary-stat"><span class="stat-label">总回退次数</span><span class="stat-value">${s.total || 0}</span></div>`;
            monitorEntries.appendChild(container);
            fallbackSeen = true;
            if (monitorPanel) {
                monitorPanel.classList.remove('ok');
                if (monitorPanel.classList.contains('collapsed')) monitorPanel.classList.remove('collapsed');
            }
            return;
        }

        if (evt.type === 'usage_summary' && monitorEntries) {
            const call = evt.call_usage || {};
            const totals = evt.session_usage || {};
            SessionState.lastSessionUsage = totals;
            const callIndex = evt.call_index;
            const item = document.createElement('div');
            item.className = 'process-item api-call-card';
            const idx = (callIndex !== undefined && callIndex !== null) ? `#${callIndex}` : '';
            item.innerHTML = `
                <div class="api-call-header">
                    <div class="api-title-group">
                        <svg class="icon api-icon"><use href="#icon-zap"></use></svg>
                        <span class="api-title">API调用 ${idx}</span>
                    </div>
                </div>
                <div class="api-stats-grid">
                    <div class="stat-row">
                        <span class="stat-label">消耗</span>
                        <span class="stat-value">${call.total ?? '-'}</span>
                        <span class="stat-detail"><span class="stat-in">↑${call.in ?? '-'}</span> <span class="stat-out">↓${call.out ?? '-'}</span></span>
                    </div>
                </div>
            `;
            monitorEntries.appendChild(item);
            return;
        }

        if (evt.type === 'final') {
            setProgressStep('reviewing', 'completed');
            setProgressStep('reporting', 'active');

            if (SessionState.lastSessionUsage && monitorEntries) {
                const totals = SessionState.lastSessionUsage;
                const item = document.createElement('div');
                item.className = 'process-item api-summary-card';
                item.innerHTML = `
                    <div class="api-call-header">
                        <div class="api-title-group">
                            <svg class="icon api-icon"><use href="#icon-trending-up"></use></svg>
                            <span class="api-title">Token 消耗总计</span>
                        </div>
                    </div>
                    <div class="api-stats-grid">
                        <div class="stat-row">
                            <span class="stat-label">总计</span>
                            <span class="stat-value">${totals.total ?? '-'}</span>
                        </div>
                    </div>
                `;
                monitorEntries.appendChild(item);
                SessionState.lastSessionUsage = null;
            }

            if (pendingChunkContent) {
                finalReportContent += pendingChunkContent;
                pendingChunkContent = '';
            }

            const finalContent = evt.content || finalReportContent;

            if (reportCanvasContainer) {
                reportCanvasContainer.innerHTML = marked.parse(finalContent);
                requestAnimationFrame(() => {
                    reportCanvasContainer.scrollTo({ top: 0, behavior: 'smooth' });
                });
            }

            let score = null;
            const scoreMatch = finalContent.match(/(?:评分|Score|分数)[:\s]*(\d+)/i);
            if (scoreMatch) score = parseInt(scoreMatch[1], 10);
            triggerCompletionTransition(null, score, true);

            if (monitorPanel && !fallbackSeen && !errorSeen) {
                monitorPanel.classList.add('ok');
                const titleEl = monitorPanel.querySelector('.panel-title');
                if (titleEl) titleEl.textContent = '日志 · 运行正常';
            }
            stopReviewTimer();
            streamEnded = true;
            return;
        }

        if (evt.type === 'error') {
            errorSeen = true;
            if (monitorPanel) {
                monitorPanel.classList.remove('ok');
                monitorPanel.classList.add('error');
                const titleEl = monitorPanel.querySelector('.panel-title');
                if (titleEl) titleEl.textContent = '日志 · 运行异常';
                monitorPanel.classList.remove('collapsed');
            }
            if (workflowEntries) {
                const errorEl = document.createElement('div');
                errorEl.className = 'workflow-error';
                errorEl.innerHTML = `
                    <div class="error-icon">${getIcon('x')}</div>
                    <div class="error-content">
                        <strong>发生错误</strong>
                        <p>${escapeHtml(evt.message || '未知错误')}</p>
                    </div>
                `;
                workflowEntries.appendChild(errorEl);
            }
            stopReviewTimer();
            streamEnded = true;
            SessionState.reviewStreamActive = false;
            endReviewTask();
            return;
        }

        if (evt.type === 'done') {
            stopReviewTimer();
            streamEnded = true;
            setProgressStep('reporting', 'completed');
            SessionState.reviewStreamActive = false;
            endReviewTask();
            loadSessions();
            return;
        }
    };

    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const events = buffer.split('\n\n');
            buffer = events.pop();

            for (const eventStr of events) {
                if (!eventStr.trim() || streamEnded) continue;
                const lines = eventStr.split('\n');
                for (const line of lines) {
                    const trimmedLine = line.trim();
                    if (!trimmedLine || trimmedLine.startsWith(':')) continue;
                    if (trimmedLine.startsWith('data: ')) {
                        try {
                            const evt = JSON.parse(trimmedLine.slice(6));
                            if (window.currentSessionId !== sid) { streamEnded = true; break; }
                            processEvent(evt);
                            if (streamEnded) break;
                        } catch (e) {
                            console.error('SSE Parse Error', e, trimmedLine);
                        }
                    }
                }
            }
            if (streamEnded) break;
        }
        if (buffer && buffer.startsWith('data: ')) {
            try {
                const evt = JSON.parse(buffer.slice(6));
                processEvent(evt);
            } catch (e) { }
        }
    } catch (e) {
        console.error('SSE Stream Error', e);
        if (workflowEntries) {
            const errorEl = document.createElement('div');
            errorEl.className = 'workflow-error';
            errorEl.innerHTML = `
                <div class="error-icon">${getIcon('x')}</div>
                <div class="error-content">
                    <strong>连接中断</strong>
                    <p>${escapeHtml(e.message)}</p>
                    <button class="retry-btn" onclick="startReview()">重试</button>
                </div>
            `;
            workflowEntries.appendChild(errorEl);
        }
        if (monitorPanel) {
            monitorPanel.classList.remove('ok');
            monitorPanel.classList.add('error');
            const titleEl = monitorPanel.querySelector('.panel-title');
            if (titleEl) titleEl.textContent = '日志 · 连接异常';
            monitorPanel.classList.remove('collapsed');
        }
        setLayoutState(LayoutState.INITIAL);
        stopReviewTimer();
    }

    if (startReviewBtn) {
        SessionState.reviewStreamActive = false;
        startReviewBtn.disabled = false;
        startReviewBtn.innerHTML = getIcon('send');
    }

    endReviewTask();
}

// 报告面板操作
function copyReportContent() {
    const reportContainer = document.getElementById('reportContainer');
    if (reportContainer && reportContainer.textContent) {
        navigator.clipboard.writeText(reportContainer.textContent).then(() => {
            showToast('报告内容已复制', 'success');
        }).catch(err => {
            showToast('复制失败', 'error');
        });
    }
}

function toggleReportFullScreen() {
    const reportPanel = document.getElementById('reportPanel');
    if (reportPanel) reportPanel.classList.toggle('fullscreen');
}

function reportGoBack() {
    const panel = document.getElementById('reportPanel');
    if (panel && panel.classList.contains('fullscreen')) {
        toggleReportFullScreen();
        return;
    }
    if (typeof returnToNewWorkspace === 'function') returnToNewWorkspace();
}

function sendChatMessage() {
    sendMessage();
}

// Export to window
window.startReview = startReview;
window.sendMessage = sendMessage;
window.sendChatMessage = sendChatMessage;
window.handleSSEResponse = handleSSEResponse;
window.copyReportContent = copyReportContent;
window.toggleReportFullScreen = toggleReportFullScreen;
window.reportGoBack = reportGoBack;
window.routeEvent = routeEvent;
