/**
 * utils.js - 工具函数模块
 * 
 * 提供全局使用的工具函数
 */

// --- Icons Helper ---
function getIcon(name) {
    return `<svg class="icon icon-${name}"><use href="#icon-${name}"></use></svg>`;
}

// --- HTML Escape ---
function escapeHtml(text) {
    if (text == null) return '';
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// --- Text Utilities ---
function truncateTextGlobal(text, maxLen = 100) {
    if (!text) return '';
    const str = String(text);
    return str.length > maxLen ? str.slice(0, maxLen) + '...' : str;
}

function formatFileSizeGlobal(bytes) {
    if (bytes == null) return '?';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function formatTimestamp(timestamp) {
    if (!timestamp) return '-';
    try {
        const d = new Date(timestamp);
        const now = new Date();
        const diffMs = now - d;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        
        if (diffDays === 0) {
            return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        } else if (diffDays === 1) {
            return '昨天 ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        } else if (diffDays < 7) {
            return `${diffDays}天前`;
        } else {
            return d.toLocaleDateString('zh-CN');
        }
    } catch (e) {
        return String(timestamp);
    }
}

function formatLanguageLabel(lang) {
    if (!lang) return '';
    const lower = lang.toLowerCase();
    const map = {
        py: 'Python', python: 'Python',
        js: 'JavaScript', javascript: 'JavaScript',
        ts: 'TypeScript', typescript: 'TypeScript',
        jsx: 'React JSX', tsx: 'React TSX',
        java: 'Java', go: 'Go', rust: 'Rust',
        cpp: 'C++', c: 'C', cs: 'C#',
        rb: 'Ruby', php: 'PHP', swift: 'Swift',
        kt: 'Kotlin', scala: 'Scala',
        html: 'HTML', css: 'CSS', scss: 'SCSS',
        vue: 'Vue', svelte: 'Svelte',
        sql: 'SQL', sh: 'Shell', bash: 'Bash',
        yaml: 'YAML', yml: 'YAML',
        json: 'JSON', md: 'Markdown', markdown: 'Markdown'
    };
    return map[lower] || lang;
}

// --- Toast Notifications ---
function showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:10000;display:flex;flex-direction:column;gap:8px;';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.style.cssText = 'padding:12px 16px;border-radius:8px;background:var(--bg-secondary);border:1px solid var(--border-color);color:var(--text-primary);box-shadow:0 4px 12px rgba(0,0,0,0.15);animation:slideIn 0.3s ease;';
    
    const icons = { success: 'check', error: 'x', warning: 'alert-triangle', info: 'info' };
    toast.innerHTML = `${getIcon(icons[type] || 'info')} <span>${escapeHtml(message)}</span>`;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// --- Button Loading State ---
function setButtonLoading(btn, isLoading, loadingText = null) {
    if (!btn) return;
    
    if (isLoading) {
        btn.dataset.originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = loadingText || '<div class="spinner-small"></div>';
    } else {
        btn.disabled = false;
        if (btn.dataset.originalText) {
            btn.innerHTML = btn.dataset.originalText;
            delete btn.dataset.originalText;
        }
    }
}

// Export to window
window.getIcon = getIcon;
window.escapeHtml = escapeHtml;
window.truncateTextGlobal = truncateTextGlobal;
window.formatFileSizeGlobal = formatFileSizeGlobal;
window.formatTimestamp = formatTimestamp;
window.formatLanguageLabel = formatLanguageLabel;
window.showToast = showToast;
window.setButtonLoading = setButtonLoading;
