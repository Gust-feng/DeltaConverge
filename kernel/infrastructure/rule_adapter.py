"""Legacy 规则成长适配器

包装旧内核的 ``Agent.core.api.rule_growth.RuleGrowthAPI``，实现新的 RulePort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from kernel.ports.rule import RulePort

logger = logging.getLogger(__name__)


class LegacyRuleAdapter(RulePort):
    """包装旧规则成长 API 的适配器。"""

    def get_summary(self) -> Dict[str, Any]:
        """获取规则成长总览。"""
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.get_summary()

    def get_trend_analysis(self) -> Dict[str, Any]:
        """获取冲突趋势分析。"""
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.get_trend_analysis()

    def get_conflict_types(self) -> Dict[str, Any]:
        """获取冲突类型分布。"""
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.get_conflict_types()

    def get_enhanced_suggestions(self) -> Dict[str, Any]:
        """获取增强版规则建议。"""
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.get_enhanced_suggestions()

    def apply_rule(self, rule_id: str) -> Dict[str, Any]:
        """应用一条建议规则。"""
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.apply_rule(rule_id)

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
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.promote_hint(
            language=language,
            tags=tags,
            suggested_context_level=suggested_context_level,
            sample_count=sample_count,
            consistency=consistency,
            conflict_type=conflict_type,
        )

    def cleanup_old_conflicts(self, *, max_age_days: int = 30) -> Dict[str, Any]:
        """清理过期冲突记录。"""
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.cleanup_old_conflicts(max_age_days=max_age_days)

    def clear_session_conflicts(self) -> Dict[str, Any]:
        """清理当前会话级冲突记录。"""
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.clear_session_conflicts()


__all__ = ["LegacyRuleAdapter"]
