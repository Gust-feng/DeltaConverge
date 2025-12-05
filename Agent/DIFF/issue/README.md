# 规则自成长机制

本模块用于记录规则层与 LLM 决策之间的冲突，帮助开发者持续优化规则。

## 冲突类型

| 类型 | 说明 | 优化建议 |
|------|------|----------|
| `rule_high_llm_expand` | 规则高置信度建议较小上下文，LLM 要求更多上下文 | 规则可能低估了变更的复杂度，考虑调整规则的上下文级别 |
| `rule_high_llm_skip` | 规则高置信度认为需要审查，LLM 建议跳过 | 规则可能高估了变更的风险，考虑添加噪音标签识别 |
| `rule_low_llm_consistent` | 规则低置信度，LLM 多次给出相同决策 | 可以提取新规则，提高规则覆盖率 |
| `context_level_mismatch` | 中等置信度，上下文级别差异超过 1 级 | 规则的置信度计算可能需要调整 |

## 目录结构

```
Agent/DIFF/issue/
├── __init__.py           # 模块入口
├── conflict_tracker.py   # 冲突追踪器实现
├── README.md             # 本文档
├── conflicts/            # 冲突记录存储（已加入 .gitignore）
│   └── *.json            # 单个冲突记录
└── patterns/             # 可提取的新规则模式（已加入 .gitignore）
    └── *.json            # 模式分析结果和报告
```

## 核心功能

### 1. 自动记录（已集成到 fusion.py）

冲突追踪已自动集成到融合层，无需手动调用。每次融合规则与 LLM 决策时，系统会自动检测并记录冲突。

### 2. 手动记录

```python
from Agent.DIFF.issue import record_conflict

# 检测并记录冲突
filepath = record_conflict(unit, llm_decision)
if filepath:
    print(f"冲突已记录: {filepath}")
```

### 3. 获取汇总统计

```python
from Agent.DIFF.issue import get_conflict_tracker

tracker = get_conflict_tracker()
summary = tracker.get_summary()

print(f"总冲突数: {summary['total_conflicts']}")
print(f"按类型: {summary['by_type']}")
print(f"按语言: {summary['by_language']}")
print(f"按规则: {summary['by_rule_notes']}")
```

### 4. 导出可提取的新规则模式

```python
from Agent.DIFF.issue import get_conflict_tracker

tracker = get_conflict_tracker()
patterns = tracker.export_patterns()

for pattern in patterns:
    print(f"建议新规则: {pattern['pattern_key']}")
    print(f"  语言: {pattern['language']}")
    print(f"  文件模式: {pattern['file_pattern']}")
    print(f"  建议上下文: {pattern['suggested_context_level']}")
    print(f"  出现次数: {pattern['occurrence_count']}")
```

### 5. 趋势分析

```python
tracker = get_conflict_tracker()
trend = tracker.get_trend_analysis(days=7)

print(f"最近 {trend['period_days']} 天冲突数: {trend['total_conflicts']}")
print(f"日均冲突: {trend['average_daily']}")
print(f"变化率: {trend['change_rate_percent']}%")
print(f"最常见类型: {trend['most_common_type']}")
print(f"最受影响语言: {trend['most_affected_language']}")
```

### 6. 生成规则优化建议

```python
tracker = get_conflict_tracker()
suggestions = tracker.generate_rule_suggestions()

for s in suggestions:
    print(f"建议类型: {s['type']}")
    print(f"  当前行为: {s.get('current_behavior', 'N/A')}")
    print(f"  建议修改: {s.get('suggested_change', 'N/A')}")
    print(f"  置信度: {s.get('confidence', 0):.2f}")
    print(f"  出现次数: {s['occurrence_count']}")
```

### 7. 导出完整报告

```python
tracker = get_conflict_tracker()
report_path = tracker.export_report()
print(f"报告已导出: {report_path}")

# 或指定输出路径
report_path = tracker.export_report("my_report.json")
```

### 8. 清理旧记录

```python
tracker = get_conflict_tracker()

# 清理 30 天前的记录
deleted = tracker.cleanup_old_conflicts(max_age_days=30)
print(f"已删除 {deleted} 条旧记录")

# 或限制最大数量
deleted = tracker.cleanup_old_conflicts(max_count=1000)
print(f"已删除 {deleted} 条超量记录")
```

### 9. 获取高优先级冲突

```python
tracker = get_conflict_tracker()
high_priority = tracker.get_high_priority_conflicts(limit=10)

for conflict in high_priority:
    print(f"[{conflict.conflict_type.value}] {conflict.file_path}")
    print(f"  规则置信度: {conflict.rule_confidence}")
    print(f"  LLM 建议: {conflict.llm_context_level}")
```

## 冲突记录格式

```json
{
  "conflict_type": "rule_high_llm_expand",
  "unit_id": "xxx",
  "file_path": "app/views.py",
  "language": "python",
  "tags": ["django"],
  "metrics": {"added_lines": 10, "removed_lines": 5},
  "rule_context_level": "function",
  "rule_confidence": 0.85,
  "rule_notes": "py:decorator:django_view",
  "llm_context_level": "file_context",
  "llm_skip_review": false,
  "llm_reason": "需要查看类的其他方法",
  "final_context_level": "file_context",
  "timestamp": "2024-12-05T10:30:00"
}
```

## 规则优化流程

1. **收集冲突**：系统自动记录冲突到 `conflicts/` 目录
2. **分析汇总**：使用 `get_summary()` 查看冲突分布
3. **趋势分析**：使用 `get_trend_analysis()` 了解冲突变化趋势
4. **识别模式**：使用 `export_patterns()` 找出可提取的新规则
5. **生成建议**：使用 `generate_rule_suggestions()` 获取具体优化建议
6. **导出报告**：使用 `export_report()` 生成完整分析报告
7. **优化规则**：根据分析结果修改 `rule_config.py` 或语言特定规则
8. **验证效果**：清空冲突记录，重新运行审查，观察冲突数量变化

## 规则建议类型

| 建议类型 | 说明 | 来源冲突类型 |
|----------|------|--------------|
| `upgrade_context_level` | 建议提升上下文级别 | `rule_high_llm_expand` |
| `add_noise_detection` | 建议添加噪音检测 | `rule_high_llm_skip` |
| `new_rule` | 建议添加新规则 | `rule_low_llm_consistent` |

## 对外 API

自成长机制通过 `RuleGrowthAPI` 对外提供统一接口：

```python
from Agent.core.api import RuleGrowthAPI

# 获取冲突汇总统计
summary = RuleGrowthAPI.get_summary()
# {"total_conflicts": 10, "by_type": {...}, "by_language": {...}, "error": None}

# 获取趋势分析
trend = RuleGrowthAPI.get_trend_analysis(days=7)
# {"period_days": 7, "total_conflicts": 10, "average_daily": 1.43, ...}

# 获取规则优化建议
suggestions = RuleGrowthAPI.get_rule_suggestions()
# {"suggestions": [...], "total_count": 3, "error": None}

# 获取可提取的新规则模式
patterns = RuleGrowthAPI.get_extractable_patterns()
# {"patterns": [...], "total_count": 2, "error": None}

# 获取高优先级冲突
high_priority = RuleGrowthAPI.get_high_priority_conflicts(limit=10)
# {"conflicts": [...], "total_count": 5, "error": None}

# 按类型获取冲突
by_type = RuleGrowthAPI.get_conflicts_by_type("rule_high_llm_expand", limit=20)
# {"conflicts": [...], "total_count": 8, "error": None}

# 清理旧冲突记录
cleanup = RuleGrowthAPI.cleanup_old_conflicts(max_age_days=30, max_count=1000)
# {"deleted_count": 5, "remaining_count": 95, "error": None}

# 导出完整报告
report = RuleGrowthAPI.export_report()
# {"report_path": "...", "report": {...}, "error": None}

# 获取冲突类型说明
types = RuleGrowthAPI.get_conflict_types()
# {"types": [...], "error": None}

# 会话冲突管理
session = RuleGrowthAPI.get_session_conflicts()
RuleGrowthAPI.clear_session_conflicts()
```

### API 方法列表

| 方法 | 说明 |
|------|------|
| `get_summary()` | 获取冲突汇总统计 |
| `get_trend_analysis(days)` | 获取冲突趋势分析 |
| `get_rule_suggestions()` | 生成规则优化建议 |
| `get_extractable_patterns()` | 获取可提取的新规则模式 |
| `get_high_priority_conflicts(limit)` | 获取高优先级冲突 |
| `get_conflicts_by_type(type, limit)` | 按类型获取冲突 |
| `cleanup_old_conflicts(max_age_days, max_count)` | 清理旧冲突记录 |
| `export_report(output_path)` | 导出完整分析报告 |
| `get_conflict_types()` | 获取冲突类型说明 |
| `get_session_conflicts()` | 获取当前会话冲突 |
| `clear_session_conflicts()` | 清空会话冲突缓存 |

## 注意事项

- 冲突记录仅用于规则优化分析，不影响审查流程
- `conflicts/` 和 `patterns/` 目录中的 JSON 文件已加入 `.gitignore`，不会提交到版本控制
- 建议定期使用 `cleanup_old_conflicts()` 清理旧记录，避免磁盘占用过大
- 高频出现的冲突模式应优先处理
- 规则建议的置信度越高，建议越可靠
