============================================================
AI Code Review Benchmark Statistics
============================================================

## 1. Overall Hit Rate

| Tool | Hits | Rate |
|---|---|---|
| DeltaConverge | 37 | 74% |
| Greptile | 41 | 82% |
| Copilot | 26 | 52% |
| CodeRabbit | 22 | 44% |
| Cursor | 29 | 58% |
| Graphite | 3 | 6% |

## 2. Hit Rate by Project

| Project | DeltaConverge | Greptile | Copilot | CodeRabbit | Cursor | Graphite |
|---|---|---|---|---|---|---|
| Sentry | 5/10 (50%) | 8/10 (80%) | 4/10 (40%) | 3/10 (30%) | 4/10 (40%) | 0/10 (0%) |
| Cal.com | 8/10 (80%) | 8/10 (80%) | 6/10 (60%) | 4/10 (40%) | 5/10 (50%) | 0/10 (0%) |
| Grafana | 9/10 (90%) | 8/10 (80%) | 5/10 (50%) | 5/10 (50%) | 7/10 (70%) | 3/10 (30%) |
| Keycloak | 8/10 (80%) | 8/10 (80%) | 4/10 (40%) | 5/10 (50%) | 6/10 (60%) | 0/10 (0%) |
| Discourse | 7/10 (70%) | 9/10 (90%) | 7/10 (70%) | 5/10 (50%) | 7/10 (70%) | 0/10 (0%) |

## 3. Hit Rate by Severity

### Severity Distribution:
- CRITICAL: 15 PRs
- HIGH: 17 PRs
- MEDIUM: 11 PRs
- LOW: 7 PRs

### Hit Rate by Severity:

| Severity | Count | DeltaConverge | Greptile | Copilot | CodeRabbit | Cursor | Graphite |
|---|---|---|---|---|---|---|---|
| CRITICAL | 15 | 9 (60%) | 11 (73%) | 8 (53%) | 5 (33%) | 9 (60%) | 1 (7%) |
| HIGH | 17 | 16 (94%) | 14 (82%) | 7 (41%) | 6 (35%) | 9 (53%) | 0 (0%) |
| MEDIUM | 11 | 8 (73%) | 10 (91%) | 7 (64%) | 6 (55%) | 7 (64%) | 1 (9%) |
| LOW | 7 | 4 (57%) | 6 (86%) | 4 (57%) | 5 (71%) | 4 (57%) | 1 (14%) |

## 4. DeltaConverge Misses

### Sentry (Missed: 5)
- PR #3: LOW
- PR #4: CRITICAL
- PR #5: CRITICAL
- PR #6: MEDIUM
- PR #7: MEDIUM

### Cal.com (Missed: 2)
- PR #7: CRITICAL
- PR #10: LOW

### Grafana (Missed: 1)
- PR #3: CRITICAL

### Keycloak (Missed: 2)
- PR #2: CRITICAL
- PR #7: LOW

### Discourse (Missed: 3)
- PR #6: MEDIUM
- PR #8: HIGH
- PR #10: CRITICAL

