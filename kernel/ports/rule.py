"""规则成长系统接口定义

定义规则冲突统计、建议生成与规则晋升的抽象接口。
对应旧实现 ``Agent.core.api.rule_growth.RuleGrowthAPI``。
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class RulePort(Protocol):
    """规则成长系统接口。

    负责规则冲突的汇总、趋势分析、建议生成，以及规则的应用与晋升。
    所有返回值均为普通字典，避免 legacy 内部类型泄漏进内核。
    """

    def get_summary(self) -> Dict[str, Any]:
        """获取规则成长总览。"""
        ...

    def get_trend_analysis(self) -> Dict[str, Any]:
        """获取冲突趋势分析。"""
        ...

    def get_conflict_types(self) -> Dict[str, Any]:
        """获取冲突类型分布。"""
        ...

    def get_enhanced_suggestions(self) -> Dict[str, Any]:
        """获取增强版规则建议。"""
        ...

    def apply_rule(self, rule_id: str) -> Dict[str, Any]:
        """应用一条建议规则。

        Args:
            rule_id: 建议规则标识

        Returns:
            应用结果
        """
        ...

    def promote_hint(
        self,
        *,
        language: str,
        tags: List[str],
        suggested_context_level: str,
        sample_count: int = 0,
        consistency: float = 0.0,
        conflict_type: str = "",
    ) -> Dict[str, Any]:
        """将一条提示晋升为正式规则。"""
        ...

    def cleanup_old_conflicts(self, *, max_age_days: int = 30) -> Dict[str, Any]:
        """清理过期冲突记录。"""
        ...

    def clear_session_conflicts(self) -> Dict[str, Any]:
        """清理当前会话级冲突记录。"""
        ...


__all__ = ["RulePort"]
