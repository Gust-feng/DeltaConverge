/**
 * folder-picker.js - 文件夹选择器模块
 */

async function pickFolder() {
    try {
        await openWebFolderPicker();
    } catch (e) {
        console.error("Pick folder error:", e);
        showToast("选择文件夹失败: " + e.message, "error");
    }
}

// Alias for compatibility
function openFolderPicker() {
    pickFolder();
}

async function openWebFolderPicker() {
    const existing = document.getElementById('folderPickerDialog');
    if (existing) existing.remove();

    const dialog = document.createElement('div');
    dialog.id = 'folderPickerDialog';
    dialog.className = 'modal-overlay';
    dialog.innerHTML = `
        <div class="modal-container folder-picker-container">
            <div class="modal-header">
                <h3>选择项目文件夹</h3>
                <button class="close-btn" onclick="closeFolderPicker()">${getIcon('x')}</button>
            </div>
            <div class="modal-body">
                <div class="picker-toolbar">
                    <input type="text" id="folderPathInput" class="picker-path-input bare-input" placeholder="输入路径或浏览...">
                    <div class="picker-actions">
                        <button class="btn-secondary" id="folderGoBtn">前往</button>
                        <button class="btn-secondary" id="folderUpBtn">${getIcon('arrow-up')} 上级</button>
                        <button class="btn-secondary" id="nativePickerBtn">${getIcon('folder')} 系统选择器</button>
                    </div>
                </div>
                <div class="file-list" id="folderListContainer">
                    <div class="empty-state">加载中...</div>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn-secondary" onclick="closeFolderPicker()">取消</button>
                <button class="btn-primary" id="selectFolderBtn">选择当前文件夹</button>
            </div>
        </div>
    `;
    document.body.appendChild(dialog);

    const pathInput = document.getElementById('folderPathInput');
    const listContainer = document.getElementById('folderListContainer');
    const goBtn = document.getElementById('folderGoBtn');
    const upBtn = document.getElementById('folderUpBtn');
    const selectBtn = document.getElementById('selectFolderBtn');
    const nativeBtn = document.getElementById('nativePickerBtn');

    let currentPath = window.currentProjectRoot || '';

    // 获取初始路径
    try {
        const resEnv = await fetch('/api/system/env');
        const env = resEnv.ok ? await resEnv.json() : {};
        if (env) {
            window.platform = env.platform || window.platform;
            window.isDockerEnv = !!env.is_docker;
        }
        currentPath = window.currentProjectRoot || env.default_project_root || '';
    } catch (_) { }
    if (pathInput) pathInput.value = currentPath || '';

    async function loadDirectory(path) {
        listContainer.innerHTML = '<div class="empty-state">加载中...</div>';
        try {
            const res = await fetch('/api/system/list-directory', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: path })
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            if (data.error) {
                listContainer.innerHTML = `<div class="empty-state">${escapeHtml(data.error)}</div>`;
                return;
            }

            currentPath = data.path || path;
            if (pathInput) pathInput.value = currentPath || '';

            if (!data.children || data.children.length === 0) {
                listContainer.innerHTML = '<div class="empty-state">空目录</div>';
                return;
            }

            listContainer.innerHTML = data.children.map(c => `
                <div class="file-list-item" data-name="${escapeHtml(c.name)}">
                    ${getIcon('folder')}
                    <span>${escapeHtml(c.name)}</span>
                </div>
            `).join('');

            listContainer.querySelectorAll('.file-list-item').forEach(item => {
                item.onclick = () => {
                    const name = item.getAttribute('data-name');
                    const sep = (currentPath.includes('\\') && !currentPath.includes('/')) ? '\\' : '/';
                    const np = (currentPath ? currentPath.replace(/[\\/]+$/, '') + sep : '') + name;
                    loadDirectory(np);
                };
            });

        } catch (e) {
            console.error("Load directory error:", e);
            listContainer.innerHTML = `<div class="error-state">${escapeHtml(e.message)}</div>`;
        }
    }

    goBtn.onclick = () => loadDirectory(pathInput.value);
    pathInput.onkeydown = (e) => { if (e.key === 'Enter') loadDirectory(pathInput.value); };

    upBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const cur = pathInput ? pathInput.value : currentPath;
        let s = cur || '';
        if (!s) return;
        s = s.replace(/[\\/]+$/, '');
        const win = s.includes('\\') && !s.includes('/');
        const sep = win ? '\\' : '/';
        const idx = s.lastIndexOf(sep);
        if (idx <= 0) {
            loadDirectory(s);
        } else {
            let parent = s.slice(0, idx);
            if (win && parent.length <= 2) parent = parent + '\\';
            loadDirectory(parent);
        }
    };

    selectBtn.onclick = () => {
        if (currentPath) {
            updateProjectPath(currentPath);
            // 根据当前页面刷新数据
            const dashboardPage = document.getElementById('page-dashboard');
            if (dashboardPage && dashboardPage.style.display !== 'none' && typeof loadDashboardData === 'function') {
                loadDashboardData();
            }
            const diffPage = document.getElementById('page-diff');
            if (diffPage && diffPage.style.display !== 'none' && typeof refreshDiffAnalysis === 'function') {
                refreshDiffAnalysis();
            }
            showToast('已选择: ' + currentPath, 'success');
            closeFolderPicker();
        }
    };

    nativeBtn.onclick = async () => {
        try {
            const res = await fetch('/api/system/pick-folder', { method: 'POST' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            if (data.error) {
                showToast('系统选择器失败: ' + data.error, 'error');
                return;
            }
            if (data.path) {
                if (pathInput) pathInput.value = data.path;
                updateProjectPath(data.path);
                const dashboardPage = document.getElementById('page-dashboard');
                if (dashboardPage && dashboardPage.style.display !== 'none' && typeof loadDashboardData === 'function') {
                    loadDashboardData();
                }
                const diffPage = document.getElementById('page-diff');
                if (diffPage && diffPage.style.display !== 'none' && typeof refreshDiffAnalysis === 'function') {
                    refreshDiffAnalysis();
                }
                showToast('已选择: ' + data.path, 'success');
                closeFolderPicker();
            }
        } catch (e) {
            console.error("Native picker error:", e);
            showToast('系统选择器失败: ' + e.message, 'error');
        }
    };

    // Close on backdrop click
    dialog.onclick = (e) => {
        if (e.target === dialog) closeFolderPicker();
    };

    // Load initial directory
    loadDirectory(currentPath);
}

function closeFolderPicker() {
    const dialog = document.getElementById('folderPickerDialog');
    if (dialog) dialog.remove();
}

// Export to window
window.pickFolder = pickFolder;
window.openFolderPicker = openFolderPicker;
window.openWebFolderPicker = openWebFolderPicker;
window.closeFolderPicker = closeFolderPicker;
