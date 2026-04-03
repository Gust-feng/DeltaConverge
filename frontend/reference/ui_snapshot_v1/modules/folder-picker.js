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
        if (!listContainer) return;
        if (!listContainer.hasChildNodes()) {
            listContainer.innerHTML = '<div class="empty-state">加载中...</div>';
        }
        listContainer.classList.add('loading');
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
        } finally {
            listContainer.classList.remove('loading');
            // 预检查当前目录是否为 Git 仓库
            if (currentPath && typeof prefetchGitCheck === 'function') {
                prefetchGitCheck(currentPath);
            }
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

    selectBtn.onclick = async () => {
        if (currentPath) {
            // 添加加载状态
            const originalText = selectBtn.textContent;
            selectBtn.disabled = true;
            selectBtn.textContent = '检查中...';

            // 辅助函数：完成选择
            const completeSelection = (selectedPath, message, messageType) => {
                updateProjectPath(selectedPath);
                const dashboardPage = document.getElementById('page-dashboard');
                if (dashboardPage && dashboardPage.style.display !== 'none' && typeof loadDashboardData === 'function') {
                    loadDashboardData();
                }
                const diffPage = document.getElementById('page-diff');
                if (diffPage && diffPage.style.display !== 'none' && typeof refreshDiffAnalysis === 'function') {
                    refreshDiffAnalysis();
                }
                showToast(message || '已选择: ' + selectedPath, messageType || 'success');
                closeFolderPicker();
            };

            try {
                // 检查是否为 Git 仓库（利用缓存快速返回）
                if (typeof checkGitRepository === 'function') {
                    const result = await checkGitRepository(currentPath);

                    // 恢复按钮状态
                    selectBtn.disabled = false;
                    selectBtn.textContent = originalText;

                    if (!result.isGit) {
                        // 不是 Git 仓库
                        if (typeof showNotGitRepoWarning === 'function') {
                            showNotGitRepoWarning(currentPath,
                                () => completeSelection(currentPath, '已选择: ' + currentPath + ' (非 Git 仓库)', 'warning'),
                                () => { /* 保持文件夹选择器打开 */ }
                            );
                            return;
                        }
                    } else if (!result.isRoot && result.gitRoot) {
                        // 是 Git 仓库但不是根目录
                        if (typeof showGitSubdirWarning === 'function') {
                            showGitSubdirWarning(currentPath, result.gitRoot,
                                // onUseRoot - 使用根目录
                                () => completeSelection(result.gitRoot, '已选择项目根目录: ' + result.gitRoot, 'success'),
                                // onContinue - 继续使用子目录
                                () => completeSelection(currentPath, '已选择子目录: ' + currentPath, 'warning'),
                                // onCancel - 取消
                                () => { /* 保持文件夹选择器打开 */ }
                            );
                            return;
                        }
                    }
                }

                // 是 Git 根目录或检查函数不可用，正常处理
                completeSelection(currentPath);
            } finally {
                // 确保按钮状态恢复（如果对话框还没打开的情况）
                if (selectBtn.disabled) {
                    selectBtn.disabled = false;
                    selectBtn.textContent = originalText;
                }
            }
        }
    };




    nativeBtn.onclick = async () => {
        // 添加加载状态
        const originalHTML = nativeBtn.innerHTML;
        nativeBtn.disabled = true;
        nativeBtn.innerHTML = '选择中...';

        // 辅助函数：完成选择
        const completeSelection = (selectedPath, message, messageType) => {
            updateProjectPath(selectedPath);
            const dashboardPage = document.getElementById('page-dashboard');
            if (dashboardPage && dashboardPage.style.display !== 'none' && typeof loadDashboardData === 'function') {
                loadDashboardData();
            }
            const diffPage = document.getElementById('page-diff');
            if (diffPage && diffPage.style.display !== 'none' && typeof refreshDiffAnalysis === 'function') {
                refreshDiffAnalysis();
            }
            showToast(message || '已选择: ' + selectedPath, messageType || 'success');
            closeFolderPicker();
        };

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

                // 更新状态为检查中
                nativeBtn.innerHTML = '检查中...';

                // 检查是否为 Git 仓库
                if (typeof checkGitRepository === 'function') {
                    const result = await checkGitRepository(data.path);

                    // 恢复按钮状态
                    nativeBtn.disabled = false;
                    nativeBtn.innerHTML = originalHTML;

                    if (!result.isGit) {
                        // 不是 Git 仓库
                        if (typeof showNotGitRepoWarning === 'function') {
                            showNotGitRepoWarning(data.path,
                                () => completeSelection(data.path, '已选择: ' + data.path + ' (非 Git 仓库)', 'warning'),
                                () => { /* 保持文件夹选择器打开 */ }
                            );
                            return;
                        }
                    } else if (!result.isRoot && result.gitRoot) {
                        // 是 Git 仓库但不是根目录
                        if (typeof showGitSubdirWarning === 'function') {
                            showGitSubdirWarning(data.path, result.gitRoot,
                                // onUseRoot - 使用根目录
                                () => completeSelection(result.gitRoot, '已选择项目根目录: ' + result.gitRoot, 'success'),
                                // onContinue - 继续使用子目录
                                () => completeSelection(data.path, '已选择子目录: ' + data.path, 'warning'),
                                // onCancel - 取消
                                () => { /* 保持文件夹选择器打开 */ }
                            );
                            return;
                        }
                    }
                }

                // 是 Git 根目录或检查函数不可用，正常处理
                completeSelection(data.path);
            }
        } catch (e) {
            console.error("Native picker error:", e);
            showToast('系统选择器失败: ' + e.message, 'error');
        } finally {
            // 确保按钮状态恢复
            if (nativeBtn.disabled) {
                nativeBtn.disabled = false;
                nativeBtn.innerHTML = originalHTML;
            }
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
