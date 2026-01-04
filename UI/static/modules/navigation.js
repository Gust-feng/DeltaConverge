/**
 * navigation.js - 页面导航模块
 */

function switchPage(pageId) {
    // Update Nav State
    const btns = document.querySelectorAll('.nav-btn');
    btns.forEach(btn => {
        if (btn.id === `nav-${pageId}`) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Update View State
    const views = document.querySelectorAll('.page-view, .workbench');
    views.forEach(view => {
        if (view.id === `page-${pageId}`) {
            view.style.display = (pageId === 'review') ? 'flex' : 'block';
        } else {
            view.style.display = 'none';
        }
    });

    // Update Document Title
    const titles = {
        'dashboard': '仪表盘 - DeltaConverge',
        'review': '代码审查 - DeltaConverge',
        'diff': '代码变更 - DeltaConverge',
        'config': '设置 - DeltaConverge',
        'github-pr': 'GitHub PR - DeltaConverge',
        'rule-growth': '规则优化 - DeltaConverge'
    };
    document.title = titles[pageId] || 'Code Review Agent';

    // Review 页面：处理首次动画标记
    if (pageId === 'review') {
        // 确保diff状态徽章更新
        if (typeof refreshDiffAnalysis === 'function') {
            // 使用 setTimeout 避免阻塞 UI 切换
            setTimeout(() => refreshDiffAnalysis(), 50);
        }

        const workbench = document.getElementById('page-review');
        if (workbench) {
            // 如果是首次加载，延迟后标记已播放动画
            if (!workbench.classList.contains('text-animated')) {
                // 等待文字动画完成后添加标记（动画约 2 秒）
                setTimeout(() => {
                    workbench.classList.add('text-animated');
                }, 2500);
            }
        }
    }

    // Trigger Loaders
    if (pageId === 'dashboard' && typeof loadDashboardData === 'function') loadDashboardData();
    if (pageId === 'diff') {
        // 初始化diff模式选择器
        if (typeof initDiffModeDropdown === 'function') initDiffModeDropdown();
        if (typeof refreshDiffAnalysis === 'function') refreshDiffAnalysis();
    }
    if (pageId === 'config' && typeof loadConfig === 'function') loadConfig();

    if (pageId === 'rule-growth') {
        if (typeof initRuleGrowthPage === 'function') initRuleGrowthPage();
        if (typeof loadRuleGrowthData === 'function') loadRuleGrowthData();
    }
}

// Export to window
window.switchPage = switchPage;
