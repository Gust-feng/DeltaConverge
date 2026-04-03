"""规则成长系统服务。"""

from __future__ import annotations

from typing import Any, Dict, List


class RuleService:
    def get_rule_growth_summary(self) -> Dict[str, Any]:
        from Agent.core.api.rule_growth import RuleGrowthAPI

        summary = RuleGrowthAPI.get_summary()
        summary["trend"] = RuleGrowthAPI.get_trend_analysis()
        summary["types"] = RuleGrowthAPI.get_conflict_types()
        return summary

    def get_rule_growth_suggestions(self) -> Dict[str, Any]:
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.get_enhanced_suggestions()

    def apply_rule_growth_rule(self, rule_id: str) -> Dict[str, Any]:
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.apply_rule(rule_id)

    def promote_rule_growth_hint(
        self,
        *,
        language: str,
        tags: List[str],
        suggested_context_level: str,
        sample_count: int = 0,
        consistency: float = 0.0,
        conflict_type: str = "",
    ) -> Dict[str, Any]:
        from Agent.core.api.rule_growth import RuleGrowthAPI

        return RuleGrowthAPI.promote_hint(
            language=language,
            tags=tags,
            suggested_context_level=suggested_context_level,
            sample_count=sample_count,
            consistency=consistency,
            conflict_type=conflict_type,
        )

    def cleanup_rule_growth(self, *, max_age_days: int = 30, clear_session: bool = True) -> Dict[str, Any]:
        from Agent.core.api.rule_growth import RuleGrowthAPI

        result = RuleGrowthAPI.cleanup_old_conflicts(max_age_days=max_age_days)
        if clear_session:
            result["session"] = RuleGrowthAPI.clear_session_conflicts()
        return result
