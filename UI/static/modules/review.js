/**
 * review.js - 审查核心逻辑模块
 * 包含 startReview, sendMessage, handleSSEResponse 等核心函数
 */

// 思考计时器
let thoughtTimerInterval = null;

// 用户交互状态跟踪
const UserInteractionState = {
    userScrolled: false,
    manualExpandStates: new Map(),
    lastScrollTime: 0,
    SCROLL_RESET_TIMEOUT: 4000
};

let isAutoScrolling = false;

function resetUserScrollState() {
    const now = Date.now();
    if (now - UserInteractionState.lastScrollTime > UserInteractionState.SCROLL_RESET_TIMEOUT) {
        UserInteractionState.userScrolled = false;
    }
}

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
        renderReportPlaceholder(reportContainer);
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
    const enableStaticScanInput = document.getElementById('enableStaticScan');
    const enableStaticScan = enableStaticScanInput ? enableStaticScanInput.checked : false;

    // 如果启用静态扫描，显示扫描器面板并初始化（默认折叠）
    if (enableStaticScan) {
        const scannerSection = document.getElementById('scannerWorkflowSection');
        if (scannerSection) {
            scannerSection.style.display = 'block';
            scannerSection.classList.add('collapsed');  // 默认折叠
        }
        if (typeof ScannerUI !== 'undefined') {
            ScannerUI.reset();
            ScannerUI.beginScanning();
        }
    }

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
                enableStaticScan: enableStaticScan,
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

    // workflowEntries 现在直接暴露，无外层容器
    const workflowEntries = document.getElementById('workflowEntries');
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

    renderReportPlaceholder(reportCanvasContainer);

    // 添加滚动事件监听器以跟踪用户滚动行为
    const scrollArea = document.getElementById('rightPanelScrollArea');
    const handleUserScroll = () => {
        if (isAutoScrolling) return; // 忽略代码触发的滚动
        UserInteractionState.userScrolled = true;
        UserInteractionState.lastScrollTime = Date.now();
    };

    if (scrollArea) {
        scrollArea.addEventListener('scroll', handleUserScroll);
    }
    if (workflowEntries) {
        workflowEntries.addEventListener('scroll', handleUserScroll);
    }

    let finalReportContent = '';
    let pendingChunkContent = '';
    let reportFinalized = false;
    let streamEnded = false;
    const sid = expectedSessionId || window.currentSessionId;
    stopSessionPolling();
    SessionState.reviewStreamActive = true;

    let currentStage = null;

    let errorSeen = false;
    let currentChunkEl = null;
    let currentThoughtEl = null;
    let thoughtStartTime = null;
    const toolCallEntries = new Map();

    // 节流渲染：减少高频 DOM 更新，提升流畅度
    let reportRenderPending = false;
    let reportRenderTimer = null;
    const RENDER_THROTTLE_MS = 50; // 50ms 节流间隔

    const STREAM_MD_DEBOUNCE_MS = 200;

    function streamAppendIntoChunkEl(chunkEl, deltaText) {
        if (!chunkEl) return;
        const d = deltaText || '';
        chunkEl.dataset.fullText = (chunkEl.dataset.fullText || '') + d;

        // 如果已经完成了 markdown 渲染，不要用 pre 覆盖，只更新 dataset 并重新调度渲染
        // 这避免了样式在"纯文本"和"渲染后"之间频繁切换的问题
        if (chunkEl._markedRendered) {
            // 已渲染过 markdown，只需重新调度 debounce 渲染更新
            if (chunkEl._streamMdTimer) {
                clearTimeout(chunkEl._streamMdTimer);
            }
            chunkEl._streamMdTimer = setTimeout(() => {
                chunkEl._streamMdTimer = null;
                if (!chunkEl.isConnected) return;
                const fullText = chunkEl.dataset.fullText || '';
                chunkEl.innerHTML = marked.parse(fullText);
            }, STREAM_MD_DEBOUNCE_MS);
            return;
        }

        const ensurePre = () => {
            let pre = chunkEl._streamPre;
            if (pre && pre.isConnected) return pre;
            chunkEl.innerHTML = '<pre class="workflow-stream-text" style="margin:0;white-space:pre-wrap;word-break:break-word;"></pre>';
            pre = chunkEl.querySelector('.workflow-stream-text');
            chunkEl._streamPre = pre;
            return pre;
        };

        if (chunkEl._streamRaf) return;
        chunkEl._streamRaf = requestAnimationFrame(() => {
            chunkEl._streamRaf = null;
            // 再次检查，防止在 raf 期间被 marked 渲染覆盖
            if (chunkEl._markedRendered) return;
            const pre = ensurePre();
            if (pre) pre.textContent = chunkEl.dataset.fullText || '';
        });

        if (chunkEl._streamMdTimer) {
            clearTimeout(chunkEl._streamMdTimer);
        }
        chunkEl._streamMdTimer = setTimeout(() => {
            chunkEl._streamMdTimer = null;
            if (!chunkEl.isConnected) return;
            const fullText = chunkEl.dataset.fullText || '';
            chunkEl._streamPre = null;
            chunkEl._markedRendered = true;  // 标记已完成 markdown 渲染
            chunkEl.innerHTML = marked.parse(fullText);
        }, STREAM_MD_DEBOUNCE_MS);
    }

    function scheduleReportRender() {
        // 只要有内容就渲染，不再等待 reportFinalized
        if (!(finalReportContent + pendingChunkContent).trim()) return;
        if (reportRenderPending) return;
        reportRenderPending = true;
        if (reportRenderTimer) cancelAnimationFrame(reportRenderTimer);
        reportRenderTimer = requestAnimationFrame(() => {
            // 在渲染时重新计算内容，确保使用最新累积的值（修复闭包快照问题）
            const contentToRender = finalReportContent + pendingChunkContent;
            if (reportCanvasContainer && contentToRender.trim()) {
                // 清除占位符标记
                if (reportCanvasContainer.dataset && reportCanvasContainer.dataset.reportPlaceholder) {
                    delete reportCanvasContainer.dataset.reportPlaceholder;
                }
                reportCanvasContainer.innerHTML = marked.parse(contentToRender);
                reportCanvasContainer.scrollTop = reportCanvasContainer.scrollHeight;
            }
            reportRenderPending = false;
        });
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
        header.id = 'stage-' + stage + '-' + Date.now();
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
        const content = lastSection ? lastSection.querySelector('.stage-content') : null;
        return content || workflowEntries;
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

    function smartScrollToBottom(el) {
        if (!el) return;

        // 检查是否需要重置用户状态（超过4秒无操作）
        if (UserInteractionState.userScrolled) {
            const now = Date.now();
            if (now - UserInteractionState.lastScrollTime > UserInteractionState.SCROLL_RESET_TIMEOUT) {
                UserInteractionState.userScrolled = false;
            } else {
                return; // 用户仍在操作或未超时，不滚动
            }
        }

        const currentScrollTop = el.scrollTop;
        const targetScrollTop = el.scrollHeight - el.clientHeight;
        const dist = targetScrollTop - currentScrollTop;

        if (dist <= 0) return; // 已经在底部

        isAutoScrolling = true;

        // 核心优化：
        // 如果距离很近 (< 100px)，直接瞬间吸附，保证高频输出时的“实时感”和“稳定性”
        // 如果距离较远 (说明是从暂停状态恢复，或者内容突然由于折叠展开变长)，用平滑滚动作为视觉引导
        if (dist < 100) {
            el.scrollTop = targetScrollTop;
            // 瞬间滚动的事件传播很快，短timeout即可
            setTimeout(() => isAutoScrolling = false, 50);
        } else {
            try {
                el.scrollTo({
                    top: targetScrollTop,
                    behavior: 'smooth'
                });
            } finally {
                // 平滑滚动耗时较长，给足安全时间防止误判
                setTimeout(() => isAutoScrolling = false, 500);
            }
        }
    }

    function liveFollowScroll() {
        // 优先滚动右侧面板的主滚动区域
        const scrollArea = document.getElementById('rightPanelScrollArea');
        if (scrollArea) {
            smartScrollToBottom(scrollArea);
        }

        // 同时也处理 workflowEntries（如果它自身有滚动）
        const scrollContainer = document.getElementById('workflowEntries');
        if (scrollContainer && scrollContainer.scrollHeight > scrollContainer.clientHeight) {
            smartScrollToBottom(scrollContainer);
        }
    }

    function liveFollowCollapse(el) {
        if (!el) return;
        const elementId = el.id || el.dataset.elementId;
        if (elementId && UserInteractionState.manualExpandStates.get(elementId)) {
            return;
        }
        if (!el.classList.contains('collapsed')) el.classList.add('collapsed');
    }

    function generateElementId() {
        return 'el-' + Math.random().toString(36).substr(2, 9);
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
                currentThoughtEl.id = generateElementId();
                currentThoughtEl.innerHTML = `
                    <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed'); UserInteractionState.manualExpandStates.set(this.parentElement.id, !this.parentElement.classList.contains('collapsed'));">
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
                // 绑定滚动监听，确保思考过程也能响应用户操作中断
                const tBody = currentThoughtEl.querySelector('.thought-body');
                if (tBody) tBody.addEventListener('scroll', handleUserScroll);
            }
            const textEl = currentThoughtEl.querySelector('.thought-text');
            textEl.textContent = (textEl.textContent || '') + thoughtText;

            const thoughtBody = currentThoughtEl.querySelector('.thought-body');
            if (thoughtBody) smartScrollToBottom(thoughtBody);

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
                // 流式渲染到左侧面板
                scheduleReportRender();
                return;
            }

            if (!currentChunkEl) {
                const wrapper = document.createElement('div');
                wrapper.className = 'workflow-chunk-wrapper collapsed';
                wrapper.id = generateElementId();
                const chunkTitle = stage === 'planner' ? '上下文决策' : '输出内容';
                wrapper.innerHTML = `
                    <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed'); UserInteractionState.manualExpandStates.set(this.parentElement.id, !this.parentElement.classList.contains('collapsed'));">
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

            streamAppendIntoChunkEl(currentChunkEl, evt.content || '');
            liveFollowScroll();
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
            liveFollowScroll();
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
        try {
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

            // 处理旁路静态扫描服务的事件（static_scan_* 系列）
            if (evt.type === 'static_scan_start') {
                // 静态扫描开始 - 显示并展开扫描器面板
                const scannerSection = document.getElementById('scannerWorkflowSection');
                if (scannerSection) {
                    scannerSection.style.display = 'block';
                    scannerSection.classList.remove('collapsed');  // 确保面板展开
                }
                if (typeof ScannerUI !== 'undefined') {
                    // 转换为 scanner_progress 格式
                    ScannerUI.handleScannerProgress({
                        status: 'start',
                        scanner: 'static_scan',
                        file: `${evt.files_total || 0} files`,
                        timestamp: evt.timestamp
                    });
                }
                return;
            }

            if (evt.type === 'static_scan_file_start') {
                // 更新 static_scan 总览卡片的当前扫描文件
                if (typeof ScannerUI !== 'undefined') {
                    ScannerUI.updateScanningFile('static_scan', evt.file, evt.language);
                }
                return;
            }

            if (evt.type === 'static_scan_file_done') {
                // 文件扫描完成，更新进度（不创建单独的语言卡片）
                if (typeof ScannerUI !== 'undefined') {
                    ScannerUI.updateFileProgress('static_scan', {
                        file: evt.file,
                        language: evt.language,
                        duration_ms: evt.duration_ms,
                        issues_count: evt.issues_count || 0,
                        progress: evt.progress
                    });
                }
                return;
            }

            if (evt.type === 'static_scan_complete') {
                if (typeof ScannerUI !== 'undefined') {
                    // 将 static_scan 扫描器标记为完成，包含完整的统计信息
                    ScannerUI.handleScannerProgress({
                        status: 'complete',
                        scanner: 'static_scan',
                        duration_ms: evt.duration_ms || 0,
                        issue_count: evt.total_issues || 0,
                        error_count: evt.error_count || 0,
                        files_scanned: evt.files_scanned,
                        files_total: evt.files_total
                    });

                    // 发送汇总事件
                    ScannerUI.handleScannerSummary({
                        total_issues: evt.total_issues || 0,
                        by_severity: {
                            error: evt.error_count || 0,
                            warning: evt.warning_count || 0,
                            info: evt.info_count || 0
                        },
                        critical_issues: evt.issues || [],
                        files_scanned: evt.files_scanned,
                        files_total: evt.files_total,
                        files_skipped_doc: evt.files_skipped_doc,
                        duration_ms: evt.duration_ms,
                        scanners_used: evt.scanners_used || []
                    });

                    try { ScannerUI.endScanning(); } catch (e) { }

                    // 扫描完成后自动折叠静态扫描器面板
                    setTimeout(() => {
                        const scannerSection = document.getElementById('scannerWorkflowSection');
                        if (scannerSection && !scannerSection.classList.contains('collapsed')) {
                            scannerSection.classList.add('collapsed');
                        }
                    }, 500);  // 延迟500ms让用户看到完成状态
                }

                if (typeof window.refreshReportDiffLinked === 'function') {
                    try { window.refreshReportDiffLinked(); } catch (e) { }
                }
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
                        scheduleReportRender();  // 触发渲染（修复：原代码缺失此调用导致截断）
                    } else {
                        if (!currentChunkEl) {
                            const wrapper = document.createElement('div');
                            wrapper.className = 'workflow-chunk-wrapper collapsed';
                            wrapper.id = generateElementId();
                            wrapper.innerHTML = `
                            <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed'); UserInteractionState.manualExpandStates.set(this.parentElement.id, !this.parentElement.classList.contains('collapsed'));">
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
                        streamAppendIntoChunkEl(currentChunkEl, contentDelta);
                    }
                }

                liveFollowScroll();
                return;
            }

            // 处理审查主题作为会话命名
            if (evt.type === 'session_title' && evt.title) {
                const title = evt.title;
                const sessionId = window.currentSessionId;
                if (sessionId && title) {
                    // 调用后端 API 更新会话名称
                    fetch('/api/sessions/rename', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: sessionId, new_name: title })
                    }).then(res => {
                        if (res.ok) {
                            // 刷新会话列表以显示新名称
                            if (typeof loadSessions === 'function') loadSessions();
                            console.log('[Session] Title updated:', title);
                        }
                    }).catch(e => console.warn('[Session] Failed to update title:', e));
                }
                return;
            }

            // 处理决策阶段的警告（重试、模型切换）
            if (evt.type === 'warning' && evt.stage === 'planner' && workflowEntries) {
                if (currentStage !== 'planner') {
                    currentStage = 'planner';
                    workflowEntries.appendChild(createStageHeader('planner'));
                }
                const stageContent = getCurrentStageContent();
                const warningEl = document.createElement('div');
                warningEl.className = 'workflow-warning';
                const icon = 'alert-triangle';
                warningEl.innerHTML = `
                    <div class="warning-icon">${getIcon(icon)}</div>
                    <span class="warning-text">${escapeHtml(evt.message || '重试中...')}</span>
                `;
                stageContent.appendChild(warningEl);
                liveFollowScroll();
                return;
            }



            if (evt.type === 'usage_summary' && monitorEntries) {
                const call_usage = evt.call_usage || {};
                const totals = evt.session_usage || {};
                SessionState.lastSessionUsage = totals;
                const callIndex = evt.call_index;
                const usageStage = evt.usage_stage || 'review';
                const item = document.createElement('div');
                item.className = 'process-item api-call-card';
                const idx = (callIndex !== undefined && callIndex !== null) ? `#${callIndex}` : '';
                const stageBadge = usageStage ? `<span class="stage-badge">${usageStage}</span>` : '';
                item.innerHTML = `
                <div class="api-call-header">
                    <div class="api-title-group">
                        <svg class="icon api-icon"><use href="#icon-zap"></use></svg>
                        <span class="api-title">API调用 ${idx}</span>
                        ${stageBadge}
                    </div>
                </div>
                <div class="api-stats-grid">
                    <div class="stat-row">
                        <span class="stat-label">消耗</span>
                        <span class="stat-value">${call_usage.total ?? '-'}</span>
                        <span class="stat-detail"><span class="stat-in">↑${call_usage.in ?? '-'}</span> <span class="stat-out">↓${call_usage.out ?? '-'}</span></span>
                    </div>
                </div>
            `;
                monitorEntries.appendChild(item);
                return;
            }

            if (evt.type === 'final') {
                reportFinalized = true;
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
                    if (reportCanvasContainer.dataset) {
                        delete reportCanvasContainer.dataset.reportPlaceholder;
                    }
                    reportCanvasContainer.innerHTML = marked.parse(finalContent);
                    requestAnimationFrame(() => {
                        reportCanvasContainer.scrollTo({ top: 0, behavior: 'smooth' });
                    });
                }

                let score = null;
                const scoreMatch = finalContent.match(/(?:评分|Score|分数)[:\s]*(\d+)/i);
                if (scoreMatch) score = parseInt(scoreMatch[1], 10);
                triggerCompletionTransition(null, score, true);

                if (monitorPanel && !errorSeen) {
                    monitorPanel.classList.add('ok');
                    const titleEl = monitorPanel.querySelector('.panel-title');
                    if (titleEl) titleEl.textContent = '日志 · 运行正常';
                }
                stopReviewTimer();

                // 主审查已完成：恢复按钮与运行状态（旁路静态扫描可能仍在继续推送事件）
                SessionState.reviewStreamActive = false;
                if (startReviewBtn) {
                    startReviewBtn.disabled = false;
                    startReviewBtn.innerHTML = getIcon('send');
                }
                endReviewTask();

                if (typeof window.refreshReportDiffLinked === 'function') {
                    try { window.refreshReportDiffLinked(); } catch (e) { }
                }
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
                SessionState.reviewStreamActive = false;
                endReviewTask();
                return;
            }

            if (evt.type === 'done') {
                stopReviewTimer();
                streamEnded = true;
                setProgressStep('reporting', 'completed');
                SessionState.reviewStreamActive = false;
                if (typeof ScannerUI !== 'undefined') {
                    try { ScannerUI.endScanning(); } catch (e) { }
                }
                endReviewTask();
                loadSessions();
                return;
            }
        } catch (e) {
            console.error('[SSE] processEvent error', e, evt);
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

    // 清理事件监听器
    if (scrollArea) {
        scrollArea.removeEventListener('scroll', handleUserScroll);
    }
    if (workflowEntries) {
        workflowEntries.removeEventListener('scroll', handleUserScroll);
    }
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

    // 如果当前是代码变更视图，先重置回审查报告视图和面板状态
    if (window.currentReportViewMode === 'diff') {
        // 重置视图切换按钮状态
        const viewToggleReport = document.getElementById('viewToggleReport');
        const viewToggleDiff = document.getElementById('viewToggleDiff');
        viewToggleReport?.classList.add('active');
        viewToggleDiff?.classList.remove('active');

        // 重置内容显示
        const reportContainer = document.getElementById('reportContainer');
        const diffViewContainer = document.getElementById('diffViewContainer');
        if (reportContainer) reportContainer.style.display = '';
        if (diffViewContainer) diffViewContainer.style.display = 'none';

        // 立即重置面板样式（不使用动画，避免返回时的视觉问题）
        const rightPanel = document.getElementById('rightPanel');
        if (rightPanel) {
            rightPanel.style.width = '';
            rightPanel.style.opacity = '';
            rightPanel.style.overflow = '';
        }
        if (panel) {
            panel.style.width = '';
        }

        window.currentReportViewMode = 'report';
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
