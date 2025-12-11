/**
 * diff.js - Diff 分析页面模块
 */

async function refreshDiffAnalysis() {
    const diffFileList = document.getElementById('diff-file-list');
    if (!diffFileList) return;
    
    if (!window.currentProjectRoot) {
        diffFileList.innerHTML = '<div class="empty-state">请先在仪表盘或审查页面选择项目</div>';
        return;
    }
    
    diffFileList.innerHTML = '<div style="padding:1rem;color:var(--text-muted);">Loading diff...</div>';
    
    try {
        let reqMode = 'working';
        try {
            const sres = await fetch('/api/diff/status?project_root=' + encodeURIComponent(window.currentProjectRoot));
            if (sres && sres.ok) {
                const st = await sres.json();
                if (st && st.has_staged_changes) reqMode = 'staged';
                else if (st && st.has_working_changes) reqMode = 'working';
            }
        } catch (_) {}
        
        const res = await fetch('/api/diff/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_root: window.currentProjectRoot, mode: reqMode })
        });
        
        if (!res.ok) throw new Error('HTTP ' + res.status);
        
        const data = await res.json();
        let errorMsg = null;
        
        if (data && data.status && data.status.error) {
            errorMsg = data.status.error;
        } else if (data && data.summary && data.summary.error) {
            errorMsg = data.summary.error;
        }
        
        if (errorMsg) {
            if (errorMsg.indexOf('not a git repository') >= 0) {
                diffFileList.innerHTML = '<div class="empty-state">此目录不是 Git 仓库</div>';
            } else if (errorMsg.indexOf('No changes detected') >= 0) {
                diffFileList.innerHTML = '<div class="empty-state">无文件变更（工作区干净）</div>';
            } else {
                diffFileList.innerHTML = '<div class="empty-state">' + escapeHtml(errorMsg) + '</div>';
            }
            return;
        }
        
        window.currentDiffMode = reqMode;
        const files = (data && data.files) ? data.files : [];
        renderDiffFileList(files);
        
    } catch (e) {
        console.error('Refresh diff error:', e);
        diffFileList.innerHTML = '<div style="padding:1rem;color:red;">Error: ' + escapeHtml(e.message) + '</div>';
    }
}

function renderDiffFileList(files) {
    const diffFileList = document.getElementById('diff-file-list');
    if (!diffFileList) return;
    
    if (!files || files.length === 0) {
        diffFileList.innerHTML = '<div class="empty-state">无文件变更</div>';
        return;
    }

    diffFileList.innerHTML = '';
    files.forEach(file => {
        const div = document.createElement('div');
        div.className = 'file-list-item';
        
        const filePath = typeof file === 'string' ? file : (file.path || "Unknown File");
        const changeType = typeof file === 'object' ? file.change_type : "modify";
        
        let icon = getIcon('file');
        let statusClass = 'status-modify';
        if (changeType === 'add') { icon = getIcon('plus'); statusClass = 'status-add'; }
        else if (changeType === 'delete') { icon = getIcon('trash'); statusClass = 'status-delete'; }
        else if (changeType === 'rename') { icon = getIcon('edit'); statusClass = 'status-rename'; }
        
        const fileName = filePath.split('/').pop();
        const dirPath = filePath.substring(0, filePath.lastIndexOf('/'));
        
        div.innerHTML = `
            <div class="file-item-row">
                <span class="file-icon ${statusClass}">${icon}</span>
                <div class="file-info">
                    <div class="file-name" title="${escapeHtml(filePath)}">${escapeHtml(fileName)}</div>
                    <div class="file-path" title="${escapeHtml(dirPath)}">${escapeHtml(dirPath)}</div>
                </div>
            </div>
        `;
        
        div.dataset.path = filePath;
        div.onclick = () => loadFileDiff(filePath);
        diffFileList.appendChild(div);
    });
}

async function loadFileDiff(filePath) {
    const diffContentArea = document.getElementById('diff-content-area');
    const diffFileList = document.getElementById('diff-file-list');
    if (!diffContentArea) return;
    
    if (!window.currentProjectRoot) {
        diffContentArea.innerHTML = '<div style="padding:1rem;color:red;">请先选择项目文件夹</div>';
        return;
    }
    
    diffContentArea.innerHTML = '<div class="empty-state">Loading...</div>';
    
    if (diffFileList) {
        const items = diffFileList.querySelectorAll('.file-list-item');
        items.forEach(i => {
            if (i.dataset.path === filePath) i.classList.add('active');
            else i.classList.remove('active');
        });
    }

    try {
        const res = await fetch(`/api/diff/file/${encodeURIComponent(filePath)}?project_root=${encodeURIComponent(window.currentProjectRoot)}&mode=${window.currentDiffMode}`);
        
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        
        const data = await res.json();
        
        if (data.error) {
            diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">${escapeHtml(data.error)}</div>`;
            return;
        }

        const diffText = data.diff_text || data.diff_content || "";
        
        if (window.Diff2HtmlUI && diffText.trim()) {
            const currentViewMode = window.currentDiffViewMode || 'side-by-side';
            
            diffContentArea.innerHTML = `
                <div class="diff-header">
                    <h3 title="${escapeHtml(filePath)}">${escapeHtml(filePath)}</h3>
                    <div class="diff-controls">
                        <label class="${currentViewMode === 'line-by-line' ? 'active' : ''}">
                            <input type="radio" name="diff-view" value="line-by-line" ${currentViewMode === 'line-by-line' ? 'checked' : ''} onclick="toggleDiffView('line-by-line')">
                            <span class="view-option">Unified</span>
                        </label>
                        <label class="${currentViewMode === 'side-by-side' ? 'active' : ''}">
                            <input type="radio" name="diff-view" value="side-by-side" ${currentViewMode === 'side-by-side' ? 'checked' : ''} onclick="toggleDiffView('side-by-side')">
                            <span class="view-option">Split</span>
                        </label>
                    </div>
                </div>
                <div id="diff-ui-container" style="padding: 0;"></div>
            `;
            
            window.currentDiffText = diffText;
            renderDiff2Html(diffText, currentViewMode);
            
        } else {
            const formattedDiff = diffText ? diffText.replace(/\r\n/g, '\n') : "No content";
            diffContentArea.innerHTML = `
                <div style="padding:1rem;">
                    <h3>${escapeHtml(filePath)}</h3>
                    <pre style="background:var(--bg-secondary);padding:1rem;overflow:auto;"><code>${escapeHtml(formattedDiff)}</code></pre>
                </div>
            `;
        }

    } catch (e) {
        console.error("Load file diff error:", e);
        diffContentArea.innerHTML = `<div style="padding:1rem;color:red;">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function renderDiff2Html(diffText, outputFormat) {
    const targetElement = document.getElementById('diff-ui-container');
    if (!targetElement || !window.Diff2HtmlUI) return;
    
    const configuration = {
        drawFileList: false,
        fileListToggle: false,
        fileContentToggle: false,
        matching: 'lines',
        outputFormat: outputFormat,
        synchronisedScroll: true,
        highlight: true,
        renderNothingWhenEmpty: false,
    };
    
    const diff2htmlUi = new Diff2HtmlUI(targetElement, diffText, configuration);
    diff2htmlUi.draw();
    diff2htmlUi.highlightCode();
}

function toggleDiffView(mode) {
    window.currentDiffViewMode = mode;
    
    const controls = document.querySelector('.diff-controls');
    if (controls) {
        controls.querySelectorAll('label').forEach(label => {
            const input = label.querySelector('input');
            if (input && input.value === mode) {
                label.classList.add('active');
            } else {
                label.classList.remove('active');
            }
        });
    }
    
    if (window.currentDiffText) {
        renderDiff2Html(window.currentDiffText, mode);
    }
}

// Export to window
window.refreshDiffAnalysis = refreshDiffAnalysis;
window.renderDiffFileList = renderDiffFileList;
window.loadFileDiff = loadFileDiff;
window.renderDiff2Html = renderDiff2Html;
window.toggleDiffView = toggleDiffView;
