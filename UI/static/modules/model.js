/**
 * model.js - 模型管理模块
 */

const OPTIONS_MAX_RETRIES = 2;
const OPTIONS_RETRY_DELAY = 800; // ms

function renderToolListError(toolListContainer, message, showRetry = true) {
    if (!toolListContainer) return;
    toolListContainer.innerHTML = `
        <div class="error-state" style="padding:0.5rem;text-align:center;">
            <span style="color:#dc2626;font-size:0.85rem;">${message}</span>
            ${showRetry ? `<button class="btn-text" onclick="loadOptions()" style="margin-left:0.5rem;">重试</button>` : ''}
        </div>
    `;
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function loadOptions(retryCount = 0) {
    const selectedModelText = document.getElementById('selectedModelText');
    const modelDropdownMenu = document.getElementById('modelDropdownMenu');
    const toolListContainer = document.getElementById('toolListContainer');

    try {
        const res = await fetch('/api/options', { cache: 'no-store' });
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();

        // Render Models - data.models 已经是分组格式
        window.availableGroups = data.models || [];
        window.availableModels = window.availableGroups;
        renderModelMenu(window.availableGroups);

        // 如果尚未选择模型，自动选择第一个可用模型
        const groups = Array.isArray(window.availableGroups) ? window.availableGroups : [];
        let selectedAvailable = false;
        if (window.currentModelValue) {
            for (const g of groups) {
                const models = Array.isArray(g && g.models) ? g.models : [];
                const hit = models.find(m => m && m.name === window.currentModelValue);
                if (hit) {
                    selectedAvailable = hit.available !== false;
                    break;
                }
            }
        }

        if (!window.currentModelValue || !selectedAvailable) {
            let firstModel = null;
            for (const g of groups) {
                const models = Array.isArray(g && g.models) ? g.models : [];
                const hit = models.find(m => m && m.available !== false);
                if (hit) {
                    firstModel = hit;
                    break;
                }
            }
            if (firstModel) {
                selectModel(firstModel.name, firstModel.label || firstModel.name);
            }
        }

        if (typeof renderIntentModelDropdown === 'function') {
            renderIntentModelDropdown(window.availableGroups);
        }

        // Render Manage Models UI
        if (typeof renderManageModelsList === 'function') {
            renderManageModelsList();
        }

        // Render Tools
        if (toolListContainer) {
            const tools = data.tools || [];
            if (tools.length === 0) {
                toolListContainer.innerHTML = '<span class="text-muted" style="font-size:0.85rem;">无可用工具</span>';
                return;
            }
            toolListContainer.innerHTML = "";

            // 获取静态扫描开关状态
            const enableStaticScanInput = document.getElementById('enableStaticScan');
            const staticScanEnabled = enableStaticScanInput ? enableStaticScanInput.checked : false;

            tools.forEach(tool => {
                const label = document.createElement("label");
                const toolName = tool.name || '';
                const toolDesc = tool.description || toolName;  // 使用描述，无则用名称
                const isDefault = tool.default === true;

                // 特殊处理：get_scanner_results 工具绑定到静态扫描开关
                const isScannerResultsTool = toolName === 'get_scanner_results';

                if (isScannerResultsTool) {
                    // 此工具与静态扫描绑定，根据静态扫描开关状态决定是否选中
                    const isChecked = staticScanEnabled;
                    label.className = `tool-item ${isChecked ? 'checked' : ''} scanner-bound-tool`;
                    label.title = toolDesc;  // 显示工具作用
                    label.innerHTML = `
                        <input type="checkbox" value="${escapeHtml(toolName)}" ${isChecked ? 'checked' : ''}>
                        ${escapeHtml(toolName)}
                    `;
                    // 点击时检查静态扫描状态
                    label.onclick = (e) => {
                        const staticScanInput = document.getElementById('enableStaticScan');
                        const staticScanOn = staticScanInput && staticScanInput.checked;
                        if (!staticScanOn) {
                            e.preventDefault();
                            e.stopPropagation();
                            showToast('请先启用"静态分析"选项后，此工具将自动激活', 'warning');
                            return false;
                        }
                    };
                } else {
                    // 普通工具
                    label.className = `tool-item ${isDefault ? 'checked' : ''}`;
                    label.title = toolDesc;  // 显示工具作用
                    label.innerHTML = `
                        <input type="checkbox" value="${escapeHtml(toolName)}" ${isDefault ? 'checked' : ''}>
                        ${escapeHtml(toolName)}
                    `;
                    const checkbox = label.querySelector('input');
                    checkbox.onchange = () => {
                        if (checkbox.checked) label.classList.add('checked');
                        else label.classList.remove('checked');
                    };
                }
                toolListContainer.appendChild(label);
            });

            // 设置静态扫描开关的联动监听器
            if (enableStaticScanInput && !enableStaticScanInput._scannerToolListenerBound) {
                enableStaticScanInput._scannerToolListenerBound = true;
                enableStaticScanInput.addEventListener('change', function () {
                    const scannerToolLabel = toolListContainer.querySelector('.scanner-bound-tool');
                    if (scannerToolLabel) {
                        const checkbox = scannerToolLabel.querySelector('input');
                        if (this.checked) {
                            checkbox.checked = true;
                            scannerToolLabel.classList.add('checked');
                        } else {
                            checkbox.checked = false;
                            scannerToolLabel.classList.remove('checked');
                        }
                    }
                });
            }
        }

    } catch (e) {
        console.error("Load options error:", e);
        if (retryCount < OPTIONS_MAX_RETRIES) {
            const attemptsText = `加载失败，正在重试 (${retryCount + 1}/${OPTIONS_MAX_RETRIES + 1})...`;
            renderToolListError(toolListContainer, attemptsText, false);
            await delay(OPTIONS_RETRY_DELAY * (retryCount + 1));
            return loadOptions(retryCount + 1);
        }
        renderToolListError(toolListContainer, '加载失败', true);
    }
}

function renderModelMenu(groups) {
    const modelDropdownMenu = document.getElementById('modelDropdownMenu');
    if (!modelDropdownMenu) return;

    modelDropdownMenu.innerHTML = "";

    if (!groups || groups.length === 0) {
        modelDropdownMenu.innerHTML = '<div class="dropdown-item" style="color:var(--text-muted);">无可用模型</div>';
        return;
    }

    groups.forEach(g => {
        const groupDiv = document.createElement("div");
        groupDiv.className = "dropdown-group-container expanded";

        const providerLabel = escapeHtml(g.label || (g.provider ? g.provider.toUpperCase() : '未知'));
        const models = g.models || [];

        groupDiv.innerHTML = `
            <div class="dropdown-group-header">
                <span>${providerLabel}</span>
                <svg class="icon chevron-dropdown"><use href="#icon-chevron-down"></use></svg>
            </div>
            <div class="dropdown-group-models">
                ${models.map(m => {
            const modelName = escapeHtml(m.name || '');
            const modelLabel = escapeHtml(m.label || m.name || '');
            const isSelected = m.name === window.currentModelValue;
            const isAvailable = m.available !== false;
            // glm-4.7 警告标识
            const isGlm47 = m.label === 'glm-4.7' || m.name === 'glm:glm-4.7';
            const warningIcon = isGlm47 ? '<svg class="icon model-warning-icon" style="width:14px;height:14px;color:#f59e0b;margin-left:4px;"><use href="#icon-alert-triangle"></use></svg>' : '';
            return `
                    <div class="dropdown-item ${isSelected ? 'selected' : ''}${isGlm47 ? ' has-warning' : ''}" 
                         style="${!isAvailable ? 'opacity:0.5;cursor:not-allowed;' : ''}"
                         data-value="${modelName}" 
                         data-label="${modelLabel}"
                         data-available="${isAvailable ? 'true' : 'false'}"
                         data-has-warning="${isGlm47 ? 'true' : 'false'}">
                        <span>${modelLabel}</span>${warningIcon}
                    </div>`;
        }).join('')}
            </div>
        `;

        // Toggle group expansion
        const header = groupDiv.querySelector('.dropdown-group-header');
        if (header) {
            header.onclick = (e) => {
                e.stopPropagation();
                groupDiv.classList.toggle('expanded');
            };
        }

        // Bind click events to model items
        const items = groupDiv.querySelectorAll('.dropdown-item');
        items.forEach(item => {
            item.onclick = (e) => {
                e.stopPropagation();
                if (item.dataset.available === 'true') {
                    selectModel(item.dataset.value, item.dataset.label);
                }
            };
        });

        modelDropdownMenu.appendChild(groupDiv);
    });
}

function selectModel(val, label) {
    console.log('[Model] selectModel called with:', val, label);
    window.currentModelValue = val;
    console.log('[Model] window.currentModelValue is now:', window.currentModelValue);

    const selectedModelText = document.getElementById('selectedModelText');
    if (selectedModelText) selectedModelText.textContent = label;

    const modelDropdown = document.getElementById('modelDropdown');
    if (modelDropdown) modelDropdown.classList.remove('open');

    // Update selected state in menu
    const items = document.querySelectorAll('#modelDropdownMenu .dropdown-item');
    items.forEach(item => {
        if (item.dataset.value === val) {
            item.classList.add('selected');
        } else {
            item.classList.remove('selected');
        }
    });

    // glm-4.7 警告提示
    if (label === 'glm-4.7' || val === 'glm:glm-4.7') {
        showToast('此模型在本系统内极易陷入思考循环，建议谨慎选择', 'warning', 5000);
    }
}

function toggleModelDropdown(e) {
    if (e) e.stopPropagation();
    const modelDropdown = document.getElementById('modelDropdown');
    if (modelDropdown) modelDropdown.classList.toggle('open');
}

function openManageModelsModal() {
    const modal = document.getElementById('manageModelsModal');
    if (modal) {
        modal.style.display = 'flex';
        loadModelProviders();
        renderManageModelsList();
    }
}

function closeManageModelsModal() {
    const modal = document.getElementById('manageModelsModal');
    if (modal) modal.style.display = 'none';
}

async function loadModelProviders() {
    const providerSelectContainer = document.getElementById('providerSelectContainer');
    if (!providerSelectContainer) return;

    try {
        const res = await fetch('/api/providers/status');
        if (!res.ok) throw new Error('Failed to load providers');
        const providers = await res.json();

        let html = '<select id="providerSelect" class="provider-select">';
        providers.forEach(p => {
            html += `<option value="${escapeHtml(p.name)}">${escapeHtml(p.label || p.name)}</option>`;
        });
        html += '</select>';

        providerSelectContainer.innerHTML = html;
    } catch (e) {
        providerSelectContainer.innerHTML = '<span class="error-text">加载失败</span>';
    }
}

function renderManageModelsList() {
    const list = document.getElementById('modelList');
    if (!list) return;

    list.innerHTML = "";

    if (!window.availableGroups || window.availableGroups.length === 0) {
        list.innerHTML = '<div class="empty-state">暂无模型</div>';
        return;
    }

    window.availableGroups.forEach(g => {
        const groupDiv = document.createElement("div");
        groupDiv.className = "model-group-item";

        const providerName = g.label || g.provider;
        const models = g.models || [];

        const modelsHtml = models.map(m => `
            <div class="model-list-row">
                <span class="model-name" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</span>
                <button class="icon-btn-small delete-btn" onclick="deleteModel('${g.provider}', '${escapeHtml(m.label || m.name)}')">
                    ${getIcon('trash')}
                </button>
            </div>
        `).join('');

        groupDiv.innerHTML = `
            <div class="group-header"><strong>${escapeHtml(providerName)}</strong><span class="count-badge">${models.length}</span></div>
            <div class="group-body">${modelsHtml}</div>
        `;
        list.appendChild(groupDiv);
    });
}

async function addModel() {
    const providerSelect = document.getElementById('providerSelect');
    const nameInput = document.getElementById('newModelName');

    if (!providerSelect || !nameInput) return;

    const provider = providerSelect.value;
    const name = nameInput.value.trim();

    if (!name) {
        showToast("请输入模型名称", "warning");
        return;
    }

    try {
        const res = await fetch('/api/models/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, model_name: name })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Add failed");
        }

        nameInput.value = '';
        await loadOptions();
        renderManageModelsList();
        showToast("模型添加成功", "success");

    } catch (e) {
        showToast("添加失败: " + e.message, "error");
    }
}

async function deleteModel(provider, modelName) {
    if (!confirm(`确定要删除模型 ${modelName} 吗？`)) return;

    try {
        const res = await fetch('/api/models/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, model_name: modelName })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Delete failed");
        }

        await loadOptions();
        renderManageModelsList();
        showToast("模型删除成功", "success");

    } catch (e) {
        showToast("删除失败: " + e.message, "error");
    }
}

// Export to window
window.loadOptions = loadOptions;
window.renderModelMenu = renderModelMenu;
window.selectModel = selectModel;
window.toggleModelDropdown = toggleModelDropdown;
window.openManageModelsModal = openManageModelsModal;
window.closeManageModelsModal = closeManageModelsModal;
window.loadModelProviders = loadModelProviders;
window.renderManageModelsList = renderManageModelsList;
window.addModel = addModel;
window.deleteModel = deleteModel;
