/* Data Generation - Matching test.md Results strictly for AGENT (System Under Test) */
/* 
Sentry: 10 PRs. Agent Hit: 1, 2, 8, 9, 10. Miss: 3, 4, 5, 6, 7. (50%)
Cal.com: 10 PRs. Agent Hit: 1, 2, 3, 4, 5, 6, 8, 9. Miss: 7, 10. (80%)
Grafana: 10 PRs. Agent Hit: 1, 2, 4, 5, 6, 7, 8, 9, 10. Miss: 3. (90%)
Keycloak: 10 PRs. Agent Hit: 1, 3, 4, 5, 6, 8, 9, 10. Miss: 2, 7. (80%)
Discourse: 10 PRs. Agent Hit: 1, 2, 3, 4, 5, 7, 9. Miss: 6, 8, 10. (70%)
*/

// Configuration for AGENT (Our System) - Strictly based on test.md
const agentResults = {
    'Sentry': { miss: [3, 4, 5, 6, 7], lang: 'Python' },
    'Cal.com': { miss: [7, 10], lang: 'TypeScript' },
    'Grafana': { miss: [3], lang: 'Go' },
    'Keycloak': { miss: [2, 7], lang: 'Java' },
    'Discourse': { miss: [6, 8, 10], lang: 'Ruby' }
};

// PR Link mapping for each project (DeltaConverge review results)
const prLinks = {
    'Sentry': {
        1: 'https://github.com/Gust-feng/sentry/pull/2',
        2: 'https://github.com/Gust-feng/sentry/pull/3',
        3: 'https://github.com/Gust-feng/sentry/pull/4',
        4: 'https://github.com/Gust-feng/sentry/pull/5',
        5: 'https://github.com/Gust-feng/sentry/pull/6',
        6: 'https://github.com/Gust-feng/sentry/pull/7',
        7: 'https://github.com/Gust-feng/sentry/pull/8',
        8: 'https://github.com/Gust-feng/sentry/pull/10',
        9: 'https://github.com/Gust-feng/sentry/pull/9',
        10: 'https://github.com/Gust-feng/sentry/pull/11'
    },
    'Cal.com': {
        1: 'https://github.com/Gust-feng/cal.com/pull/16',
        2: 'https://github.com/Gust-feng/cal.com/pull/17',
        3: 'https://github.com/Gust-feng/cal.com/pull/24',
        4: 'https://github.com/Gust-feng/cal.com/pull/25',
        5: 'https://github.com/Gust-feng/cal.com/pull/26',
        6: 'https://github.com/Gust-feng/cal.com/pull/19',
        7: 'https://github.com/Gust-feng/cal.com/pull/22',
        8: 'https://github.com/Gust-feng/cal.com/pull/23',
        9: 'https://github.com/Gust-feng/cal.com/pull/20',
        10: 'https://github.com/Gust-feng/cal.com/pull/21'
    },
    'Grafana': {
        1: 'https://github.com/Gust-feng/grafana/pull/1',
        2: 'https://github.com/Gust-feng/grafana/pull/2',
        3: 'https://github.com/Gust-feng/grafana/pull/3',
        4: 'https://github.com/Gust-feng/grafana/pull/4',
        5: 'https://github.com/Gust-feng/grafana/pull/5',
        6: 'https://github.com/Gust-feng/grafana/pull/6',
        7: 'https://github.com/Gust-feng/grafana/pull/7',
        8: 'https://github.com/Gust-feng/grafana/pull/8',
        9: 'https://github.com/Gust-feng/grafana/pull/9',
        10: 'https://github.com/Gust-feng/grafana/pull/10'
    },
    'Keycloak': {
        1: 'https://github.com/Gust-feng/keycloak/pull/1',
        2: 'https://github.com/Gust-feng/keycloak/pull/2',
        3: 'https://github.com/Gust-feng/keycloak/pull/3',
        4: 'https://github.com/Gust-feng/keycloak/pull/4',
        5: 'https://github.com/Gust-feng/keycloak/pull/5',
        6: 'https://github.com/Gust-feng/keycloak/pull/6',
        7: 'https://github.com/Gust-feng/keycloak/pull/7',
        8: 'https://github.com/Gust-feng/keycloak/pull/8',
        9: 'https://github.com/Gust-feng/keycloak/pull/9',
        10: 'https://github.com/Gust-feng/keycloak/pull/10'
    },
    'Discourse': {
        1: 'https://github.com/Gust-feng/discourse/pull/1',
        2: 'https://github.com/Gust-feng/discourse/pull/2',
        3: 'https://github.com/Gust-feng/discourse/pull/3',
        4: 'https://github.com/Gust-feng/discourse/pull/4',
        5: 'https://github.com/Gust-feng/discourse/pull/5',
        6: 'https://github.com/Gust-feng/discourse/pull/6',
        7: 'https://github.com/Gust-feng/discourse/pull/7',
        8: 'https://github.com/Gust-feng/discourse/pull/8',
        9: 'https://github.com/Gust-feng/discourse/pull/9',
        10: 'https://github.com/Gust-feng/discourse/pull/10'
    }
};

// =============================================================================
// REAL BENCHMARK DATA - Extracted from Greptile Benchmarks Images (5 Projects)
// =============================================================================

// --- SENTRY (Image 0) ---
const sentryData = [
    { id: 1, title: "Enhanced Pagination Performance for High-Volume Audit Logs", subtitle: "Importing non-existent OptimizedCursorPaginator", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 2, title: "Optimize spans buffer insertion with eviction during insert", subtitle: "Negative offset cursor manipulation bypasses pagination boundaries", sev: "CRITICAL", greptile: 0, copilot: 0, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 3, title: "Support upsampled error count with performance optimizations", subtitle: "sample_rate = 0.0 is falsy and skipped", sev: "LOW", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 4, title: "GitHub OAuth Security Enhancement", subtitle: "Null reference if github_authenticated_user state is missing", sev: "CRITICAL", greptile: 0, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 5, title: "Replays Self-Serve Bulk Delete System", subtitle: "Breaking changes in error response format", sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 6, title: "Span Buffer Multiprocess Enhancement with Health Monitoring", subtitle: "Inconsistent metric tagging with shard and shards", sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 7, title: "Implement cross-system issue synchronization", subtitle: "Shared mutable default in dataclass timestamp", sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 8, title: "Reorganize incident creation / issue occurrence logic", subtitle: "Using stale config variable instead of updated one", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 9, title: "Add ability to use queues to manage parallelism", subtitle: "Invalid queue.ShutDown exception handling", sev: "HIGH", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 10, title: "Add hook for producing occurrences from the stateful detector", subtitle: "Incomplete implementation (only contains pass)", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 }
];

// --- CAL.COM (Image 1) ---
const calData = [
    { id: 1, title: "Async import of the appStore packages", subtitle: "Async callbacks in forEach creates unhandled promise rejections", sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 2, title: "feat: 2fa backup codes", subtitle: "Backup codes not invalidated after use", sev: "CRITICAL", greptile: 0, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 3, title: "fix: handle collective multiple host on destinationCalendar", subtitle: "Null reference error if array is empty", sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 4, title: "feat: convert InsightsBookingService to use Prisma.sql raw queries", subtitle: "Potential SQL injection risk in raw SQL query construction", sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 5, title: "Comprehensive workflow reminder management for booking lifecycle events", subtitle: "Missing database cleanup when immediateDelete is true", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 6, title: "Advanced date override handling and timezone compatibility improvements", subtitle: "Incorrect end time calculation using slotStartTime instead of slotEndTime", sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 7, title: "OAuth credential sync and app integration enhancements", subtitle: "Timing attack vulnerability using direct string comparison", sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 8, title: "SMS workflow reminder retry count tracking", subtitle: "OR condition causes deletion of all workflow reminders", sev: "HIGH", greptile: 0, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 9, title: "Add guest management functionality to existing bookings", subtitle: "Case sensitivity bypass in email blacklist", sev: "HIGH", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 10, title: "feat: add calendar cache status and actions (#22532)", subtitle: "Inaccurate cache status tracking due to unreliable updatedAt field", sev: "LOW", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 }
];

// --- GRAFANA (Image 2) ---
const grafanaData = [
    { id: 1, title: "Anonymous: Add configurable device limit", subtitle: "Race condition in CreateOrUpdateDevice method", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 2, title: "AuthZService: improve authz caching", subtitle: "Cache entries without expiration causing permanent permission denials", sev: "HIGH", greptile: 0, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 3, title: "Plugins: Chore: Renamed instrumentation middleware to metrics middleware", subtitle: "Undefined endpoint constants causing compilation errors", sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 4, title: "Advanced Query Processing Architecture", subtitle: "Double interpolation risk", sev: "CRITICAL", greptile: 0, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 5, title: "Notification Rule Processing Engine", subtitle: "Missing key prop causing React rendering issues", sev: "MEDIUM", greptile: 1, copilot: 0, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 6, title: "Dual Storage Architecture", subtitle: "Incorrect metrics recording methods causing misleading performance tracking", sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 1 },
    { id: 7, title: "Database Performance Optimizations", subtitle: "Incorrect error level logging", sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 0, graphite: 1 },
    { id: 8, title: "Frontend Asset Optimization", subtitle: "Deadlock potential during concurrent annotation deletion operations", sev: "HIGH", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 9, title: "Advanced SQL Analytics Framework", subtitle: "enableSqlExpressions function always returns false, disabling SQL functionality", sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 1 },
    { id: 10, title: "Unified Storage Performance Optimizations", subtitle: "Race condition in cache locking", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 }
];

// --- KEYCLOAK (Image 3) ---
const keycloakData = [
    { id: 1, title: "Fixing Re-authentication with passkeys", subtitle: "ConditionalPasskeysEnabled() called without UserModel parameter", sev: "MEDIUM", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 2, title: "Add caching support for IdentityProviderStorageProvider.getForLogin operations", subtitle: "Recursive caching call using session instead of delegate", sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 3, title: "Add AuthzClientCryptoProvider for authorization client cryptographic operations", subtitle: "Returns wrong provider (default keystore instead of BouncyCastle)", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 4, title: "Add rolling-updates feature flag and compatibility framework", subtitle: "Incorrect method call for exit codes", sev: "MEDIUM", greptile: 0, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 5, title: "Add Client resource type and scopes to authorization schema", subtitle: "Inconsistent feature flag bug causing orphaned permissions", sev: "HIGH", greptile: 0, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 6, title: "Add Groups resource type and scopes to authorization schema", subtitle: "Incorrect permission check in canManage() method", sev: "HIGH", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 7, title: "Add HTML sanitizer for translated message resources", subtitle: "Lithuanian translation files contain Italian text", sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 8, title: "Implement access token context encoding framework", subtitle: "Wrong parameter in null check (grantType vs. rawTokenId)", sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 9, title: "Implement recovery key support for user storage providers", subtitle: "Unsafe raw List deserialization without type safety", sev: "MEDIUM", greptile: 1, copilot: 0, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 10, title: "Fix concurrent group access to prevent NullPointerException", subtitle: "Missing null check causing NullPointerException", sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 }
];

// --- DISCOURSE (Image 4) ---
const discourseData = [
    { id: 1, title: "FEATURE: automatically downsize large images", subtitle: "Method overwriting causing parameter mismatch", sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 2, title: "FEATURE: per-topic unsubscribe option in emails", subtitle: "Nil reference non-existent TopicUser", sev: "HIGH", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 3, title: "Add comprehensive email validation for blocked users", subtitle: "BlockedEmail.should_block? modifies DB during read", sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 4, title: "Enhance embed URL handling and validation system", subtitle: "SSRF vulnerability using open(url) without validation", sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 5, title: "Optimize header layout performance with flexbox mixins", subtitle: "Mixing float: left with flexbox causes layout issues", sev: "LOW", greptile: 0, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 6, title: "UX: show complete URL path if website domain is same as instance domain", subtitle: "String mutation with << operator", sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 7, title: "scale-color $lightness must use $secondary for dark themes", subtitle: "Inconsistent theme color lightness affects visibility", sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 8, title: "FIX: proper handling of group memberships", subtitle: "Race conditions in async member loading", sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 9, title: "FEATURE: Localization fallbacks (server-side)", subtitle: "Thread-safety issue with lazy @loaded_locales", sev: "HIGH", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 10, title: "FEATURE: Can edit category/host relationships for embedding", subtitle: "NoMethodError before_validation in EmbeddableHost", sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 }
];

// =============================================================================
// Build Full Dataset from Real Data
// =============================================================================
const fullDataset = {};

const tools = ['agent', 'greptile', 'cursor', 'copilot', 'rabbit', 'graphite'];
const toolLabels = ['DeltaConverge', 'Greptile', 'Cursor', 'Copilot', 'CodeRabbit', 'Graphite'];

const projectDataMap = {
    'Sentry': sentryData,
    'Cal.com': calData,
    'Grafana': grafanaData,
    'Keycloak': keycloakData,
    'Discourse': discourseData
};

Object.keys(agentResults).forEach(proj => {
    const config = agentResults[proj];
    const realData = projectDataMap[proj];

    fullDataset[proj] = realData.map(pr => {
        const isAgentMiss = config.miss.includes(pr.id);
        return {
            id: pr.id,
            title: pr.title,
            subtitle: pr.subtitle,
            sev: pr.sev,
            tools: {
                agent: !isAgentMiss,
                greptile: pr.greptile === 1,
                copilot: pr.copilot === 1,
                rabbit: pr.rabbit === 1,
                cursor: pr.cursor === 1,
                graphite: pr.graphite === 1
            }
        };
    });
});

/* Charts Configuration */
Chart.defaults.font.family = "'JetBrains Mono', monospace";
Chart.defaults.color = '#555';

const colors = {
    agent: 'rgb(100, 149, 237)',    // Cornflower Blue - Highlight
    greptile: '#64748B', // Slate - Strong Comp
    copilot: '#EBE0B9',
    rabbit: '#ECC4B4',
    cursor: '#F2D2D6',
    graphite: '#C8C8C8'
};

/* Render Logic */

document.addEventListener('DOMContentLoaded', () => {
    renderTabs();
    renderTable('Sentry');
    renderCharts();
    // Initialize Printer Effect Observer
    const printerObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                startPrinterEffect();
                printerObserver.disconnect(); // Run only once
            }
        });
    }, { threshold: 0.5 }); // Trigger when 50% of the element is visible

    const printerContainer = document.querySelector('.tabs-wrapper');
    if (printerContainer) {
        printerObserver.observe(printerContainer);
    }
});

function renderTabs() {
    const container = document.getElementById('projectTabs');
    Object.keys(agentResults).forEach((proj, idx) => {
        const btn = document.createElement('button');
        btn.className = `tab-btn ${idx === 0 ? 'active' : ''}`;
        btn.innerHTML = `${proj}`;
        btn.onclick = () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            renderTable(proj);
        };
        container.appendChild(btn);
    });
}

function renderTable(project) {
    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = '';

    fullDataset[project].forEach(row => {
        const tr = document.createElement('tr');

        // Get PR link for this row
        const prUrl = prLinks[project] && prLinks[project][row.id] ? prLinks[project][row.id] : null;

        // Tool Cells
        const toolCells = tools.map((t, idx) => {
            const status = row.tools[t];
            let iconClass = 'status-miss';
            let iconContent = '✗';

            if (status) {
                iconClass = 'status-hit';
                iconContent = '✓';
            } else if (t === 'agent') {
                iconClass = 'status-miss-agent';
                iconContent = '✗';
            }

            // Highlight Agent Column (Index 0)
            const cellClass = idx === 0 ? 'highlight-col' : '';

            // For agent column (idx 0), make entire cell clickable
            if (idx === 0 && prUrl) {
                return `<td class="${cellClass} clickable-cell"><a href="${prUrl}" target="_blank" rel="noopener noreferrer" class="pr-cell-link" title="查看 DeltaConverge 审查结果"><span class="status-icon ${iconClass}">${iconContent}</span></a></td>`;
            }

            return `<td class="${cellClass}"><span class="status-icon ${iconClass}">${iconContent}</span></td>`;
        }).join('');

        const badgeClass = `sev-${row.sev.toLowerCase()}`;

        tr.innerHTML = `
            <td>
                <span class="bug-title">${row.title}</span>
                <span class="bug-subtitle">${row.subtitle}</span>
            </td>
            <td><span class="sev-badge ${badgeClass}">${row.sev}</span></td>
            ${toolCells}
        `;
        tbody.appendChild(tr);
    });
}

function renderCharts() {
    Chart.register(ChartDataLabels);

    const commonOptions = {
        plugins: {
            legend: { display: false },
            datalabels: {
                anchor: 'end',
                align: 'top',
                formatter: (value) => value + '%',
                font: { weight: 'bold', size: 11 },
                color: '#555'
            }
        },
        maintainAspectRatio: false,
        layout: { padding: { top: 20 } }
    };

    // 1. Overall Chart
    const totals = { agent: 0, greptile: 0, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 };
    let totalPRs = 0;

    Object.values(fullDataset).forEach(projPrs => {
        projPrs.forEach(pr => {
            totalPRs++;
            tools.forEach(t => {
                if (pr.tools[t]) totals[t]++;
            });
        });
    });

    const rates = tools.map(t => Math.round((totals[t] / totalPRs) * 100));
    const counts = tools.map(t => totals[t]);

    new Chart(document.getElementById('overallChart'), {
        type: 'bar',
        data: {
            labels: toolLabels,
            datasets: [{
                data: rates,
                counts: counts, // Pass raw counts for formatter
                backgroundColor: tools.map(t => calculateAlpha(colors[t], 0.2)),
                borderColor: tools.map(t => colors[t]),
                borderWidth: 2,
                borderDash: [5, 5],
                borderRadius: 4,
                barPercentage: 0.6
            }]
        },
        options: {
            ...commonOptions,
            plugins: {
                ...commonOptions.plugins,
                datalabels: {
                    ...commonOptions.plugins.datalabels,
                    formatter: (value) => `${value}%`
                },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const count = context.dataset.counts[context.dataIndex];
                            const rate = context.raw;
                            const missed = totalPRs - count;
                            return [
                                ` 命中率: ${rate}%`,
                                ` 检出数: ${count} / ${totalPRs} 个PR`,
                                ` 漏检数: ${missed} 个PR`
                            ];
                        }
                    },
                    padding: 12,
                    cornerRadius: 8,
                    displayColors: false,
                    titleFont: { size: 13 },
                    bodyFont: { size: 12, family: 'monospace' }
                }
            },
            scales: {
                y: { max: 100, display: false, grid: { display: false } },
                x: {
                    grid: { display: false },
                    ticks: {
                        autoSkip: false,
                        maxRotation: 0,
                        font: { size: 11, weight: 'bold' }
                    }
                }
            }
        }
    });

    // 2. Severity Breakdown (Grouped Bar Chart)
    const severityLevels = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
    const severityLabels = ['Critical', 'High', 'Medium', 'Low'];

    // Initialize stats: { agent: [crit, high, med, low], ... }
    const severityStats = {};
    tools.forEach(t => severityStats[t] = [0, 0, 0, 0]);
    // Initialize severityCounts which stores TOTAL PRs per severity
    const severityCounts = [0, 0, 0, 0];

    Object.values(fullDataset).forEach(projPrs => {
        projPrs.forEach(pr => {
            const sevIdx = severityLevels.indexOf(pr.sev);
            if (sevIdx !== -1) {
                severityCounts[sevIdx]++;
                tools.forEach(t => {
                    if (pr.tools[t]) severityStats[t][sevIdx]++;
                });
            }
        });
    });

    // Create datasets for each tool
    const datasets = tools.map((t, index) => {
        // Calculate percentages
        const data = severityCounts.map((count, idx) =>
            count === 0 ? 0 : Math.round((severityStats[t][idx] / count) * 100)
        );
        const toolCounts = severityStats[t];

        return {
            label: toolLabels[index],
            data: data,
            counts: toolCounts, // Pass raw counts for tooltips
            backgroundColor: calculateAlpha(colors[t], 0.2),
            borderColor: colors[t],
            borderWidth: 2,
            borderDash: [5, 5],
            borderRadius: 4,
            barPercentage: 0.7,
            categoryPercentage: 0.8
        };
    });

    new Chart(document.getElementById('severityChart'), {
        type: 'bar',
        data: {
            labels: severityLabels,
            datasets: datasets
        },
        options: {
            plugins: {
                legend: {
                    display: false,
                    position: 'bottom',
                    labels: { usePointStyle: true, boxWidth: 8 }
                },
                datalabels: {
                    anchor: 'end',
                    align: 'top',
                    formatter: (value) => value === 0 ? '' : value + '%',
                    font: { weight: 'bold', size: 10 },
                    color: '#666',
                    display: function (context) {
                        return context.dataset.data[context.dataIndex] > 0; // Hide 0% labels
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function (context) {
                            const count = context.dataset.counts[context.dataIndex];
                            const rate = context.raw;
                            const total = severityCounts[context.dataIndex];
                            return [
                                ` ${context.dataset.label}`,
                                ` 命中率: ${rate}%`,
                                ` 检出数: ${count}/${total} (${context.label} 严重程度)`
                            ];
                        }
                    },
                    padding: 12,
                    cornerRadius: 8,
                    displayColors: true,
                    titleFont: { size: 13 },
                    bodyFont: { size: 12, family: 'monospace' }
                }
            },
            maintainAspectRatio: false,
            scales: {
                y: { max: 100, display: false },
                x: { grid: { display: false } }
            },
            layout: { padding: { top: 25 } }
        }
    });

}

// Helper to add alpha to hex/rgb colors
function calculateAlpha(color, alpha) {
    if (color.startsWith('#')) {
        const r = parseInt(color.slice(1, 3), 16);
        const g = parseInt(color.slice(3, 5), 16);
        const b = parseInt(color.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    } else if (color.startsWith('rgb')) {
        return color.replace(')', `, ${alpha})`).replace('rgb', 'rgba');
    }
    return color;
}

// Printer Effect Logic
function startPrinterEffect() {
    const textElement = document.getElementById('printer-text');
    if (!textElement) return;

    // Content segments to type
    const segments = [
        { text: "选择 ", type: "text" },
        { text: "DeltaConverge", type: "code" },
        { text: " 下的PR可查看审查报告，如需了解更多请访问", type: "text" },
        { text: " Greptile Benchmarks", type: "link", url: "https://www.greptile.com/benchmarks" }
    ];

    let segmentIndex = 0;
    let charIndex = 0;

    function type() {
        if (segmentIndex >= segments.length) return;

        const segment = segments[segmentIndex];

        // If it's the start of a segment, create the wrapping element if needed
        if (charIndex === 0) {
            if (segment.type === 'code') {
                const span = document.createElement('span');
                span.className = 'highlight-code';
                span.textContent = ''; // Start empty
                textElement.appendChild(span);
            } else if (segment.type === 'link') {
                const a = document.createElement('a');
                a.href = segment.url;
                a.className = 'printer-link';
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                a.textContent = ''; // Start empty
                textElement.appendChild(a);
            } else {
                const span = document.createElement('span');
                textElement.appendChild(span);
            }
        }

        // Get the current element to type into (last child)
        const currentEl = textElement.lastElementChild;

        // Add next character
        currentEl.textContent += segment.text.charAt(charIndex);
        charIndex++;

        // Check if segment is finished
        if (charIndex >= segment.text.length) {
            segmentIndex++;
            charIndex = 0;
            setTimeout(type, 300); // Pause between segments
        } else {
            // Typing speed (randomized slightly for realism)
            const speed = 30 + Math.random() * 50;
            setTimeout(type, speed);
        }
    }

    // Start typing after a short delay
    setTimeout(type, 1500);
}
