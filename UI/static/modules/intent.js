/**
 * intent.js - 意图分析面板模块
 */

let currentIntentModel = "";  // 将由 renderIntentModelDropdown 设置
window.intentContent = window.intentContent || "";

function initIntentPanel() {
    if (document.getElementById('intentModelDropdown')) {
        if (window.availableGroups) {
            renderIntentModelDropdown(window.availableGroups);
        }
    }

    const trigger = document.getElementById('intentModelDropdownTrigger');
    if (trigger) {
        trigger.onclick = (e) => {
            e.stopPropagation();
            const dropdown = document.getElementById('intentModelDropdown');
            if (dropdown) dropdown.classList.toggle('open');
        };
    }

    // 思考过程折叠/展开
    const thoughtHeaderToggle = document.getElementById('thought-header-toggle');
    if (thoughtHeaderToggle) {
        thoughtHeaderToggle.onclick = () => {
            const container = document.getElementById('intent-thought-container');
            if (container) {
                container.classList.toggle('collapsed');
            }
        };
    }

    document.addEventListener('click', (e) => {
        const dropdown = document.getElementById('intentModelDropdown');
        if (dropdown && dropdown.classList.contains('open') && !dropdown.contains(e.target)) {
            dropdown.classList.remove('open');
        }
    });
}

function renderIntentModelDropdown(groupsData) {
    const menu = document.getElementById('intentModelDropdownMenu');
    if (!menu) return;

    menu.innerHTML = '';

    // 移除了 Auto 选项

    if (!groupsData || groupsData.length === 0) return;

    let firstAvailableModel = null;

    groupsData.forEach(group => {
        const providerName = group.label || group.provider || 'Unknown';
        const models = group.models || [];

        if (models.length === 0) return;

        const header = document.createElement('div');
        header.className = 'dropdown-group-header';
        header.innerHTML = `<span>${escapeHtml(providerName)}</span>`;
        menu.appendChild(header);

        models.forEach(m => {
            const item = document.createElement('div');
            const modelName = m.name || '';
            const modelLabel = m.label || m.name || '';
            const isAvailable = m.available !== false;

            // 记录第一个可用模型
            if (isAvailable && !firstAvailableModel) {
                firstAvailableModel = { name: modelName, label: modelLabel };
            }

            item.className = `dropdown-item ${currentIntentModel === modelName ? 'selected' : ''}`;
            if (!isAvailable) {
                item.style.opacity = '0.5';
                item.style.cursor = 'not-allowed';
            }

            item.innerHTML = `<span>${escapeHtml(modelLabel)}</span>`;

            if (isAvailable) {
                item.onclick = () => selectIntentModel(modelName, modelLabel);
            }

            menu.appendChild(item);
        });
    });

    // 如果尚未选择模型，自动选择第一个可用模型
    if (!currentIntentModel && firstAvailableModel) {
        selectIntentModel(firstAvailableModel.name, firstAvailableModel.label);
    }
}

function selectIntentModel(model, displayName) {
    currentIntentModel = model;

    const selectedText = document.getElementById('intentSelectedModelText');
    if (selectedText) selectedText.textContent = displayName;

    const dropdown = document.getElementById('intentModelDropdown');
    if (dropdown) dropdown.classList.remove('open');

    const items = document.querySelectorAll('#intentModelDropdownMenu .dropdown-item');
    items.forEach(item => item.classList.remove('selected'));

    event.target.closest('.dropdown-item')?.classList.add('selected');
}

async function runIntentAnalysis() {
    if (!window.currentProjectRoot) {
        showToast("请先选择项目文件夹", "error");
        return;
    }

    const btn = document.getElementById('intent-analyze-btn');
    if (typeof setButtonLoading === 'function') setButtonLoading(btn, true);

    const thoughtContainer = document.getElementById('intent-thought-container');
    const thoughtContent = document.getElementById('intent-thought-content');
    const thoughtStatus = document.getElementById('thought-status');
    const contentView = document.getElementById('intent-view');
    const contentDiv = document.getElementById('intent-content');
    const emptyState = document.getElementById('intent-empty');

    // Reset UI
    if (emptyState) emptyState.style.display = 'none';
    if (contentView) contentView.style.display = 'block';
    if (contentDiv) contentDiv.innerHTML = '';
    if (thoughtContainer) thoughtContainer.style.display = 'none';
    if (thoughtContent) thoughtContent.innerHTML = '';
    if (thoughtStatus) thoughtStatus.textContent = "";

    let fullContent = "";
    let fullThought = "";

    try {
        // 使用意图模型选择器的值（currentIntentModel）
        const modelToUse = currentIntentModel;
        console.log('[Intent] currentIntentModel:', currentIntentModel);
        console.log('[Intent] modelToUse:', modelToUse);

        if (!modelToUse) {
            showToast("请先在意图面板选择模型", "error");
            if (typeof setButtonLoading === 'function') setButtonLoading(btn, false);
            return;
        }

        const response = await fetch("/api/intent/analyze_stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                project_root: window.currentProjectRoot,
                model: modelToUse
            })
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    try {
                        const evt = JSON.parse(line.slice(6));

                        if (evt.type === "thought") {
                            if (thoughtContainer && thoughtContainer.style.display === 'none') {
                                thoughtContainer.style.display = 'block';
                                thoughtContainer.classList.remove('collapsed');
                                if (thoughtStatus) thoughtStatus.textContent = "思考中...";
                            }
                            fullThought += evt.content;
                            if (thoughtContent) {
                                thoughtContent.textContent = fullThought;
                                thoughtContent.scrollTop = thoughtContent.scrollHeight;
                            }
                        } else if (evt.type === "chunk") {
                            fullContent += evt.content;
                            if (contentDiv) contentDiv.innerHTML = marked.parse(fullContent);
                        } else if (evt.type === "final") {
                            if (evt.content) {
                                fullContent = evt.content;
                                if (contentDiv) contentDiv.innerHTML = marked.parse(fullContent);
                            }
                            // 思考结束，自动折叠
                            if (thoughtContainer && fullThought) {
                                thoughtContainer.classList.add('collapsed');
                                if (thoughtStatus) thoughtStatus.textContent = "已完成";
                            }
                        } else if (evt.type === "error") {
                            showToast("分析出错: " + evt.message, "error");
                        }
                    } catch (e) {
                        console.error("SSE Parse Error", e);
                    }
                }
            }
        }

        window.intentContent = fullContent;

    } catch (e) {
        console.error("Intent Analysis Error:", e);
        showToast("分析失败: " + e.message, "error");
        if (contentDiv && !fullContent) {
            contentDiv.innerHTML = `<p class="error-text">分析失败: ${escapeHtml(e.message)}</p>`;
        }
    } finally {
        if (typeof setButtonLoading === 'function') setButtonLoading(btn, false);
    }
}

function enterIntentEditMode() {
    const viewMode = document.getElementById('intent-view');
    const textarea = document.getElementById('intent-textarea');
    const actions = document.getElementById('intent-edit-actions');
    const contentDiv = document.getElementById('intent-content');

    if (textarea && viewMode && actions) {
        textarea.value = window.intentContent || (contentDiv ? contentDiv.innerText : "");

        viewMode.style.display = 'none';
        textarea.style.display = 'block';
        actions.style.display = 'flex';

        textarea.focus();
    }
}

function cancelIntentEdit() {
    const viewMode = document.getElementById('intent-view');
    const textarea = document.getElementById('intent-textarea');
    const actions = document.getElementById('intent-edit-actions');

    if (viewMode && textarea && actions) {
        viewMode.style.display = 'block';
        textarea.style.display = 'none';
        actions.style.display = 'none';
    }
}

async function saveIntentEdit() {
    const textarea = document.getElementById('intent-textarea');
    if (!textarea) return;

    const newContent = textarea.value;
    console.log('[Intent] saveIntentEdit newContent length:', newContent?.length);
    console.log('[Intent] newContent first 100 chars:', newContent?.substring(0, 100));

    // Optimistic update - 先更新 UI
    window.intentContent = newContent;
    const contentDiv = document.getElementById('intent-content');
    if (contentDiv) {
        const parsed = marked.parse(newContent);
        console.log('[Intent] marked.parse result first 200 chars:', parsed?.substring(0, 200));
        contentDiv.innerHTML = parsed;
    }

    cancelIntentEdit();

    // Persist to backend
    if (window.currentProjectRoot) {
        try {
            const res = await fetch('/api/intent/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_root: window.currentProjectRoot,
                    content: newContent
                })
            });

            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }

            const result = await res.json();
            if (result.success) {
                showToast('意图已保存', 'success');
            } else {
                showToast('保存失败: ' + (result.error || 'Unknown error'), 'error');
            }
        } catch (e) {
            console.error("Save intent error:", e);
            showToast('保存请求失败: ' + e.message, 'error');
        }
    } else {
        showToast('未选择项目，仅本地更新', 'warning');
    }
}

// Export to window
window.initIntentPanel = initIntentPanel;
window.renderIntentModelDropdown = renderIntentModelDropdown;
window.selectIntentModel = selectIntentModel;
window.runIntentAnalysis = runIntentAnalysis;
window.enterIntentEditMode = enterIntentEditMode;
window.cancelIntentEdit = cancelIntentEdit;
window.saveIntentEdit = saveIntentEdit;

