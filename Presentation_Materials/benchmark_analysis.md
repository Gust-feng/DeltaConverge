#  AI 代码审查 Benchmark 统计分析

> 基于 50 个真实生产环境 PR 的命中率统计 (脚本计算版)

---

## 1. 总体命中率 (Overall Hit Rate)

| 工具 | 命中数 | 命中率 |
|---|---|---|
| **Greptile** | 41 | **82%** |
| **DeltaConverge** | 37 | **74%** |
| **Cursor** | 29 | **58%** |
| **Copilot** | 26 | **52%** |
| **CodeRabbit** | 22 | **44%** |
| **Graphite** | 3 | **6%** |

---

## 2. 各项目命中率分解

| 项目 | DeltaConverge | Greptile | Copilot | CodeRabbit | Cursor | Graphite |
|---|---|---|---|---|---|---|
| **Sentry** (Python) | 5/10 (50%) | 8/10 (80%) | 4/10 (40%) | 3/10 (30%) | 4/10 (40%) | 0/10 (0%) |
| **Cal.com** (TypeScript) | 8/10 (80%) | 8/10 (80%) | 6/10 (60%) | 4/10 (40%) | 5/10 (50%) | 0/10 (0%) |
| **Grafana** (Go) | 9/10 (90%) | 8/10 (80%) | 5/10 (50%) | 5/10 (50%) | 7/10 (70%) | 3/10 (30%) |
| **Keycloak** (Java) | 8/10 (80%) | 8/10 (80%) | 4/10 (40%) | 5/10 (50%) | 6/10 (60%) | 0/10 (0%) |
| **Discourse** (Ruby) | 7/10 (70%) | 9/10 (90%) | 7/10 (70%) | 5/10 (50%) | 7/10 (70%) | 0/10 (0%) |

---

## 3. 各严重程度命中率分解

### 严重程度分布
- **CRITICAL**: 15 PRs
- **HIGH**: 17 PRs
- **MEDIUM**: 11 PRs
- **LOW**: 7 PRs

| 严重程度 | PR数量 | DeltaConverge | Greptile | Copilot | CodeRabbit | Cursor | Graphite |
|---|---|---|---|---|---|---|---|
| **CRITICAL** | 15 | 9 (60%) | 11 (73%) | 8 (53%) | 5 (33%) | 9 (60%) | 1 (7%) |
| **HIGH** | 17 | 16 (94%) | 14 (82%) | 7 (41%) | 6 (35%) | 9 (53%) | 0 (0%) |
| **MEDIUM** | 11 | 8 (73%) | 10 (91%) | 7 (64%) | 6 (55%) | 7 (64%) | 1 (9%) |
| **LOW** | 7 | 4 (57%) | 6 (86%) | 4 (57%) | 5 (71%) | 4 (57%) | 1 (14%) |

---

## 4. 关键洞察

- **Greptile 综合领先**: 82% 总体命中率
- **DeltaConverge 排名第二**: 74%
- **HIGH 级别 DeltaConverge 最强**: 16/17 (94%) 超越 Greptile (82%)
- **Grafana 项目亮点**: DeltaConverge 90% > Greptile 80%
- **Sentry 项目短板**: DeltaConverge 仅 50%

---

## 5. DeltaConverge 漏报详情 (13个)

### Sentry (漏报: 5)
- PR #3: LOW
- PR #4: CRITICAL
- PR #5: CRITICAL
- PR #6: MEDIUM
- PR #7: MEDIUM

### Cal.com (漏报: 2)
- PR #7: CRITICAL
- PR #10: LOW

### Grafana (漏报: 1)
- PR #3: CRITICAL

### Keycloak (漏报: 2)

- PR #2: CRITICAL
- PR #7: LOW

### Discourse (漏报: 3)
- PR #6: MEDIUM
- PR #8: HIGH
- PR #10: CRITICAL
