/**
 * config.js - 配置页面模块
 */

const CONFIG_LABELS = {
    "llm.call_timeout": "调用超时 (秒)",
    "llm.planner_timeout": "规划器超时 (秒)",
    "llm.max_retries": "最大重试次数",
    "llm.retry_delay": "重试延迟 (秒)",
    "context.max_context_chars": "单字段最大长度 (字符)",
    "context.full_file_max_lines": "全文件读取限制 (行)",
    "context.callers_max_hits": "调用者最大命中数",
    "context.file_cache_ttl": "文件缓存时间 (秒)",
    "review.max_units_per_batch": "单次审查最大单元数",
    "review.enable_intent_cache": "启用意图缓存",
    "review.intent_cache_ttl_days": "意图缓存过期天数",
    "review.stream_chunk_sample_rate": "流式日志采样率",
    "fusion_thresholds.high": "高置信度阈值",
    "fusion_thresholds.medium": "中置信度阈值",
    "fusion_thresholds.low": "低置信度阈值"
};

const CONFIG_DESCRIPTIONS = {
    "llm.call_timeout": "单次 LLM API 调用的最大等待时间，超时将自动中断。",
    "llm.planner_timeout": "规划阶段（分析代码结构）的最大等待时间。",
    "llm.max_retries": "API 调用失败时的最大重试次数。",
    "llm.retry_delay": "每次重试前的等待时间，避免频繁请求。",
    "context.max_context_chars": "单字段最大字符数；每个上下文字段分别截断。",
    "context.full_file_max_lines": "完整文件模式的最大行数，超过则按行截断或回退。",
    "context.callers_max_hits": "调用方搜索的最大命中数。",
    "context.file_cache_ttl": "文件内容在内存中的缓存时间，减少磁盘 IO。",
    "review.max_units_per_batch": "单次审查任务包含的最大代码单元数量。",
    "review.enable_intent_cache": "启用意图分析缓存。",
    "review.intent_cache_ttl_days": "意图缓存的过期天数。",
    "review.stream_chunk_sample_rate": "流式日志采样率。",
    "fusion_thresholds.high": "规则侧置信度≥此值时，以规则建议为主。",
    "fusion_thresholds.medium": "介于低/高之间为中等置信区间。",
    "fusion_thresholds.low": "规则侧置信度≤此值时，优先采纳 LLM 的上下文建议。"
};

async function loadConfig() {
    const configFormContainer = document.getElementById('config-form-container');
    if (!configFormContainer) return;
    
    configFormContainer.innerHTML = '<div class="loading-state">加载配置中...</div>';
    
    try {
        const configRes = await fetch('/api/config');

        if (!configRes.ok) {
            throw new Error(`HTTP ${configRes.status}`);
        }
        
        const config = await configRes.json();
        renderConfigForm(config, {});
    } catch (e) {
        console.error("Load config error:", e);
        configFormContainer.innerHTML = `<div class="error-state">加载配置失败: ${escapeHtml(e.message)}</div>`;
    }
}

function createConfigInput(fullKey, label, value) {
    const isBool = typeof value === 'boolean';
    const type = isBool ? 'checkbox' : (typeof value === 'number' ? 'number' : 'text');
    const checked = isBool && value ? 'checked' : '';
    const valueAttr = isBool ? '' : `value="${escapeHtml(String(value))}"`;
    
    const description = CONFIG_DESCRIPTIONS[fullKey];
    const tooltipHtml = description ? `
        <div class="tooltip-container">
            <svg class="icon icon-info tooltip-trigger"><use href="#icon-info"></use></svg>
            <div class="tooltip-content">${escapeHtml(description)}</div>
        </div>
    ` : '';
    
    if (isBool) {
        return `
            <div class="form-group form-group-checkbox">
                <label class="checkbox-label">
                    <span class="checkbox-text-container">
                        <span class="checkbox-text">${escapeHtml(label)}</span>
                        ${tooltipHtml}
                    </span>
                    <span class="checkbox-status ${checked ? 'status-enabled' : 'status-disabled'}">
                        ${checked ? '已启用' : '已禁用'}
                    </span>
                    <input type="${type}" data-key="${escapeHtml(fullKey)}" ${checked} class="toggle-checkbox" role="switch">
                </label>
            </div>
        `;
    }
    
    return `
        <div class="form-group">
            <div class="label-container">
                <label>${escapeHtml(label)}</label>
                ${tooltipHtml}
            </div>
            <input type="${type}" data-key="${escapeHtml(fullKey)}" ${valueAttr} class="config-input">
        </div>
    `;
}

function renderConfigForm(config, envVars = {}) {
    const configFormContainer = document.getElementById('config-form-container');
    if (!configFormContainer) return;
    
    let html = '';
    
    // LLM Config Section
    if (config.llm) {
        html += `<div class="config-section">
            <div class="section-header"><h3>LLM 配置</h3></div>`;
        for (const [key, val] of Object.entries(config.llm)) {
            if (typeof val === 'object' && val !== null) continue;
            const label = CONFIG_LABELS[`llm.${key}`] || key;
            html += createConfigInput(`llm.${key}`, label, val);
        }
        html += `</div>`;
    }

    // Context Config Section
    if (config.context) {
        html += `<div class="config-section"><h3>上下文配置</h3>`;
        for (const [key, val] of Object.entries(config.context)) {
            if (typeof val === 'object' && val !== null) continue;
            const label = CONFIG_LABELS[`context.${key}`] || key;
            html += createConfigInput(`context.${key}`, label, val);
        }
        html += `</div>`;
    }

    // Review Config Section
    if (config.review) {
        html += `<div class="config-section"><h3>审查配置</h3>`;
        for (const [key, val] of Object.entries(config.review)) {
            if (typeof val === 'object' && val !== null) continue;
            const label = CONFIG_LABELS[`review.${key}`] || key;
            html += createConfigInput(`review.${key}`, label, val);
        }
        html += `</div>`;
    }

    // Fusion Thresholds Section
    if (config.fusion_thresholds) {
        html += `<div class="config-section"><h3>融合阈值配置</h3>`;
        for (const [key, val] of Object.entries(config.fusion_thresholds)) {
            if (typeof val === 'object' && val !== null) continue;
            const label = CONFIG_LABELS[`fusion_thresholds.${key}`] || key;
            html += createConfigInput(`fusion_thresholds.${key}`, label, val);
        }
        html += `</div>`;
    }

    if (!html) {
        html = '<div class="empty-state">无可用配置项</div>';
    }
    
    configFormContainer.innerHTML = html;
    attachConfigInteractions();
}

function attachConfigInteractions() {
    const configFormContainer = document.getElementById('config-form-container');
    if (!configFormContainer) return;
    
    const labels = configFormContainer.querySelectorAll('.form-group-checkbox .checkbox-label');
    labels.forEach(label => {
        const input = label.querySelector('.toggle-checkbox');
        const status = label.querySelector('.checkbox-status');
        if (!input || !status) return;
        
        input.addEventListener('change', () => {
            const enabled = input.checked;
            status.textContent = enabled ? '已启用' : '已禁用';
            status.classList.toggle('status-enabled', enabled);
            status.classList.toggle('status-disabled', !enabled);
        });
        
        label.addEventListener('click', (e) => {
            if (e.target === input) return;
            input.click();
        });
    });
}

async function saveConfig() {
    const configFormContainer = document.getElementById('config-form-container');
    if (!configFormContainer) return;
    
    const inputs = configFormContainer.querySelectorAll('input');
    const updates = {};
    
    inputs.forEach(input => {
        const key = input.dataset.key;
        if (!key) return;
        
        const parts = key.split('.');
        if (parts.length < 2) return;
        
        const section = parts[0];
        const field = parts[1];
        
        if (!updates[section]) updates[section] = {};
        
        if (input.type === 'checkbox') {
            updates[section][field] = input.checked;
        } else if (input.type === 'number') {
            updates[section][field] = Number(input.value) || 0;
        } else {
            updates[section][field] = input.value;
        }
    });
    
    try {
        const res = await fetch('/api/config', {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ updates: updates, persist: true })
        });
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        showToast('配置已保存！', 'success');
    } catch (e) {
        console.error("Save config error:", e);
        showToast('保存失败: ' + e.message, 'error');
    }
}

// Export to window
window.loadConfig = loadConfig;
window.saveConfig = saveConfig;
window.renderConfigForm = renderConfigForm;
window.createConfigInput = createConfigInput;
window.attachConfigInteractions = attachConfigInteractions;
