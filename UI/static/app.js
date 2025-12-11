/**
 * app.js - 代码审查系统前端入口文件
 * 
 * 这是模块化架构的入口文件，负责：
 * 1. 初始化应用
 * 2. 绑定全局事件
 * 3. 加载初始数据
 * 
 * 所有功能模块位于 /modules/ 目录下
 * 原始完整代码备份在 main.js.backup
 */

// ============================================================
// 应用初始化
// ============================================================

document.addEventListener('DOMContentLoaded', async () => {
    console.log('[App] Application initializing...');

    try {
        // 1. 初始化全局状态
        initializeGlobalState();

        // 2. 绑定全局事件
        bindGlobalEvents();

        // 3. 初始化 ScannerUI 模块
        initScannerUI();

        // 4. 默认显示审查页面
        if (typeof switchPage === 'function') {
            switchPage('review');
        }

        // 5. 环境检测（确保依赖准备就绪）
        await checkEnvironment();

        // 6. 加载初始数据
        await loadInitialData();

        // 7. 加载会话列表
        if (typeof loadSessions === 'function') {
            await loadSessions();
        }

        // 8. 更新后台任务指示器
        if (typeof updateBackgroundTaskIndicator === 'function') {
            updateBackgroundTaskIndicator();
        }

        // 9. 初始化意图面板
        if (typeof initIntentPanel === 'function') {
            initIntentPanel();
        }

        // 10. 启动健康检查定时器
        setInterval(() => {
            if (typeof updateHealthStatus === 'function') {
                updateHealthStatus();
            }
        }, 30000);

        console.log('[App] Application initialized successfully');
    } catch (error) {
        console.error('[App] Application initialization failed:', error);
        if (typeof showToast === 'function') {
            showToast('应用初始化失败: ' + error.message, 'error');
        }
    }
});

// ============================================================
// 全局状态初始化
// ============================================================

function initializeGlobalState() {
    // 初始化布局状态
    if (typeof setLayoutState === 'function' && typeof LayoutState !== 'undefined') {
        setLayoutState(LayoutState.INITIAL);
    }

    // 确保没有当前会话
    window.currentSessionId = null;

    // 初始化进度面板
    if (typeof resetProgress === 'function') {
        resetProgress();
    }

    console.log('[App] Global state initialized');
}

// ============================================================
// ScannerUI 初始化
// ============================================================

function initScannerUI() {
    if (typeof ScannerUI !== 'undefined') {
        const scannerSection = document.getElementById('scannerWorkflowSection');
        if (scannerSection && typeof ScannerUI.init === 'function') {
            ScannerUI.init(scannerSection);
            console.log('[App] ScannerUI initialized');
        }
    }
}

// ============================================================
// 环境检测
// ============================================================

async function checkEnvironment() {
    try {
        const res = await fetch('/api/system/env');
        if (!res.ok) return;
        const data = await res.json();
        window.isDockerEnv = !!(data && data.is_docker);
        window.defaultProjectRoot = data && data.default_project_root ? data.default_project_root : null;
        window.platform = (data && data.platform) ? data.platform : null;
        console.log('[App] Environment detected:', { platform: window.platform, isDocker: window.isDockerEnv });
    } catch (e) {
        console.warn('[App] Environment check failed:', e);
    }
}

// ============================================================
// 全局事件绑定
// ============================================================

function bindGlobalEvents() {
    // 文件夹选择按钮
    const pickFolderBtn = document.getElementById('pickFolderBtn');
    if (pickFolderBtn) {
        pickFolderBtn.addEventListener('click', () => {
            if (typeof pickFolder === 'function') {
                pickFolder();
            } else if (typeof openFolderPicker === 'function') {
                openFolderPicker();
            }
        });
    }

    // 开始审查按钮
    const startReviewBtn = document.getElementById('startReviewBtn');
    if (startReviewBtn) {
        startReviewBtn.addEventListener('click', () => {
            if (typeof startReview === 'function') {
                startReview();
            }
        });
    }

    // 发送按钮
    const sendBtn = document.getElementById('sendBtn');
    if (sendBtn) {
        sendBtn.addEventListener('click', () => {
            if (typeof sendMessage === 'function') {
                sendMessage();
            }
        });
    }

    // 历史记录抽屉
    const historyToggleBtn = document.getElementById('historyToggleBtn');
    const historyDrawer = document.getElementById('historyDrawer');
    const closeHistoryBtn = document.getElementById('closeHistoryBtn');

    if (historyToggleBtn) {
        historyToggleBtn.addEventListener('click', () => {
            if (typeof toggleHistoryDrawer === 'function') {
                toggleHistoryDrawer();
            } else if (historyDrawer) {
                historyDrawer.classList.toggle('open');
                if (historyDrawer.classList.contains('open') && typeof loadSessions === 'function') {
                    loadSessions();
                }
            }
        });
    }

    if (closeHistoryBtn && historyDrawer) {
        closeHistoryBtn.addEventListener('click', () => {
            historyDrawer.classList.remove('open');
        });
    }

    // 报告面板返回按钮
    const reportBackBtn = document.getElementById('reportBackBtn');
    if (reportBackBtn) {
        reportBackBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (typeof reportGoBack === 'function') {
                reportGoBack();
            }
        });
    }

    // 历史模式返回按钮
    const historyBackBtn = document.getElementById('historyBackBtn');
    if (historyBackBtn) {
        historyBackBtn.addEventListener('click', () => {
            if (typeof exitHistoryMode === 'function') {
                exitHistoryMode();
            } else if (typeof returnToNewWorkspace === 'function') {
                returnToNewWorkspace();
            }
        });
    }

    // 后台任务按钮
    const backgroundTaskBtn = document.getElementById('backgroundTaskBtn');
    if (backgroundTaskBtn) {
        backgroundTaskBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const runningSessionId = typeof getRunningSessionId === 'function' ? getRunningSessionId() : null;
            if (runningSessionId && typeof loadSession === 'function') {
                loadSession(runningSessionId);
            } else if (typeof showToast === 'function') {
                showToast('没有正在运行的任务', 'info');
            }
        });
    }

    // 模型下拉菜单
    initModelDropdown();

    // 模态框关闭
    bindModalCloseEvents();

    // 键盘快捷键
    document.addEventListener('keydown', handleKeyboardShortcuts);

    console.log('[App] Global events bound');
}

// ============================================================
// 模型下拉菜单初始化
// ============================================================

function initModelDropdown() {
    const dropdown = document.getElementById('modelDropdown');
    const trigger = document.getElementById('modelDropdownTrigger');

    if (trigger && dropdown) {
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('open');
        });

        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target)) {
                dropdown.classList.remove('open');
            }
        });
    }
}

// ============================================================
// 模态框事件绑定
// ============================================================

function bindModalCloseEvents() {
    // 管理模型模态框
    const manageModelsModal = document.getElementById('manageModelsModal');
    if (manageModelsModal) {
        const closeBtn = manageModelsModal.querySelector('.close-modal');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                if (typeof closeManageModelsModal === 'function') {
                    closeManageModelsModal();
                } else {
                    manageModelsModal.style.display = 'none';
                }
            });
        }

        manageModelsModal.addEventListener('click', (e) => {
            if (e.target === manageModelsModal) {
                if (typeof closeManageModelsModal === 'function') {
                    closeManageModelsModal();
                } else {
                    manageModelsModal.style.display = 'none';
                }
            }
        });
    }

    // Provider Keys 模态框
    const providerKeysModal = document.getElementById('providerKeysModal');
    if (providerKeysModal) {
        providerKeysModal.addEventListener('click', (e) => {
            if (e.target === providerKeysModal) {
                if (typeof closeProviderKeysModal === 'function') {
                    closeProviderKeysModal();
                } else {
                    providerKeysModal.style.display = 'none';
                }
            }
        });
    }
}

// ============================================================
// 键盘快捷键处理
// ============================================================

function handleKeyboardShortcuts(e) {
    // Escape 关闭模态框
    if (e.key === 'Escape') {
        const modals = document.querySelectorAll('.modal');
        modals.forEach(modal => {
            if (modal.style.display !== 'none') {
                modal.style.display = 'none';
            }
        });

        const historyDrawer = document.getElementById('historyDrawer');
        if (historyDrawer && historyDrawer.classList.contains('open')) {
            historyDrawer.classList.remove('open');
        }
    }

    // Ctrl+Enter 发送消息
    if (e.ctrlKey && e.key === 'Enter') {
        const promptInput = document.getElementById('prompt');
        if (promptInput && document.activeElement === promptInput) {
            if (typeof sendMessage === 'function') {
                sendMessage();
            }
        }
    }
}

// ============================================================
// 初始数据加载
// ============================================================

async function loadInitialData() {
    console.log('[App] Loading initial data...');

    try {
        // loadOptions 已包含模型和工具加载
        if (typeof loadOptions === 'function') {
            await loadOptions();
        }

        console.log('[App] Initial data loaded');
    } catch (error) {
        console.error('[App] Failed to load initial data:', error);
    }
}

async function loadToolsData() {
    try {
        const res = await fetch('/api/options');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();
        const tools = data.tools || [];

        const toolListContainer = document.getElementById('toolListContainer');
        if (toolListContainer && tools.length > 0) {
            toolListContainer.innerHTML = tools.map(tool => `
                <label class="tool-checkbox">
                    <input type="checkbox" name="tool" value="${escapeHtml(tool.name)}" ${tool.default !== false ? 'checked' : ''}>
                    <span class="tool-name">${escapeHtml(tool.name)}</span>
                </label>
            `).join('');
        } else if (toolListContainer) {
            toolListContainer.innerHTML = '<span class="text-muted">无可用工具</span>';
        }
    } catch (error) {
        console.error('[App] Failed to load tools:', error);
    }
}

// ============================================================
// 工具面板折叠
// ============================================================

function toggleToolsPanel() {
    const inputArea = document.querySelector('.input-area');
    if (inputArea) {
        inputArea.classList.toggle('collapsed');
    }
}

// 导出到 window
window.toggleToolsPanel = toggleToolsPanel;

console.log('[App] Entry point loaded');
