/**
 * workflow-replay.js - 工作流回放模块
 */

/**
 * 后端Stage说明：
 * 
 * 文件处理阶段（无用户可见内容，仅pipeline控制）：
 * - diff_parse: 解析Git差异，识别变更文件
 * - review_units: 分析审查单元，确定审查范围
 * - rule_layer: 应用规则层，匹配审查规则
 * - review_index: 构建审查索引，组织审查结构
 * - intent_analysis: 意图分析阶段标记（pipeline控制层，实际内容在intent中）
 * 
 * 用户阶段（有thought/chunk等实际内容）：
 * - intent: 意图分析 - 理解代码变更意图（实际执行和内容）
 * - planner: 审查规划 - 制定审查策略和上下文
 *   - fusion, context_provider, context_bundle, final_context_plan: 规划子步骤（内部使用）
 * - reviewer/review: 代码审查 - 执行审查并生成报告
 */

// 无内容的技术stage列表（完全隐藏，不创建UI块），如果未来有机会的话，可以考虑在前端添加些技术细节
const HIDDEN_STAGES = [
    // 文件处理阶段（pipeline控制）
    'diff_parse',      // 文件差异解析
    'review_units',    // 审查单元分析
    'rule_layer',      // 规则匹配
    'review_index',    // 索引构建

    // 意图分析阶段的pipeline控制层（实际内容在intent stage）
    'intent_analysis', // 意图分析阶段标记（无内容，内容在intent中）

    // 规划阶段的子步骤（pipeline控制）
    'fusion',          // 融合（planner子步骤）
    'context_provider',// 上下文提供（planner子步骤）
    'context_bundle',  // 上下文打包（planner子步骤）
    'final_context_plan' // 最终计划（planner子步骤）
];

// Stage normalization helpers
const STAGE_ALIAS_MAP = {
    'reviewer': 'review',
    'intent_analysis': 'intent',
    // planner sub-stages (pipeline/internal steps) should be grouped under planner in replay
    'fusion': 'planner',
    'context_provider': 'planner',
    'context_bundle': 'planner',
    'final_context_plan': 'planner'
};
const VISIBLE_STAGES = ['intent', 'planner', 'review'];

// 检查stage是否应该显示
function shouldShowStage(stage) {
    const normalized = normalizeStage(stage);
    if (!VISIBLE_STAGES.includes(normalized)) return false;
    return !HIDDEN_STAGES.includes(normalized);
}

function normalizeStage(stage) {
    if (!stage) return 'review';
    return STAGE_ALIAS_MAP[stage] || stage;
}

// 阶段信息映射（为每个后端stage提供唯一标题）
function getStageInfo(stage) {
    const stageMap = {
        // 意图分析相关
        'intent_analysis': { title: '意图分析', icon: 'bot', color: '#6366f1' },
        'intent': { title: '意图分析', icon: 'bot', color: '#6366f1' },

        // 规划相关
        'planner': { title: '审查规划', icon: 'plan', color: '#8b5cf6' },

        // 审查相关
        'review': { title: '代码审查', icon: 'review', color: '#10b981' },
        'reviewer': { title: '代码审查', icon: 'review', color: '#10b981' },

        // 默认
        'default': { title: '处理中', icon: 'settings', color: '#64748b' }
    };
    return stageMap[stage] || stageMap['default'];
}

function formatToolArgsGlobal(toolName, rawArgs) {
    if (rawArgs === undefined || rawArgs === null || rawArgs === '') {
        return '<span class="tool-args-empty">无参数</span>';
    }

    let text = '';
    if (typeof rawArgs === 'string') {
        text = rawArgs;
    } else {
        try {
            text = JSON.stringify(rawArgs, null, 2);
        } catch (e) {
            text = String(rawArgs);
        }
    }

    // Truncate if too long
    if (text.length > 500) {
        text = text.slice(0, 500) + '...';
    }

    return `<pre class="tool-args-code"><code>${escapeHtml(text)}</code></pre>`;
}

function formatToolArgsDefault(rawArgs) {
    return formatToolArgsGlobal('default', rawArgs);
}

function renderToolContentGlobal(toolName, rawContent) {
    if (rawContent === undefined || rawContent === null || rawContent === '') {
        return '<span class="tool-empty">无返回内容</span>';
    }

    let data = rawContent;
    if (typeof rawContent === 'string') {
        try { data = JSON.parse(rawContent); } catch (_) { /* keep raw */ }
    }

    // Error handling
    if (data && typeof data === 'object' && data.error) {
        return `<div class="tool-result error">${escapeHtml(String(data.error))}</div>`;
    }

    const name = (toolName || '').toLowerCase();

    // read_file_hunk: Code snippet display
    if (name.includes('read_file_hunk') || (name.includes('read_file') && data && data.snippet_with_line_numbers)) {
        const filePath = data.path || '';
        const ctxStart = data.context_start || data.start_line || 1;
        const ctxEnd = data.context_end || data.end_line || ctxStart;
        const totalLines = data.total_lines || '?';
        const snippet = data.snippet_with_line_numbers || data.snippet || '';
        const ext = filePath.split('.').pop() || 'txt';

        return `
            <div class="tool-code-block">
                <div class="code-header">
                    <span class="code-path" title="${escapeHtml(filePath)}">${getIcon('folder')} ${escapeHtml(filePath.split(/[\/\\]/).pop() || filePath)}</span>
                    <span class="code-range">行 ${ctxStart}-${ctxEnd} / 共 ${totalLines} 行</span>
                </div>
                <pre class="code-content"><code>${escapeHtml(snippet)}</code></pre>
            </div>
        `;
    }

    // read_file_info: File info card
    if (name.includes('read_file_info') || (data && data.line_count !== undefined && data.language !== undefined)) {
        const filePath = data.path || '';
        const size = data.size_bytes != null ? formatFileSizeGlobal(data.size_bytes) : '?';
        const lang = data.language || 'unknown';
        const lines = data.line_count || 0;

        return `
            <div class="tool-file-info">
                <div class="file-info-header">
                    ${getIcon('folder')}
                    <span class="file-name">${escapeHtml(filePath.split(/[\/\\]/).pop() || filePath)}</span>
                </div>
                <div class="file-info-grid">
                    <div class="info-item"><span class="label">路径</span><span class="value">${escapeHtml(truncateTextGlobal(filePath, 60))}</span></div>
                    <div class="info-item"><span class="label">大小</span><span class="value">${escapeHtml(size)}</span></div>
                    <div class="info-item"><span class="label">语言</span><span class="value">${escapeHtml(lang)}</span></div>
                    <div class="info-item"><span class="label">行数</span><span class="value">${lines}</span></div>
                </div>
            </div>
        `;
    }

    // search: Search results
    if (name.includes('search') && data && Array.isArray(data.matches)) {
        const query = data.query || '';
        const matches = data.matches || [];
        if (matches.length === 0) {
            return `<div class="tool-search-empty">${getIcon('search')} 未找到匹配: <code>${escapeHtml(query)}</code></div>`;
        }
        const items = matches.slice(0, 20).map(m => {
            const fileName = (m.path || '').split(/[\/\\]/).pop() || m.path;
            return `
                <div class="search-match">
                    <span class="match-file">${escapeHtml(fileName)}</span>
                    <span class="match-line">:${m.line || 0}</span>
                    <code class="match-snippet">${escapeHtml(truncateTextGlobal(m.snippet || '', 120))}</code>
                </div>
            `;
        }).join('');
        return `
            <div class="tool-search-results">
                <div class="search-header">${getIcon('search')} 搜索 <code>${escapeHtml(query)}</code> — ${matches.length} 条匹配</div>
                <div class="search-list">${items}</div>
            </div>
        `;
    }

    // list_directory: Directory listing
    if (name.includes('list_dir') || name.includes('directory') || (data && data.directories !== undefined && data.files !== undefined)) {
        const dirPath = data.path || '';
        const dirs = data.directories || [];
        const files = data.files || [];
        const dirItems = dirs.slice(0, 30).map(d => `<span class="dir-item">${getIcon('folder')} ${escapeHtml(d)}</span>`).join('');
        const fileItems = files.slice(0, 50).map(f => `<span class="file-item">${escapeHtml(f)}</span>`).join('');
        return `
            <div class="tool-directory">
                <div class="dir-header">${getIcon('folder')} ${escapeHtml(dirPath || '/')}</div>
                <div class="dir-content">${dirItems}${fileItems}</div>
            </div>
        `;
    }

    // Default: JSON or text display
    if (typeof data === 'object') {
        const jsonStr = JSON.stringify(data, null, 2);
        return `<pre class="tool-json"><code>${escapeHtml(truncateTextGlobal(jsonStr, 3000))}</code></pre>`;
    }

    return `<pre class="tool-text"><code>${escapeHtml(truncateTextGlobal(String(rawContent), 2000))}</code></pre>`;
}

function replayScannerEvents(events) {
    if (typeof ScannerUI === 'undefined') return;
    if (!events || events.length === 0) return;

    // 过滤扫描器相关事件（包括 static_scan_* 系列）
    const scannerEvents = events.filter(e =>
        e.type === 'scanner_progress' ||
        e.type === 'scanner_issues_summary' ||
        e.type === 'static_scan_start' ||
        e.type === 'static_scan_file_start' ||
        e.type === 'static_scan_file_done' ||
        e.type === 'static_scan_complete'
    );

    if (scannerEvents.length === 0) return;

    // 重置扫描器状态
    ScannerUI.reset();

    // 显示扫描器面板
    const scannerSection = document.getElementById('scannerWorkflowSection');
    if (scannerSection) {
        scannerSection.style.display = 'block';
    }

    // 回放每个扫描器事件
    scannerEvents.forEach(evt => {
        try {
            if (evt.type === 'scanner_progress') {
                ScannerUI.handleScannerProgress(evt);
            } else if (evt.type === 'scanner_issues_summary') {
                ScannerUI.handleScannerSummary(evt);
            } else if (evt.type === 'static_scan_start') {
                // 转换为 scanner_progress 格式
                ScannerUI.handleScannerProgress({
                    status: 'start',
                    scanner: 'static_scan',
                    file: `${evt.files_total || 0} files`,
                    timestamp: evt.timestamp
                });
            } else if (evt.type === 'static_scan_file_start') {
                // 更新当前扫描文件，不创建新卡片
                if (typeof ScannerUI.updateScanningFile === 'function') {
                    ScannerUI.updateScanningFile('static_scan', evt.file, evt.language);
                }
            } else if (evt.type === 'static_scan_file_done') {
                // 更新文件进度，不创建新卡片
                if (typeof ScannerUI.updateFileProgress === 'function') {
                    ScannerUI.updateFileProgress('static_scan', {
                        file: evt.file,
                        language: evt.language,
                        duration_ms: evt.duration_ms,
                        issues_count: evt.issues_count || 0,
                        progress: evt.progress
                    });
                }
            } else if (evt.type === 'static_scan_complete') {
                // 将 static_scan 扫描器标记为完成
                ScannerUI.handleScannerProgress({
                    status: 'complete',
                    scanner: 'static_scan',
                    duration_ms: evt.duration_ms || 0,
                    issue_count: evt.total_issues || 0,
                    error_count: evt.error_count || 0,
                    files_scanned: evt.files_scanned,
                    files_total: evt.files_total
                });
                // 发送汇总
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
                    duration_ms: evt.duration_ms,
                    scanners_used: evt.scanners_used || []
                });
            }
        } catch (e) {
            console.warn('Scanner replay error:', e);
        }
    });

    console.log(`[WorkflowReplay] Replayed ${scannerEvents.length} scanner events`);
}

// --- Planner Visualization Helpers (Copied from review.js for independence) ---
function extractPlanItemsSafe(jsonStr) {
    const items = [];
    const planStart = jsonStr.indexOf('"plan"');
    if (planStart === -1) return items;

    const arrayStart = jsonStr.indexOf('[', planStart);
    if (arrayStart === -1) return items;

    let depth = 0;
    let start = -1;
    let inString = false;
    let escape = false;

    for (let i = arrayStart + 1; i < jsonStr.length; i++) {
        const char = jsonStr[i];
        if (escape) { escape = false; continue; }
        if (char === '\\') { escape = true; continue; }
        if (char === '"') { inString = !inString; continue; }
        if (inString) continue;

        if (char === '{') {
            if (depth === 0) start = i;
            depth++;
        } else if (char === '}') {
            depth--;
            if (depth === 0 && start !== -1) {
                try {
                    const itemStr = jsonStr.substring(start, i + 1);
                    const item = JSON.parse(itemStr);
                    items.push(item);
                } catch (e) { }
                start = -1;
            }
        }
    }
    return items;
}

function renderPlannerVisualsReplay(container, fullText) {
    const items = extractPlanItemsSafe(fullText);
    if (!items.length) return false;

    const visualizer = document.createElement('div');
    visualizer.className = 'plan-visualizer';

    items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'plan-item';

        let ctxClass = 'tag-context-file';
        if (item.llm_context_level === 'diff_only') ctxClass = 'tag-context-diff';
        else if (item.llm_context_level === 'function') ctxClass = 'tag-context-func';

        const skipTag = item.skip_review ? '<span class="plan-tag tag-skip">跳过</span>' : '';
        const ctxTag = `<span class="plan-tag ${ctxClass}">${item.llm_context_level}</span>`;

        const displayName = item.unit_id.length > 20
            ? item.unit_id.substring(0, 8) + '...' + item.unit_id.substring(item.unit_id.length - 6)
            : item.unit_id;

        card.innerHTML = `
            <div class="plan-header">
                <div class="plan-title-group">
                    <svg class="plan-icon"><use href="#icon-folder"></use></svg>
                    <span class="plan-id" title="${item.unit_id}">${displayName}</span>
                </div>
            </div>
            <div class="plan-reason">${item.reason || ''}</div>
            <div class="plan-tags">
                ${ctxTag}
                ${skipTag}
            </div>
        `;
        visualizer.appendChild(card);
    });

    const toggleRaw = document.createElement('div');
    toggleRaw.className = 'plan-raw-toggle';
    toggleRaw.textContent = '切换原始 JSON 视图';
    toggleRaw.onclick = () => {
        const p = container.querySelector('.workflow-raw-text');
        const v = container.querySelector('.plan-visualizer');
        if (p && v) {
            const isHidden = p.style.display === 'none';
            p.style.display = isHidden ? 'block' : 'none';
            v.style.display = isHidden ? 'none' : 'flex';
        }
    };

    container.appendChild(visualizer);
    container.appendChild(toggleRaw);

    const rawDiv = document.createElement('div');
    rawDiv.className = 'workflow-raw-text markdown-body';
    rawDiv.style.display = 'none';
    rawDiv.innerHTML = marked.parse(fullText);
    container.appendChild(rawDiv);

    return true;
}

function replayWorkflowEvents(container, events) {
    if (!container || !events || events.length === 0) return;

    container.innerHTML = '';

    let currentStage = null;
    let currentStageContent = null;
    let chunkBuffer = '';
    const toolCallEntries = new Map();

    function createStageHeader(stage) {
        const info = getStageInfo(stage);
        const section = document.createElement('div');
        section.className = 'workflow-stage-section';
        section.dataset.stage = stage;
        section.innerHTML = `
            <div class="stage-header collapsible" onclick="toggleStageSection(this)">
                <div class="stage-indicator" style="--stage-color: ${info.color}">
                    ${getIcon(info.icon)}
                    <span>${info.title}</span>
                </div>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="stage-content"></div>
        `;
        return section;
    }

    function ensureStage(stage) {
        const normalizedStage = normalizeStage(stage);
        if (normalizedStage === currentStage || !shouldShowStage(normalizedStage)) {
            return;
        }
        const section = createStageHeader(normalizedStage);
        container.appendChild(section);
        currentStage = normalizedStage;
        currentStageContent = section.querySelector('.stage-content');
    }

    function getToolKey(evt) {
        const callIdx = evt.call_index ?? evt.index ?? '0';
        const toolName = evt.tool_name || evt.tool || 'tool';
        // [FIX] Removed hash. Arguments in start/result events may differ, causing key mismatch.
        return `${callIdx}-${toolName}`;
    }

    function ensureToolCard(stageContent, evt) {
        if (!stageContent) return null;
        let key = getToolKey(evt);
        const toolName = evt.tool_name || evt.tool || '未知工具';

        if (toolCallEntries.has(key)) {
            return toolCallEntries.get(key);
        }

        // [FIX] Orphan Claiming Logic:
        // If we have a specific index (e.g. "3-tool"), but haven't found it,
        // check if there is a generic "0-tool" card that is still running.
        // If so, "claim" it (rename it) instead of creating a new one.
        // This handles cases where backend sends start(no-index) then start(index).
        const callIdx = evt.call_index ?? evt.index;
        if (callIdx && String(callIdx) !== '0') {
            const genericKey = `0-${toolName}`;
            const genericEntry = toolCallEntries.get(genericKey);
            if (genericEntry && genericEntry.statusEl && genericEntry.statusEl.classList.contains('status-running')) {
                // Claim it!
                toolCallEntries.delete(genericKey);

                // Update Entry
                genericEntry.key = key;
                genericEntry.card.dataset.callKey = key;

                // Update Badge if needed
                const titleText = genericEntry.card.querySelector('.tool-title-text');
                if (titleText && !titleText.querySelector('.tool-badge')) {
                    titleText.innerHTML += `<span class="tool-badge">#${escapeHtml(String(callIdx))}</span>`;
                }

                toolCallEntries.set(key, genericEntry);
                return genericEntry;
            }
        }

        const card = document.createElement('div');
        card.className = 'workflow-tool';
        card.dataset.callKey = key;
        card.innerHTML = `
            <div class="tool-head">
                <div class="tool-title">
                    ${getIcon('terminal')}
                    <div class="tool-title-text">
                        <span class="tool-name">${escapeHtml(toolName)}</span>
                        ${evt.call_index !== undefined && evt.call_index !== null ? `<span class="tool-badge">#${escapeHtml(String(evt.call_index))}</span>` : ''}
                    </div>
                </div>
                <span class="tool-status status-running">调用中</span>
            </div>
            <div class="tool-section tool-args">${formatToolArgsGlobal(toolName, evt.arguments || evt.detail)}</div>
            <div class="tool-section tool-output" style="display:none"></div>
            <div class="tool-section tool-meta" style="display:none"></div>
        `;
        stageContent.appendChild(card);

        const entry = {
            key,
            card,
            statusEl: card.querySelector('.tool-status'),
            argsEl: card.querySelector('.tool-args'),
            outputEl: card.querySelector('.tool-output'),
            metaEl: card.querySelector('.tool-meta'),
            name: toolName
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
        if (!chips.length) return;
        entry.metaEl.innerHTML = chips.join('');
        entry.metaEl.style.display = 'flex';
    }

    function updateToolOutput(entry, evt) {
        if (!entry || !entry.outputEl) return;
        const hasError = !!evt.error;
        const body = hasError
            ? `<div class="tool-result error">${escapeHtml(String(evt.error))}</div>`
            : `<div class="tool-result success">${renderToolContentGlobal(entry.name, evt.content || evt.result)}</div>`;
        entry.outputEl.innerHTML = body;
        entry.outputEl.style.display = 'block';
        setToolStatus(entry, hasError ? 'error' : 'success', hasError ? '失败' : '完成');
        updateToolMeta(entry, evt);
    }

    function flushChunk(stage, chunkText, nextEvt) {
        if (!chunkText.trim() || !currentStageContent) {
            return;
        }
        if (stage === 'review') {
            if (nextEvt && (nextEvt.type === 'tool_start' || nextEvt.type === 'tool_call_start')) {
                const explanation = document.createElement('div');
                explanation.className = 'workflow-tool-explanation';
                explanation.innerHTML = `
                    <div class="tool-explanation-content markdown-body">
                        ${marked.parse(chunkText)}
                    </div>
                `;
                currentStageContent.appendChild(explanation);
            }
            return;
        }

        const chunkTitle = stage === 'planner' ? '上下文决策' : '输出内容';
        // Planner 默认展开以便查看，其他内容默认折叠保持整洁
        const initialClass = stage === 'planner' ? 'workflow-chunk-wrapper' : 'workflow-chunk-wrapper collapsed';

        const wrapper = document.createElement('div');
        wrapper.className = initialClass;
        wrapper.innerHTML = `
            <div class="chunk-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                ${getIcon('folder')}
                <span>${chunkTitle}</span>
                <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="chunk-body">
                <div class="workflow-chunk"></div>
            </div>
        `;
        currentStageContent.appendChild(wrapper);

        const chunkEl = wrapper.querySelector('.workflow-chunk');

        // 尝试可视化渲染 (Planner)
        if (stage === 'planner') {
            // 如果成功渲染出可视化组件，就不再渲染默认 Markdown
            if (renderPlannerVisualsReplay(chunkEl, chunkText)) {
                return;
            }
        }

        // 默认 Markdown 渲染
        chunkEl.classList.add('markdown-body');
        chunkEl.innerHTML = marked.parse(chunkText);
    }

    const RENDER_EVENT_TYPES = new Set([
        'thought', 'chunk', 'delta',
        'tool_start', 'tool_call_start', 'tool_result', 'tool_call_end',
        'workflow_chunk'
    ]);

    function getNextRelevantEvent(startIdx, stage) {
        for (let k = startIdx; k < events.length; k++) {
            const e = events[k];
            const s = normalizeStage(e.stage || stage || 'review');
            if (!shouldShowStage(s)) continue;
            if (!RENDER_EVENT_TYPES.has(e.type)) continue;
            return { evt: e, idx: k, stage: s };
        }
        return { evt: null, idx: -1, stage: stage };
    }

    for (let i = 0; i < events.length; i++) {
        const evt = events[i];
        const nextEvt = events[i + 1];
        const stage = normalizeStage(evt.stage || 'review');

        if (!shouldShowStage(stage)) {
            continue;
        }
        if (!RENDER_EVENT_TYPES.has(evt.type)) {
            continue;
        }
        ensureStage(stage);
        if (!currentStageContent) continue;

        if (evt.type === 'thought') {
            // 收集当前 stage 的所有 thought 事件，跳过不属于当前 stage 的事件
            let thoughtContent = evt.content || evt.text || '';
            let j = i + 1;
            while (j < events.length) {
                const nextEvt = events[j];
                const nextStage = normalizeStage(nextEvt.stage || 'review');

                // 如果是同 stage 的 thought，累积内容
                if (nextEvt.type === 'thought' && nextStage === stage) {
                    thoughtContent += (nextEvt.content || nextEvt.text || '');
                    j++;
                    continue;
                }

                // 如果是不同 stage 的事件，跳过它（不打断合并）
                if (nextStage !== stage) {
                    j++;
                    continue;
                }

                // 如果是同 stage 的非 thought 事件，停止合并
                break;
            }
            // 跳过已经处理的事件
            i = j - 1;

            if (!thoughtContent.trim()) continue;

            const thoughtEl = document.createElement('div');
            thoughtEl.className = 'workflow-thought collapsed';
            thoughtEl.innerHTML = `
                <div class="thought-toggle" onclick="this.parentElement.classList.toggle('collapsed')">
                    ${getIcon('bot')}
                    <span>思考过程</span>
                    <svg class="icon chevron"><use href="#icon-chevron-down"></use></svg>
                </div>
                <div class="thought-body"><pre class="thought-text">${escapeHtml(thoughtContent)}</pre></div>
            `;
            currentStageContent.appendChild(thoughtEl);
            continue;
        }

        if (evt.type === 'chunk' || evt.type === 'delta' || evt.type === 'workflow_chunk') {
            const content = evt.content || evt.text || '';
            if (content) {
                chunkBuffer += content;
            }

            // Merge across intervening non-render / hidden-stage events.
            // Only stop when the next *relevant* event is not a same-stage chunk stream.
            const next = getNextRelevantEvent(i + 1, stage);
            const nextEvt = next.evt;
            const nextStage = next.stage;
            const continueChunk = !!nextEvt
                && nextStage === stage
                && (nextEvt.type === 'chunk' || nextEvt.type === 'delta' || nextEvt.type === 'workflow_chunk');

            if (continueChunk) continue;

            flushChunk(stage, chunkBuffer, nextEvt);
            chunkBuffer = '';
            continue;
        }

        chunkBuffer = '';

        if (evt.type === 'tool_start' || evt.type === 'tool_call_start') {
            const entry = ensureToolCard(currentStageContent, evt);
            // [FIX] Always try to update arguments from latest event
            if (entry && entry.argsEl && (evt.arguments || evt.detail)) {
                entry.argsEl.innerHTML = formatToolArgsGlobal(entry.name, evt.arguments || evt.detail);
            }
            setToolStatus(entry, 'running', '调用中');
            continue;
        }

        if (evt.type === 'tool_result' || evt.type === 'tool_call_end') {
            const key = getToolKey(evt);
            let entry = toolCallEntries.get(key);

            // [FIX] Fallback matching: if exact key not found (e.g. index mismatch),
            // find the LAST running tool with same name.
            if (!entry) {
                const entries = Array.from(toolCallEntries.values());
                const targetName = evt.tool_name || evt.tool || evt.name || '未知工具';
                for (let k = entries.length - 1; k >= 0; k--) {
                    const e = entries[k];
                    if (e.name === targetName &&
                        e.statusEl && e.statusEl.classList.contains('status-running')) {
                        entry = e;
                        break;
                    }
                }
            }

            if (entry) {
                if (evt.type === 'tool_result') {
                    updateToolOutput(entry, evt);
                } else {
                    setToolStatus(entry, evt.success === false ? 'error' : 'success', evt.success === false ? '失败' : '完成');
                    updateToolMeta(entry, evt);
                }
            }
            continue;
        }

        if (evt.content) {
            const block = document.createElement('div');
            block.className = 'workflow-block markdown-body';
            block.innerHTML = marked.parse(evt.content);
            currentStageContent.appendChild(block);
        }
    }
}

function replayMonitorEvents(container, events) {
    if (!container || !events) return;

    container.innerHTML = '';

    const monitorEvents = events.filter(e =>
        e.type === 'warning' ||
        e.type === 'usage_summary' ||
        e.type === 'error'
    );

    monitorEvents.forEach(evt => {
        const div = document.createElement('div');
        div.className = `monitor-entry ${evt.type}`;

        if (evt.type === 'warning') {
            div.innerHTML = `
                <div class="monitor-icon">${getIcon('alert-triangle')}</div>
                <div class="monitor-content">${escapeHtml(evt.message || '')}</div>
            `;
        } else if (evt.type === 'usage_summary') {
            const usage = evt.data || {};
            div.innerHTML = `
                <div class="monitor-icon">${getIcon('bar-chart')}</div>
                <div class="monitor-content">
                    <span>Tokens: ${usage.total_tokens || 0}</span>
                    <span>Cost: $${(usage.total_cost || 0).toFixed(4)}</span>
                </div>
            `;
        } else if (evt.type === 'error') {
            div.innerHTML = `
                <div class="monitor-icon">${getIcon('x')}</div>
                <div class="monitor-content error">${escapeHtml(evt.message || evt.error || '')}</div>
            `;
        }

        container.appendChild(div);
    });
}

// Export to window
window.formatToolArgsGlobal = formatToolArgsGlobal;
window.formatToolArgsDefault = formatToolArgsDefault;
window.renderToolContentGlobal = renderToolContentGlobal;
window.replayScannerEvents = replayScannerEvents;
window.replayWorkflowEvents = replayWorkflowEvents;
window.replayMonitorEvents = replayMonitorEvents;
