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

        // 使用日期比较而非毫秒差，确保跨午夜时正确判断
        const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterdayStart = new Date(todayStart.getTime() - 24 * 60 * 60 * 1000);
        const targetDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());

        const timeStr = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

        if (targetDate.getTime() === todayStart.getTime()) {
            return '今天 ' + timeStr;
        } else if (targetDate.getTime() === yesterdayStart.getTime()) {
            return '昨天 ' + timeStr;
        } else {
            const diffDays = Math.floor((todayStart - targetDate) / (1000 * 60 * 60 * 24));
            if (diffDays < 7) {
                return `${diffDays}天前 ${timeStr}`;
            } else {
                // 显示月/日 时:分
                const month = d.getMonth() + 1;
                const day = d.getDate();
                return `${month}月${day}日 ${timeStr}`;
            }
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
    // 1) 优先复用 main.js 的系统消息插入逻辑
    if (typeof window.addSystemMessage === 'function') {
        window.addSystemMessage(escapeHtml(message));
        return;
    }

    // 2) 次优先：直接向 messageContainer 追加一条 system-message
    const messageArea = document.getElementById('messageContainer');
    if (messageArea) {
        const div = document.createElement('div');
        div.className = 'message system-message';
        const iconName = type === 'error'
            ? 'x'
            : type === 'success'
                ? 'check'
                : type === 'warning'
                    ? 'alert-triangle'
                    : 'bot';
        div.innerHTML = `
            <div class="avatar">${getIcon(iconName)}</div>
            <div class="message-body">
                <div class="content"><p>${escapeHtml(message)}</p></div>
            </div>
        `;
        messageArea.appendChild(div);
        messageArea.scrollTop = messageArea.scrollHeight;
        return;
    }

    // 3) Fallback：浮动 toast（与 main.js 保持一致）
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconName = 'bot';
    if (type === 'error') iconName = 'x';
    if (type === 'success') iconName = 'check';
    if (type === 'warning') iconName = 'alert-triangle';

    toast.innerHTML = `
        <div class="toast-icon">${getIcon(iconName)}</div>
        <div class="toast-content">${escapeHtml(message)}</div>
        <div class="toast-close">${getIcon('x')}</div>
    `;

    const closeBtn = toast.querySelector('.toast-close');
    if (closeBtn) {
        closeBtn.onclick = () => {
            toast.classList.add('hiding');
            toast.addEventListener('animationend', () => toast.remove());
        };
    }

    container.appendChild(toast);

    // 自动移除
    setTimeout(() => {
        if (toast.isConnected) {
            toast.classList.add('hiding');
            toast.addEventListener('animationend', () => toast.remove());
        }
    }, 5000);
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
