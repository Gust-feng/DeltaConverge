/**
 * rule-growth.js - 规则优化页面模块
 * 
 * 包含规则与 LLM 决策冲突分析的完整功能
 */



// ============================================================
// 初始化函数 - 定义在文件末尾
// ============================================================

// ============================================================
// 数据加载函数
// ============================================================

async function loadRuleGrowthData() {
    try {
        await Promise.all([
            loadRuleGrowthSummary(),
            loadEnhancedSuggestions()
        ]);
    } catch (e) {
        console.error('Load rule growth data error:', e);
        showToast('加载规则数据失败: ' + e.message, 'error');
    }
}

async function loadRuleGrowthSummary() {
    const summaryContent = document.getElementById('rg-summary-content');
    const summaryEmpty = document.getElementById('rg-summary-empty');
    const totalBadge = document.getElementById('rg-total-badge');

    try {
        const res = await fetch('/api/rule-growth/summary');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();

        if (data.error) throw new Error(data.error);

        const total = data.total_conflicts || 0;
        if (totalBadge) totalBadge.textContent = total;

        if (total === 0) {
            if (summaryEmpty) summaryEmpty.style.display = 'flex';
            if (summaryContent) summaryContent.innerHTML = '';
            return;
        }

        if (summaryEmpty) summaryEmpty.style.display = 'none';

        let html = `<div class="stat-total" style="text-align: center; padding: 1rem 0; margin-bottom: 1rem; background: #f9fafb; border-radius: 8px;">
            <div style="font-size: 2rem; font-weight: 700; color: var(--primary);">${total}</div>
            <div style="font-size: 0.8rem; color: var(--text-muted);">总冲突数</div>
        </div>`;

        if (data.by_type && Object.keys(data.by_type).length > 0) {
            html += '<div class="stat-section"><h4>按冲突类型</h4><div class="stat-list">';
            for (const [type, count] of Object.entries(data.by_type)) {
                const typeLabel = getRuleGrowthTypeLabel(type);
                const typeIcon = getRuleGrowthTypeIcon(type);
                html += `<div class="stat-row">
                    <span class="label">${typeIcon} ${escapeHtml(typeLabel)}</span>
                    <span class="value">${count}</span>
                </div>`;
            }
            html += '</div></div>';
        }

        if (data.by_language && Object.keys(data.by_language).length > 0) {
            html += '<div class="stat-section"><h4>按语言</h4><div class="stat-list">';
            for (const [lang, count] of Object.entries(data.by_language)) {
                const langLabel = formatLanguageLabel(lang);
                html += `<div class="stat-row">
                    <span class="label">${escapeHtml(langLabel)}</span>
                    <span class="value">${count}</span>
                </div>`;
            }
            html += '</div></div>';
        }

        if (summaryContent) summaryContent.innerHTML = html;

    } catch (e) {
        console.error('Load rule growth summary error:', e);
        if (summaryContent) {
            summaryContent.innerHTML = `<div class="error-text">加载失败: ${escapeHtml(e.message)}</div>`;
        }
    }
}

async function loadEnhancedSuggestions() {
    const applicableContent = document.getElementById('rg-applicable-content');
    const applicableEmpty = document.getElementById('rg-applicable-empty');
    const applicableList = document.getElementById('rg-applicable-list');
    const applicableBadge = document.getElementById('rg-applicable-badge');

    const hintsContent = document.getElementById('rg-hints-content');
    const hintsEmpty = document.getElementById('rg-hints-empty');
    const hintsList = document.getElementById('rg-hints-list');
    const hintsBadge = document.getElementById('rg-hints-badge');

    try {
        const res = await fetch('/api/rule-growth/enhanced-suggestions');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();

        if (data.error) throw new Error(data.error);

        const applicableRules = data.applicable_rules || [];
        const referenceHints = data.reference_hints || [];

        // 渲染可应用规则
        if (applicableBadge) applicableBadge.textContent = applicableRules.length;

        if (applicableRules.length === 0) {
            if (applicableEmpty) applicableEmpty.style.display = 'flex';
            if (applicableList) applicableList.style.display = 'none';
        } else {
            if (applicableEmpty) applicableEmpty.style.display = 'none';
            if (applicableList) {
                applicableList.style.display = 'block';
                applicableList.innerHTML = applicableRules.map(rule => renderApplicableRule(rule)).join('');
            }
        }

        // 渲染参考提示（按语言分组）
        if (hintsBadge) hintsBadge.textContent = referenceHints.length;

        if (referenceHints.length === 0) {
            if (hintsEmpty) hintsEmpty.style.display = 'flex';
            if (hintsList) hintsList.style.display = 'none';
        } else {
            if (hintsEmpty) hintsEmpty.style.display = 'none';
            if (hintsList) {
                hintsList.style.display = 'block';
                hintsList.innerHTML = renderGroupedHintsByLanguage(referenceHints);
            }
        }

    } catch (e) {
        console.error('Load enhanced suggestions error:', e);
        if (applicableContent) {
            applicableContent.innerHTML = `<div class="error-text">加载失败: ${escapeHtml(e.message)}</div>`;
        }
    }
}

// ============================================================
// 标签和图标辅助函数
// ============================================================

function getRuleGrowthTypeIcon(type) {
    const iconMap = {
        'rule_high_llm_expand': 'trending-up',
        'rule_high_llm_skip': 'x',
        'rule_low_llm_consistent': 'lightbulb',
        'context_level_mismatch': 'alert-triangle'
    };
    const iconName = iconMap[type] || 'rule';
    return `<svg class="icon icon-small"><use href="#icon-${iconName}"></use></svg>`;
}

function getRuleGrowthTypeLabel(type) {
    const labels = {
        'rule_high_llm_expand': 'LLM 要求更多上下文',
        'rule_high_llm_skip': 'LLM 建议跳过',
        'rule_low_llm_consistent': '可提取新规则',
        'context_level_mismatch': '上下文级别不匹配'
    };
    return labels[type] || type;
}

function getConflictTypeLabel(conflictType) {
    const labels = {
        'rule_high_llm_expand': '规则高/LLM扩展',
        'rule_high_llm_skip': '规则高/LLM跳过',
        'rule_low_llm_consistent': '规则低/LLM一致',
        'context_level_mismatch': '上下文级别不匹配'
    };
    return labels[conflictType] || conflictType || '';
}

function getSuggestionTypeLabel(type) {
    const labels = {
        'upgrade_context_level': '提升上下文级别',
        'add_noise_detection': '添加噪音检测',
        'new_rule': '新增规则'
    };
    return labels[type] || type;
}

function getSuggestionTypeBadgeClass(type) {
    const classes = {
        'upgrade_context_level': 'warning',
        'add_noise_detection': 'info',
        'new_rule': 'success'
    };
    return classes[type] || '';
}

// ============================================================
// 渲染函数 - 可应用规则
// ============================================================

function renderApplicableRule(rule) {
    const tagsHtml = (rule.required_tags || []).map(tag =>
        `<span class="tag-badge">${escapeHtml(tag)}</span>`
    ).join('');

    return `
        <div class="applicable-rule-card" data-rule-id="${escapeHtml(rule.rule_id)}">
            <div class="rule-header">
                <span class="rule-language">${escapeHtml(rule.language)}</span>
                <span class="rule-tags">${tagsHtml}</span>
            </div>
            <div class="rule-body">
                <div class="rule-suggestion">
                    <svg class="icon"><use href="#icon-zap"></use></svg>
                    建议上下文级别: <strong>${escapeHtml(rule.suggested_context_level)}</strong>
                </div>
                <div class="rule-stats">
                    <span title="样本数量">${rule.sample_count} 次</span>
                    <span title="一致性">${Math.round(rule.consistency * 100)}% 一致</span>
                    <span title="不同文件数">${rule.unique_files} 文件</span>
                </div>
            </div>
            <div class="rule-warning">
                <svg class="icon"><use href="#icon-alert-triangle"></use></svg>
                <span>此规则将全局生效，影响所有匹配的代码变更</span>
            </div>
            <div class="rule-actions">
                <button class="btn-primary btn-small" onclick="applyRule('${escapeHtml(rule.rule_id)}')">
                    <svg class="icon"><use href="#icon-check"></use></svg>
                    确认并应用
                </button>
            </div>
        </div>
    `;
}

// ============================================================
// 渲染函数 - 参考提示
// ============================================================

function renderReferenceHint(hint) {
    const tagsHtml = (hint.tags || []).map(tag =>
        `<span class="tag-badge tag-muted">${escapeHtml(tag)}</span>`
    ).join('');

    // 安全序列化 hint，避免内联 JSON 破坏 onclick
    const hintEncoded = encodeURIComponent(JSON.stringify(hint));

    const consistencyPercent = Math.round((hint.consistency || 0) * 100);
    const hintId = `hint-${hint.language}-${(hint.tags || []).join('-')}-${Date.now()}`;

    // 渲染各信息块
    const conflictFilesHtml = renderConflictFilesBlock(hint);
    const decisionCompareHtml = renderDecisionCompareBlock(hint);
    const timeDistributionHtml = renderTimeDistributionBlock(hint);
    const unmetConditionsHtml = renderUnmetConditionsBlock(hint);

    return `
        <div class="reference-hint-card" data-hint-id="${escapeHtml(hintId)}">
            <!-- 摘要头部 -->
            <div class="hint-summary">
                <div class="hint-summary-row">
                    <span class="hint-language-badge">${escapeHtml(hint.language)}</span>
                    <span class="hint-tags">${tagsHtml}</span>
                </div>
                <div class="hint-summary-row">
                    <span class="hint-suggestion-text">
                        <svg class="icon icon-small"><use href="#icon-zap"></use></svg>
                        建议: ${escapeHtml(hint.suggested_context_level)}
                    </span>
                </div>
                <div class="hint-summary-row hint-metrics">
                    <span class="hint-metric">
                        <span class="metric-value">${hint.sample_count}</span> 次出现
                    </span>
                    <span class="hint-metric">
                        <span class="metric-value">${consistencyPercent}%</span> 一致性
                    </span>
                    <span class="hint-metric">
                        <span class="metric-value">${hint.unique_files || 0}</span> 文件
                    </span>
                </div>
            </div>
            
            <!-- 可折叠信息块 -->
            <div class="hint-info-blocks">
                ${conflictFilesHtml}
                ${decisionCompareHtml}
                ${timeDistributionHtml}
                ${unmetConditionsHtml}
            </div>
            
            <!-- 不可应用原因 -->
            <div class="hint-reason-section">
                <svg class="icon icon-small"><use href="#icon-alert-triangle"></use></svg>
                <span class="reason-text">${escapeHtml(hint.reason || '')}</span>
            </div>
            
            <!-- 手动提升按钮 -->
            <div class="hint-actions">
                <button class="btn-secondary btn-small hint-promote-btn" onclick="showPromoteHintDialog('${escapeHtml(hintId)}', decodeURIComponent('${hintEncoded}'))" title="手动提升为规则">
                    <svg class="icon"><use href="#icon-trending-up"></use></svg>
                    提升为规则
                </button>
            </div>
        </div>
    `;
}

// ============================================================
// 信息块渲染函数
// ============================================================

function renderConflictFilesBlock(hint) {
    const conflicts = hint.conflicts || [];
    const fileCount = conflicts.length || hint.unique_files || 0;

    let contentHtml = '';
    if (conflicts.length > 0) {
        const groupedFiles = groupFilesByDirectory(conflicts);
        contentHtml = renderGroupedFileList(groupedFiles);
    } else {
        contentHtml = `<div class="block-empty-state">
            <span class="text-muted">共 ${fileCount} 个文件涉及此模式</span>
        </div>`;
    }

    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-folder"></use></svg>
                <span class="block-title">冲突文件</span>
                <span class="block-badge">${fileCount}</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
}

function renderDecisionCompareBlock(hint) {
    const conflicts = hint.conflicts || [];

    let contentHtml = '';
    if (conflicts.length > 0) {
        const decisionStats = calculateDecisionStats(conflicts);
        contentHtml = renderDecisionStats(decisionStats);
    } else {
        contentHtml = `
            <div class="decision-compare-summary">
                <div class="decision-item">
                    <span class="decision-label">建议上下文级别:</span>
                    <span class="decision-value">${escapeHtml(hint.suggested_context_level || '')}</span>
                </div>
                <div class="decision-item">
                    <span class="decision-label">一致性:</span>
                    <span class="decision-value">${Math.round((hint.consistency || 0) * 100)}%</span>
                </div>
                <div class="decision-item">
                    <span class="decision-label">冲突类型:</span>
                    <span class="decision-value">${escapeHtml(getRuleGrowthTypeLabel(hint.conflict_type))}</span>
                </div>
            </div>
        `;
    }

    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-review"></use></svg>
                <span class="block-title">决策对比</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
}

function renderTimeDistributionBlock(hint) {
    const conflicts = hint.conflicts || [];

    let contentHtml = '';
    if (conflicts.length > 0) {
        const timeStats = calculateTimeDistribution(conflicts);
        contentHtml = renderTimeStats(timeStats);
    } else {
        contentHtml = `<div class="block-empty-state">
            <span class="text-muted">详细时间分布需要加载完整冲突数据</span>
        </div>`;
    }

    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-clock"></use></svg>
                <span class="block-title">时间分布</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
}

function renderUnmetConditionsBlock(hint) {
    const unmetConditions = hint.unmetConditions || hint.unmet_conditions || [];

    if (unmetConditions.length === 0) {
        return '';
    }

    const conditionsHtml = unmetConditions.map(condition => {
        const severity = calculateConditionSeverity(condition);
        const formattedValue = formatUnmetCondition(condition);
        const conditionName = condition.name || condition.condition_name || '未知条件';

        return `
            <div class="unmet-condition-item severity-${severity}">
                <span class="condition-name">${escapeHtml(conditionName)}</span>
                <span class="condition-values">${escapeHtml(formattedValue)}</span>
            </div>
        `;
    }).join('');

    return `
        <div class="collapsible-info-block collapsed" onclick="toggleInfoBlock(this)">
            <div class="block-header">
                <svg class="icon block-icon"><use href="#icon-alert-triangle"></use></svg>
                <span class="block-title">未满足条件</span>
                <span class="block-badge severity-indicator">${unmetConditions.length}</span>
                <svg class="icon block-chevron"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="block-content">
                <div class="block-content-inner">
                    <div class="unmet-conditions-list">
                        ${conditionsHtml}
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ============================================================
// 折叠控制函数
// ============================================================

function toggleInfoBlock(blockEl) {
    if (blockEl) {
        blockEl.classList.toggle('collapsed');
    }
}

function toggleLanguageGroup(groupId) {
    const groupEl = document.getElementById(groupId);
    if (groupEl) {
        groupEl.classList.toggle('collapsed');
    }
}

// ============================================================
// 分组函数
// ============================================================

function groupFilesByDirectory(conflicts) {
    const groups = {};

    for (const conflict of conflicts) {
        if (conflict.promoted) continue;

        const filePath = conflict.file_path || conflict.filePath || '';
        const lastSlash = filePath.lastIndexOf('/');
        const directory = lastSlash > 0 ? filePath.substring(0, lastSlash) : '(root)';
        const fileName = lastSlash > 0 ? filePath.substring(lastSlash + 1) : filePath;

        if (!groups[directory]) {
            groups[directory] = [];
        }

        groups[directory].push({
            fileName,
            filePath,
            conflictType: conflict.conflict_type || conflict.conflictType || '',
            timestamp: conflict.timestamp || '',
            language: conflict.language || 'unknown',
            llmContext: conflict.llm_context_level || conflict.llmContextLevel || '',
            ruleContext: conflict.rule_context_level || conflict.ruleContextLevel || '',
            ruleConfidence: conflict.rule_confidence ?? conflict.ruleConfidence,
            llmReason: conflict.llm_reason || conflict.llmReason || '',
            ruleNotes: conflict.rule_notes || conflict.ruleNotes || '',
            metrics: conflict.metrics || {},
            tags: conflict.tags || []
        });
    }

    return groups;
}

function groupHintsByLanguage(hints) {
    const groups = {};

    for (const hint of hints) {
        const language = hint.language || 'unknown';

        if (!groups[language]) {
            groups[language] = {
                count: 0,
                hints: [],
                expanded: false
            };
        }

        groups[language].hints.push(hint);
        groups[language].count++;
    }

    return groups;
}

function renderGroupedHintsByLanguage(hints) {
    if (!hints || hints.length === 0) {
        return '<div class="empty-state"><span class="text-muted">暂无参考提示</span></div>';
    }

    const groupedHints = groupHintsByLanguage(hints);
    const languages = Object.keys(groupedHints).sort();

    let html = '<div class="language-grouped-hints">';

    for (const language of languages) {
        const group = groupedHints[language];
        const languageId = `lang-group-${language.replace(/[^a-zA-Z0-9]/g, '-')}`;

        html += `
            <div class="language-group collapsed" data-language="${escapeHtml(language)}" id="${languageId}">
                <div class="language-group-header" onclick="toggleLanguageGroup('${languageId}')">
                    <svg class="icon language-chevron"><use href="#icon-chevron-down"></use></svg>
                    <span class="language-name">${escapeHtml(language)}</span>
                    <span class="language-count-badge">${group.count}</span>
                </div>
                <div class="language-group-content">
                    ${group.hints.map(hint => renderReferenceHint(hint)).join('')}
                </div>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

function renderGroupedFileList(groupedFiles) {
    const directories = Object.keys(groupedFiles).sort();

    if (directories.length === 0) {
        return '<div class="block-empty-state"><span class="text-muted">无文件数据</span></div>';
    }

    let html = '<div class="grouped-file-list">';

    for (const dir of directories) {
        const files = groupedFiles[dir];
        html += `
            <div class="file-group">
                <div class="file-group-header">
                    <svg class="icon icon-small"><use href="#icon-folder"></use></svg>
                    <span class="file-group-name">${escapeHtml(dir)}</span>
                    <span class="file-group-count">${files.length}</span>
                </div>
                <div class="file-group-items">
                    ${files.map(f => `
                        <div class="file-item">
                            <div class="file-head">
                                <span class="file-name" title="${escapeHtml(f.filePath)}">${escapeHtml(f.fileName)}</span>
                                ${f.conflictType ? `<span class="file-conflict-type">${escapeHtml(getConflictTypeLabel(f.conflictType))}</span>` : ''}
                                ${f.language ? `<span class="file-lang-badge">${escapeHtml(formatLanguageLabel(f.language))}</span>` : ''}
                            </div>
                            <div class="file-meta-row">
                                ${f.llmContext ? `<span class="tag-badge tag-muted">LLM: ${escapeHtml(f.llmContext)}</span>` : ''}
                                ${f.ruleContext ? `<span class="tag-badge">规则: ${escapeHtml(f.ruleContext)}</span>` : ''}
                                ${f.ruleConfidence !== undefined && f.ruleConfidence !== null ? `<span class="tag-badge tag-muted">置信 ${Math.round(f.ruleConfidence * 100)}%</span>` : ''}
                                ${f.timestamp ? `<span class="file-time">${formatTimestamp(f.timestamp)}</span>` : ''}
                            </div>
                            ${f.metrics && (f.metrics.added_lines || f.metrics.removed_lines || f.metrics.hunk_count) ? `
                                <div class="file-metrics">+${f.metrics.added_lines || 0} / -${f.metrics.removed_lines || 0} · 块 ${f.metrics.hunk_count || 0}</div>
                            ` : ''}
                            ${f.llmReason ? `<div class="file-reason" title="${escapeHtml(f.llmReason)}">${escapeHtml(truncateTextGlobal(f.llmReason, 120))}</div>` : ''}
                            ${f.ruleNotes ? `<div class="file-notes" title="${escapeHtml(f.ruleNotes)}">规则提示: ${escapeHtml(truncateTextGlobal(f.ruleNotes, 120))}</div>` : ''}
                            ${f.tags && f.tags.length ? `<div class="file-tags">${f.tags.slice(0, 4).map(t => `<span class="tag-badge tag-muted">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

// ============================================================
// 统计计算函数
// ============================================================

function calculateDecisionStats(conflicts) {
    const llmDecisions = {};
    const ruleDecisions = {};

    for (const conflict of conflicts) {
        const llmLevel = conflict.llm_context_level || conflict.llmContextLevel || 'unknown';
        const ruleLevel = conflict.rule_context_level || conflict.ruleContextLevel || 'unknown';

        llmDecisions[llmLevel] = (llmDecisions[llmLevel] || 0) + 1;
        ruleDecisions[ruleLevel] = (ruleDecisions[ruleLevel] || 0) + 1;
    }

    return { llmDecisions, ruleDecisions, total: conflicts.length };
}

function renderDecisionStats(stats) {
    let html = '<div class="decision-stats">';

    // LLM 决策分布
    html += '<div class="decision-section"><h5>LLM 决策分布</h5><div class="decision-bars">';
    for (const [level, count] of Object.entries(stats.llmDecisions)) {
        const percent = Math.round((count / stats.total) * 100);
        html += `
            <div class="decision-bar-item">
                <span class="bar-label">${escapeHtml(level)}</span>
                <div class="bar-container">
                    <div class="bar-fill" style="width: ${percent}%"></div>
                </div>
                <span class="bar-value">${count} (${percent}%)</span>
            </div>
        `;
    }
    html += '</div></div>';

    // 规则决策分布
    html += '<div class="decision-section"><h5>规则决策分布</h5><div class="decision-bars">';
    for (const [level, count] of Object.entries(stats.ruleDecisions)) {
        const percent = Math.round((count / stats.total) * 100);
        html += `
            <div class="decision-bar-item">
                <span class="bar-label">${escapeHtml(level)}</span>
                <div class="bar-container">
                    <div class="bar-fill bar-fill-rule" style="width: ${percent}%"></div>
                </div>
                <span class="bar-value">${count} (${percent}%)</span>
            </div>
        `;
    }
    html += '</div></div>';

    html += '</div>';
    return html;
}

function calculateTimeDistribution(conflicts) {
    const timestamps = conflicts
        .map(c => c.timestamp)
        .filter(t => t)
        .sort();

    if (timestamps.length === 0) {
        return { timestamps: [], earliest: null, latest: null };
    }

    return {
        timestamps,
        earliest: timestamps[0],
        latest: timestamps[timestamps.length - 1],
        count: timestamps.length
    };
}

function renderTimeStats(stats) {
    if (!stats.earliest) {
        return '<div class="block-empty-state"><span class="text-muted">无时间数据</span></div>';
    }

    return `
        <div class="time-stats">
            <div class="time-stat-item">
                <span class="time-label">最早记录:</span>
                <span class="time-value">${formatTimestamp(stats.earliest)}</span>
            </div>
            <div class="time-stat-item">
                <span class="time-label">最近记录:</span>
                <span class="time-value">${formatTimestamp(stats.latest)}</span>
            </div>
            <div class="time-stat-item">
                <span class="time-label">记录总数:</span>
                <span class="time-value">${stats.count}</span>
            </div>
        </div>
    `;
}

// ============================================================
// 条件格式化函数
// ============================================================

function formatUnmetCondition(condition) {
    const name = condition.name || '';
    const current = condition.currentValue;
    const required = condition.requiredValue;

    if (name.includes('一致性') || name.includes('consistency') || name.includes('percent')) {
        const currentPercent = typeof current === 'number' ? Math.round(current * 100) : current;
        const requiredPercent = typeof required === 'number' ? Math.round(required * 100) : required;
        return `${currentPercent}%/${requiredPercent}%`;
    } else if (name.includes('次') || name.includes('count') || name.includes('出现')) {
        return `${current}/${required} 次`;
    } else {
        return `${current}/${required}`;
    }
}

function calculateConditionSeverity(condition) {
    const current = condition.currentValue;
    const required = condition.requiredValue;

    if (typeof current !== 'number' || typeof required !== 'number' || required === 0) {
        return 'far';
    }

    const completionRatio = current / required;
    return completionRatio >= 0.7 ? 'close' : 'far';
}

// ============================================================
// 操作函数
// ============================================================

async function applyRule(ruleId) {
    if (!confirm('确定要应用此规则吗？此操作将影响全局规则配置。')) {
        return;
    }

    try {
        const res = await fetch('/api/rule-growth/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rule_id: ruleId })
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();

        if (data.error) {
            throw new Error(data.error);
        }

        showToast('规则已成功应用', 'success');
        await loadRuleGrowthData();

    } catch (e) {
        console.error('Apply rule error:', e);
        showToast('应用规则失败: ' + e.message, 'error');
    }
}

async function ruleGrowthCleanup() {
    if (!confirm('确定要清理 30 天前的冲突记录吗？')) {
        return;
    }

    try {
        const res = await fetch('/api/rule-growth/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_age_days: 30 })
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();

        if (data.error) {
            throw new Error(data.error);
        }

        const deleted = data.deleted_count || 0;
        const remaining = data.remaining_count || 0;

        showToast(`已清理 ${deleted} 条记录，剩余 ${remaining} 条`, 'success');
        await loadRuleGrowthData();

    } catch (e) {
        console.error('Rule growth cleanup error:', e);
        showToast('清理失败: ' + e.message, 'error');
    }
}

// ============================================================
// 提升对话框
// ============================================================

function showPromoteHintDialog(hintId, hintData) {
    let hint;
    try {
        hint = typeof hintData === 'string' ? JSON.parse(hintData) : hintData;
    } catch (e) {
        console.error('Failed to parse hint data:', e);
        showToast('无法解析提示数据', 'error');
        return;
    }

    const tagsHtml = (hint.tags || []).map(tag =>
        `<span class="tag-badge">${escapeHtml(tag)}</span>`
    ).join(' ');

    const consistencyPercent = Math.round((hint.consistency || 0) * 100);

    const dialogContent = `
        <div class="promote-hint-dialog">
            <div class="dialog-section">
                <h4>规则详情</h4>
                <div class="rule-detail-grid">
                    <div class="detail-row">
                        <span class="detail-label">语言:</span>
                        <span class="detail-value">${escapeHtml(hint.language || '')}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">标签:</span>
                        <span class="detail-value">${tagsHtml || '无'}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">建议上下文级别:</span>
                        <span class="detail-value">${escapeHtml(hint.suggested_context_level || hint.suggestedContextLevel || '')}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">样本数量:</span>
                        <span class="detail-value">${hint.sample_count || hint.sampleCount || 0} 次</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">一致性:</span>
                        <span class="detail-value">${consistencyPercent}%</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">涉及文件:</span>
                        <span class="detail-value">${hint.unique_files || hint.uniqueFiles || 0} 个</span>
                    </div>
                </div>
            </div>
            <div class="dialog-section warning-section">
                <svg class="icon"><use href="#icon-alert-triangle"></use></svg>
                <div class="warning-text">
                    <strong>注意:</strong> 此提示未满足自动应用条件。手动提升后，规则将应用到全局配置。
                    <div class="reason-detail">${escapeHtml(hint.reason || '')}</div>
                </div>
            </div>
        </div>
    `;

    showConfirmDialog({
        title: '提升为规则',
        content: dialogContent,
        confirmText: '确认提升',
        cancelText: '取消',
        onConfirm: () => promoteHintToRule(hint)
    });
}

function showConfirmDialog(options) {
    const existingDialog = document.getElementById('confirmDialog');
    if (existingDialog) {
        existingDialog.remove();
    }

    const dialog = document.createElement('div');
    dialog.id = 'confirmDialog';
    dialog.className = 'modal-overlay';
    dialog.innerHTML = `
        <div class="modal-container confirm-dialog-container">
            <div class="modal-header">
                <h3>${escapeHtml(options.title || '确认')}</h3>
                <button class="icon-btn modal-close-btn" onclick="closeConfirmDialog()">
                    <svg class="icon"><use href="#icon-x"></use></svg>
                </button>
            </div>
            <div class="modal-body">
                ${options.content || ''}
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeConfirmDialog()">${escapeHtml(options.cancelText || '取消')}</button>
                <button class="btn-primary" id="confirmDialogBtn">${escapeHtml(options.confirmText || '确认')}</button>
            </div>
        </div>
    `;

    document.body.appendChild(dialog);

    const confirmBtn = document.getElementById('confirmDialogBtn');
    if (confirmBtn && options.onConfirm) {
        confirmBtn.onclick = () => {
            closeConfirmDialog();
            options.onConfirm();
        };
    }

    dialog.onclick = (e) => {
        if (e.target === dialog) {
            closeConfirmDialog();
            if (options.onCancel) options.onCancel();
        }
    };
}

function closeConfirmDialog() {
    const dialog = document.getElementById('confirmDialog');
    if (dialog) {
        dialog.remove();
    }
}

async function promoteHintToRule(hint) {
    try {
        const promoteBtn = document.querySelector('.hint-promote-btn.loading') || document.querySelector('.hint-promote-btn:focus');
        if (promoteBtn) promoteBtn.classList.add('loading');

        const fallbackConflict = (hint.conflicts && hint.conflicts[0]) || null;
        const language = hint.language || (fallbackConflict && fallbackConflict.language) || 'unknown';
        const tags = Array.isArray(hint.tags) ? hint.tags : (fallbackConflict && fallbackConflict.tags) || [];

        const res = await fetch('/api/rule-growth/promote-hint', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                language,
                tags,
                suggested_context_level: hint.suggested_context_level || hint.suggestedContextLevel,
                sample_count: hint.sample_count || hint.sampleCount,
                consistency: hint.consistency,
                conflict_type: hint.conflict_type || hint.conflictType
            })
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || errData.error || `HTTP ${res.status}`);
        }

        const data = await res.json();

        if (data.error) {
            throw new Error(data.error);
        }

        showToast('提示已成功提升为规则', 'success');
        await loadRuleGrowthData();

    } catch (e) {
        console.error('Promote hint error:', e);
        showToast('提升失败: ' + e.message, 'error');
    } finally {
        const promoteBtn = document.querySelector('.hint-promote-btn.loading');
        if (promoteBtn) promoteBtn.classList.remove('loading');
    }
}

// ============================================================
// 帮助对话框函数
// ============================================================
/**
 * 显示参考提示帮助对话框
 * 
 * 为首次接触该板块的用户提供详细说明
 */
function showHintsHelp() {
    const helpContent = `
        <div class="dialog-body">
            <div class="md-doc">
                <aside class="md-sidebar">
                    <nav class="md-nav">
                        <div class="md-nav-title">目录</div>
                        <ul class="md-nav-list">
                            <li><a href="#sec-overview" class="active">核心机制</a></li>
                            <li><a href="#sec-conflict-types">冲突类型</a></li>
                            <li><a href="#sec-grouping">聚合维度</a></li>
                            <li><a href="#sec-consistency">一致性</a></li>
                            <li><a href="#sec-rule-hint">规则提示</a></li>
                            <li><a href="#sec-tags">标签作用</a></li>
                        </ul>
                    </nav>
                </aside>
            <main class="md-main">
                <section id="sec-overview" class="md-section">
                    <h2>什么是规则优化</h2>
                    <p>系统同时使用两种方式判断代码变更需要多少上下文信息：<strong>规则层</strong>（基于预设规则快速判断）和<strong>LLM 层</strong>（大语言模型深度分析）</p>
                    <p>当两者判断不一致时，系统记录为「冲突」。多个相似的冲突被聚合后，形成<strong>参考提示</strong>，供您判断是否需要更新规则配置</p>
                </section>

                <section id="sec-conflict-types" class="md-section">
                    <h2>冲突类型</h2>
                    <p>系统会检测以下四种冲突情况：</p>
                    <table class="md-table">
                        <tr>
                            <td><strong>规则高/LLM扩展</strong></td>
                            <td>规则层很有信心，但 LLM 认为需要更多上下文。说明规则可能<strong>低估了变更的复杂度</strong></td>
                        </tr>
                        <tr>
                            <td><strong>规则高/LLM跳过</strong></td>
                            <td>规则层认为需要审查，但 LLM 建议跳过。说明规则可能<strong>过度敏感</strong>，对无关紧要的变更也要求审查</td>
                        </tr>
                        <tr>
                            <td><strong>规则低/LLM明确</strong></td>
                            <td>规则层不确定（低置信度），但 LLM 给出了明确建议。这类冲突可用于<strong>发现新的规则模式</strong></td>
                        </tr>
                        <tr>
                            <td><strong>上下文级别不匹配</strong></td>
                            <td>规则层和 LLM 层建议的上下文级别差异较大</td>
                        </tr>
                    </table>
                </section>

                <section id="sec-grouping" class="md-section">
                    <h2>如何聚合</h2>
                    <p>系统按以下三个维度对冲突进行分组：</p>
                    <table class="md-table">
                        <tr><td><strong>编程语言</strong></td><td>如 Python、CSS、JavaScript 等</td></tr>
                        <tr><td><strong>语义标签</strong></td><td>代码变更的特征标签，如「完整类定义」「API端点」等</td></tr>
                        <tr><td><strong>冲突类型</strong></td><td>上述四种冲突类型之一</td></tr>
                    </table>
                    <p>具有相同语言、相同标签组合、相同冲突类型的记录会被归为同一组，统一分析</p>
                </section>

                <section id="sec-consistency" class="md-section">
                    <h2>一致性指标</h2>
                    <p><strong>一致性</strong>表示 LLM 在同一组冲突中给出相同建议的比例</p>
                    <p>计算方式：统计该组所有冲突中 LLM 的建议，找出最常见的建议，计算其占比</p>
                    <p>例如：某组有5次冲突，LLM 建议了4次「文件级上下文」、1次「函数级上下文」，则一致性为 <strong>80%</strong></p>
                    <div class="md-callout">
                        <p>一致性越高，说明 LLM 的判断越稳定，该提示的参考价值越高</p>
                    </div>
                </section>

                <section id="sec-rule-hint" class="md-section">
                    <h2>规则提示</h2>
                    <p><strong>py:fastapi:routers</strong> 是命中规则的路径标识：</p>
                    <ul class="md-list">
                        <li><strong>py</strong> — 语言：Python</li>
                        <li><strong>fastapi</strong> — 框架类型</li>
                        <li><strong>routers</strong> — 具体模块</li>
                    </ul>
                    <p>它告诉您这个变更命中了哪条规则，便于定位和调整规则配置</p>
                </section>

                <section id="sec-tags" class="md-section">
                    <h2>标签作用</h2>
                    <p><strong>clustered_changes</strong>、<strong>complete_class</strong> 等标签是代码变更的语义特征</p>
                    <p>系统按「语言 + 标签组合」聚合冲突。例如所有带有 complete_class + clustered_changes 标签的 Python 文件冲突会被归为同一模式</p>
                    <p>当某个标签组合反复触发相同类型的冲突时，说明现有规则对这类代码变更模式的判断可能存在系统性偏差</p>
                </section>
            </main>
        </div> <!-- Close md-doc -->
        </div> <!-- Close dialog-body -->
    `;

    showHelpDialog('参考提示', helpContent);
}

/**
 * 通用帮助对话框
 */
function showHelpDialog(title, content) {
    // 移除已存在的对话框
    const existingDialog = document.getElementById('help-dialog-overlay');
    if (existingDialog) {
        existingDialog.remove();
    }

    const dialogHtml = `
        <div id="help-dialog-overlay" class="dialog-overlay" onclick="closeHelpDialog(event)">
            <div class="dialog-box help-dialog" onclick="event.stopPropagation()">
                <div class="dialog-header">
                    <h3 class="dialog-title">
                        <svg class="icon" style="margin-right: 0.5rem; color: var(--primary);">
                            <use href="#icon-book"></use>
                        </svg>
                        ${escapeHtml(title)}
                    </h3>
                    <button class="dialog-close-btn" onclick="closeHelpDialog(event)" title="关闭">
                        <svg class="icon"><use href="#icon-x"></use></svg>
                    </button>
                </div>
                <div class="dialog-body" style="max-height: 70vh; overflow-y: auto;">
                    ${content}
                </div>
                <div class="dialog-footer" style="text-align: right; padding-top: 1rem; border-top: 1px solid var(--border);">
                    <button class="btn-primary" onclick="closeHelpDialog(event)">知了</button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', dialogHtml);

    // Scrollspy Logic
    const dialogBody = document.querySelector('.help-dialog .md-main'); // 监听主滚动区
    const navLinks = document.querySelectorAll('.md-nav-list a');
    const sections = document.querySelectorAll('.md-section');

    const handleScroll = () => {
        if (!dialogBody) return;

        let currentSectionId = '';
        const containerRect = dialogBody.getBoundingClientRect();
        const scrollTop = dialogBody.scrollTop;

        // 使用 getBoundingClientRect 计算相对于容器的位置
        for (const section of sections) {
            const sectionRect = section.getBoundingClientRect();
            // 计算 section 顶部相对于容器顶部的位置
            const relativeTop = sectionRect.top - containerRect.top;

            // 如果 section 顶部在容器顶部附近（允许 80px 的偏移）
            if (relativeTop <= 80) {
                currentSectionId = section.getAttribute('id');
            }
        }

        // 如果滚动到底部，强制选中最后一个
        if (dialogBody.scrollHeight - scrollTop <= dialogBody.clientHeight + 50) {
            const lastSection = sections[sections.length - 1];
            if (lastSection) currentSectionId = lastSection.getAttribute('id');
        }

        // 如果没有命中任何 section，默认选中第一个
        if (!currentSectionId && sections.length > 0) {
            currentSectionId = sections[0].getAttribute('id');
        }

        // 更新导航状态
        navLinks.forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('href') === `#${currentSectionId}`) {
                link.classList.add('active');
            }
        });
    };

    if (dialogBody) {
        dialogBody.addEventListener('scroll', handleScroll);
        // 初始化一次
        handleScroll();
    }

    // 添加 ESC 键关闭
    const handleEsc = (e) => {
        if (e.key === 'Escape') {
            closeHelpDialog(e);
            document.removeEventListener('keydown', handleEsc);
        }
    };
    document.addEventListener('keydown', handleEsc);
}

function closeHelpDialog(event) {
    if (event) event.stopPropagation();
    const overlay = document.getElementById('help-dialog-overlay');
    if (overlay) {
        overlay.remove();
    }
}



// ============================================================
// Export to window
// ============================================================

window.loadRuleGrowthData = loadRuleGrowthData;
window.loadRuleGrowthSummary = loadRuleGrowthSummary;
window.loadEnhancedSuggestions = loadEnhancedSuggestions;
window.getRuleGrowthTypeIcon = getRuleGrowthTypeIcon;
window.getRuleGrowthTypeLabel = getRuleGrowthTypeLabel;
window.getConflictTypeLabel = getConflictTypeLabel;
window.getSuggestionTypeLabel = getSuggestionTypeLabel;
window.getSuggestionTypeBadgeClass = getSuggestionTypeBadgeClass;
window.renderApplicableRule = renderApplicableRule;
window.renderReferenceHint = renderReferenceHint;
window.renderConflictFilesBlock = renderConflictFilesBlock;
window.renderDecisionCompareBlock = renderDecisionCompareBlock;
window.renderTimeDistributionBlock = renderTimeDistributionBlock;
window.renderUnmetConditionsBlock = renderUnmetConditionsBlock;
window.toggleInfoBlock = toggleInfoBlock;
window.toggleLanguageGroup = toggleLanguageGroup;
window.groupFilesByDirectory = groupFilesByDirectory;
window.groupHintsByLanguage = groupHintsByLanguage;
window.renderGroupedHintsByLanguage = renderGroupedHintsByLanguage;
window.renderGroupedFileList = renderGroupedFileList;
window.calculateDecisionStats = calculateDecisionStats;
window.renderDecisionStats = renderDecisionStats;
window.calculateTimeDistribution = calculateTimeDistribution;
window.renderTimeStats = renderTimeStats;
window.formatUnmetCondition = formatUnmetCondition;
window.calculateConditionSeverity = calculateConditionSeverity;
window.applyRule = applyRule;
window.ruleGrowthCleanup = ruleGrowthCleanup;
window.showPromoteHintDialog = showPromoteHintDialog;
window.showConfirmDialog = showConfirmDialog;
window.closeConfirmDialog = closeConfirmDialog;
window.promoteHintToRule = promoteHintToRule;
window.showConflictFilesHelp = showConflictFilesHelp;
window.showHintsHelp = showHintsHelp;
window.showHelpDialog = showHelpDialog;
window.closeHelpDialog = closeHelpDialog;

// ============================================================
// 初始化函数
// ============================================================

function initRuleGrowthPage() {
    console.log('[rule-growth] initRuleGrowthPage called');
    // 绑定帮助按钮点击事件
    const hintsHelpBtn = document.getElementById('hintsHelpBtn');
    console.log('[rule-growth] hintsHelpBtn element:', hintsHelpBtn);
    if (hintsHelpBtn) {
        hintsHelpBtn.addEventListener('click', function (e) {
            console.log('[rule-growth] Help button clicked');
            e.preventDefault();
            e.stopPropagation();
            showHintsHelp();
        });
        console.log('[rule-growth] Event listener attached');

        // ============================================================
        // 彩蛋：光束效果 - 当鼠标靠近时，按钮边缘朝向鼠标发光
        // ============================================================
        const PROXIMITY_THRESHOLD = 150; // 触发光束的距离（像素）
        const GLOW_INTENSITY = 8; // 光晕强度（像素）

        document.addEventListener('mousemove', function (e) {
            const rect = hintsHelpBtn.getBoundingClientRect();
            const btnCenterX = rect.left + rect.width / 2;
            const btnCenterY = rect.top + rect.height / 2;

            // 计算鼠标到按钮中心的距离
            const dx = e.clientX - btnCenterX;
            const dy = e.clientY - btnCenterY;
            const distance = Math.sqrt(dx * dx + dy * dy);

            if (distance <= rect.width / 2) {
                // 鼠标悬停在按钮上，显示最强光晕（360度环绕）
                hintsHelpBtn.style.boxShadow = `0 0 12px rgba(59, 130, 246, 0.6)`;
                hintsHelpBtn.style.filter = `brightness(1.1)`;
            } else if (distance < PROXIMITY_THRESHOLD) {
                // 鼠标靠近但未悬停，显示方向性光束
                const angle = Math.atan2(dy, dx);
                const glowX = Math.cos(angle) * GLOW_INTENSITY;
                const glowY = Math.sin(angle) * GLOW_INTENSITY;
                const intensity = 1 - (distance / PROXIMITY_THRESHOLD);
                const glowColor = `rgba(59, 130, 246, ${intensity * 0.8})`;
                const glowSpread = Math.round(4 + intensity * 6);

                hintsHelpBtn.style.boxShadow = `${glowX}px ${glowY}px ${glowSpread}px ${glowColor}`;
                hintsHelpBtn.style.filter = `brightness(${1 + intensity * 0.2})`;
            } else {
                // 超出范围，移除光晕
                hintsHelpBtn.style.boxShadow = 'none';
                hintsHelpBtn.style.filter = 'none';
            }
        });
    }
}

window.initRuleGrowthPage = initRuleGrowthPage;

// 自动初始化
(function () {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initRuleGrowthPage);
    } else {
        // DOM已加载，直接初始化
        initRuleGrowthPage();
    }
})();
