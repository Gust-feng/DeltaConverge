// Statistics Script - Calculate benchmark results from main.js data

const agentResults = {
    'Sentry': { miss: [3, 4, 5, 6, 7], lang: 'Python' },
    'Cal.com': { miss: [7, 10], lang: 'TypeScript' },
    'Grafana': { miss: [3], lang: 'Go' },
    'Keycloak': { miss: [2, 7], lang: 'Java' },
    'Discourse': { miss: [6, 8, 10], lang: 'Ruby' }
};

const sentryData = [
    { id: 1, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 2, sev: "CRITICAL", greptile: 0, copilot: 0, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 3, sev: "LOW", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 4, sev: "CRITICAL", greptile: 0, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 5, sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 6, sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 7, sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 8, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 9, sev: "HIGH", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 10, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 }
];

const calData = [
    { id: 1, sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 2, sev: "CRITICAL", greptile: 0, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 3, sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 4, sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 5, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 6, sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 7, sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 8, sev: "HIGH", greptile: 0, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 9, sev: "HIGH", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 10, sev: "LOW", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 }
];

const grafanaData = [
    { id: 1, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 2, sev: "HIGH", greptile: 0, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 3, sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 4, sev: "CRITICAL", greptile: 0, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 5, sev: "MEDIUM", greptile: 1, copilot: 0, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 6, sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 1 },
    { id: 7, sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 0, graphite: 1 },
    { id: 8, sev: "HIGH", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 9, sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 1 },
    { id: 10, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 }
];

const keycloakData = [
    { id: 1, sev: "MEDIUM", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 2, sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 3, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 4, sev: "MEDIUM", greptile: 0, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 5, sev: "HIGH", greptile: 0, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 6, sev: "HIGH", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 7, sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 8, sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 9, sev: "MEDIUM", greptile: 1, copilot: 0, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 10, sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 }
];

const discourseData = [
    { id: 1, sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 2, sev: "HIGH", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 3, sev: "CRITICAL", greptile: 1, copilot: 0, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 4, sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 5, sev: "LOW", greptile: 0, copilot: 0, rabbit: 1, cursor: 0, graphite: 0 },
    { id: 6, sev: "MEDIUM", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 },
    { id: 7, sev: "LOW", greptile: 1, copilot: 1, rabbit: 1, cursor: 1, graphite: 0 },
    { id: 8, sev: "HIGH", greptile: 1, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 9, sev: "HIGH", greptile: 1, copilot: 1, rabbit: 0, cursor: 0, graphite: 0 },
    { id: 10, sev: "CRITICAL", greptile: 1, copilot: 1, rabbit: 0, cursor: 1, graphite: 0 }
];

const projectDataMap = {
    'Sentry': sentryData,
    'Cal.com': calData,
    'Grafana': grafanaData,
    'Keycloak': keycloakData,
    'Discourse': discourseData
};

const tools = ['agent', 'greptile', 'copilot', 'rabbit', 'cursor', 'graphite'];
const toolLabels = ['DeltaConverge', 'Greptile', 'Copilot', 'CodeRabbit', 'Cursor', 'Graphite'];

// Build full dataset
const fullDataset = {};
Object.keys(agentResults).forEach(proj => {
    const config = agentResults[proj];
    const realData = projectDataMap[proj];
    fullDataset[proj] = realData.map(pr => ({
        id: pr.id,
        sev: pr.sev,
        tools: {
            agent: !config.miss.includes(pr.id),
            greptile: pr.greptile === 1,
            copilot: pr.copilot === 1,
            rabbit: pr.rabbit === 1,
            cursor: pr.cursor === 1,
            graphite: pr.graphite === 1
        }
    }));
});

// ========== STATISTICS ==========

console.log("=".repeat(60));
console.log("AI Code Review Benchmark Statistics");
console.log("=".repeat(60));

// 1. Overall totals
console.log("\n## 1. Overall Hit Rate\n");
const totals = { agent: 0, greptile: 0, copilot: 0, rabbit: 0, cursor: 0, graphite: 0 };
let totalPRs = 0;

Object.values(fullDataset).forEach(projPrs => {
    projPrs.forEach(pr => {
        totalPRs++;
        tools.forEach(t => { if (pr.tools[t]) totals[t]++; });
    });
});

console.log("| Tool | Hits | Rate |");
console.log("|---|---|---|");;
tools.forEach((t, i) => {
    const rate = Math.round((totals[t] / totalPRs) * 100);
    console.log(`| ${toolLabels[i]} | ${totals[t]} | ${rate}% |`);
});

// 2. By project
console.log("\n## 2. Hit Rate by Project\n");
console.log("| Project | " + toolLabels.join(" | ") + " |");
console.log("|---|" + tools.map(() => "---|").join(""));

Object.keys(fullDataset).forEach(proj => {
    const projTotals = {};
    tools.forEach(t => projTotals[t] = 0);
    fullDataset[proj].forEach(pr => {
        tools.forEach(t => { if (pr.tools[t]) projTotals[t]++; });
    });
    const row = tools.map(t => `${projTotals[t]}/10 (${projTotals[t] * 10}%)`).join(" | ");
    console.log(`| ${proj} | ${row} |`);
});

// 3. By severity
console.log("\n## 3. Hit Rate by Severity\n");
const sevLevels = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];

// Count PRs per severity
const sevCounts = {};
sevLevels.forEach(s => sevCounts[s] = 0);
Object.values(fullDataset).forEach(projPrs => {
    projPrs.forEach(pr => { sevCounts[pr.sev]++; });
});

console.log("### Severity Distribution:");
sevLevels.forEach(s => console.log(`- ${s}: ${sevCounts[s]} PRs`));

console.log("\n### Hit Rate by Severity:\n");
console.log("| Severity | Count | " + toolLabels.join(" | ") + " |");
console.log("|---|---|" + tools.map(() => "---|").join(""));

sevLevels.forEach(sev => {
    const sevTotals = {};
    tools.forEach(t => sevTotals[t] = 0);
    let count = 0;

    Object.values(fullDataset).forEach(projPrs => {
        projPrs.filter(pr => pr.sev === sev).forEach(pr => {
            count++;
            tools.forEach(t => { if (pr.tools[t]) sevTotals[t]++; });
        });
    });

    const row = tools.map(t => {
        const rate = count > 0 ? Math.round((sevTotals[t] / count) * 100) : 0;
        return `${sevTotals[t]} (${rate}%)`;
    }).join(" | ");
    console.log(`| ${sev} | ${count} | ${row} |`);
});

// 4. Agent misses
console.log("\n## 4. DeltaConverge Misses\n");
Object.keys(fullDataset).forEach(proj => {
    const misses = fullDataset[proj].filter(pr => !pr.tools.agent);
    console.log(`### ${proj} (Missed: ${misses.length})`);
    misses.forEach(pr => console.log(`- PR #${pr.id}: ${pr.sev}`));
    console.log("");
});
