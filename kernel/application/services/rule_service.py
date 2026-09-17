"""规则成长系统服务。

通过 RulePort 访问规则成长能力，不直接依赖旧 Agent/ 代码。
未注入端口时回退到 Legacy 适配器，保证可独立运行与向后兼容。
"""

from __future__ import annotations

from typing import Any, Dict, List

from kernel.ports.rule import RulePort


class RuleService:
    def __init__(self, *, rule_port: RulePort | None = None) -> None:
        if rule_port is None:
            from kernel.infrastructure import LegacyRuleAdapter

            rule_port = LegacyRuleAdapter()
        self.rule_port = rule_port

    def get_rule_growth_summary(self) -> Dict[str, Any]:
        summary = self.rule_port.get_summary()
        summary["trend"] = self.rule_port.get_trend_analysis()
        summary["types"] = self.rule_port.get_conflict_types()
        return summary

    def get_rule_growth_suggestions(self) -> Dict[str, Any]:
        return self.rule_port.get_enhanced_suggestions()

    def apply_rule_growth_rule(self, rule_id: str) -> Dict[str, Any]:
        return self.rule_port.apply_rule(rule_id)

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
        return self.rule_port.promote_hint(
            language=language,
            tags=tags,
            suggested_context_level=suggested_context_level,
            sample_count=sample_count,
            consistency=consistency,
            conflict_type=conflict_type,
        )

    def cleanup_rule_growth(self, *, max_age_days: int = 30, clear_session: bool = True) -> Dict[str, Any]:
        result = self.rule_port.cleanup_old_conflicts(max_age_days=max_age_days)
        if clear_session:
            result["session"] = self.rule_port.clear_session_conflicts()
        return result
