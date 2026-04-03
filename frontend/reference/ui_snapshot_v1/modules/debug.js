/**
 * debug.js - 调试页面模块
 */

async function loadDebugInfo() {
    const cacheStatsDiv = document.getElementById('cache-stats');
    const intentCacheListDiv = document.getElementById('intent-cache-list');
    
    try {
        const resStats = await fetch('/api/cache/stats');
        if (resStats.ok && cacheStatsDiv) {
            const stats = await resStats.json();
            const intentSize = stats.intent_cache_size || 0;
            const diffSize = stats.diff_cache_size || 0;
            cacheStatsDiv.innerHTML = `
                <div class="stat-row"><span class="label">Intent Cache Size:</span><span class="value">${intentSize} items</span></div>
                <div class="stat-row"><span class="label">Diff Cache Size:</span><span class="value">${diffSize} items</span></div>
            `;
        }
        
        const resIntents = await fetch('/api/cache/intent');
        if (resIntents.ok && intentCacheListDiv) {
            const intents = await resIntents.json();
            
            if (!intents || intents.length === 0) {
                intentCacheListDiv.innerHTML = '<div class="empty-state">No intent caches</div>';
            } else {
                intentCacheListDiv.innerHTML = intents.map(i => {
                    const project = escapeHtml(i.project_name || 'Unknown');
                    const timestamp = i.created_at ? new Date(i.created_at).toLocaleString() : '';
                    return `
                        <div class="file-list-item" style="cursor:default;">
                            <strong>${project}</strong>
                            <br>
                            <small class="text-muted">${timestamp}</small>
                        </div>
                    `;
                }).join('');
            }
        }
    } catch (e) {
        console.error("Load debug info error:", e);
    }
}

async function clearCache() {
    if(confirm('确定要清除所有意图缓存吗？')) {
        try {
            const res = await fetch('/api/cache/intent', { method: 'DELETE' });
            if (res.ok) {
                showToast('缓存已清除', 'success');
                loadDebugInfo();
            } else {
                showToast('清除缓存失败', 'error');
            }
        } catch (e) {
            console.error("Clear cache error:", e);
            showToast('清除缓存失败: ' + e.message, 'error');
        }
    }
}

// Export to window
window.loadDebugInfo = loadDebugInfo;
window.clearCache = clearCache;
