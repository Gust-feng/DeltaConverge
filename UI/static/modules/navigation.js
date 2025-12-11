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
        'debug': '调试 - DeltaConverge',
        'rule-growth': '规则优化 - DeltaConverge'
    };
    document.title = titles[pageId] || 'Code Review Agent';

    // Trigger Loaders
    if (pageId === 'dashboard' && typeof loadDashboardData === 'function') loadDashboardData();
    if (pageId === 'diff' && typeof refreshDiffAnalysis === 'function') refreshDiffAnalysis();
    if (pageId === 'config' && typeof loadConfig === 'function') loadConfig();
    if (pageId === 'debug' && typeof loadDebugInfo === 'function') loadDebugInfo();
    if (pageId === 'rule-growth' && typeof loadRuleGrowthData === 'function') loadRuleGrowthData();
}

// Export to window
window.switchPage = switchPage;
