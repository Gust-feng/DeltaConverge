"""规则反馈与自成长机制模块。

用于记录规则层与 LLM 决策之间的冲突，帮助开发者优化规则。

主要功能：
- 冲突检测与记录
- 冲突汇总统计
- 模式提取与规则建议生成
- 冲突清理（按时间/数量）
- 趋势分析
- 规则建议导出
"""

from .conflict_tracker import (
    ConflictTracker,
    ConflictType,
    RuleConflict,
    get_conflict_tracker,
    record_conflict,
)

__all__ = [
    "ConflictTracker",
    "ConflictType",
    "RuleConflict",
    "get_conflict_tracker",
    "record_conflict",
]
