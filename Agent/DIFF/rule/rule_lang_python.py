"""Python 规则：按路径/关键词给出上下文建议。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from Agent.DIFF.rule.rule_base import RuleHandler, RuleSuggestion

Unit = Dict[str, Any]


class PythonRuleHandler(RuleHandler):
    def __init__(self):
        super().__init__(language="python")
    
    def match(self, unit: Unit) -> Optional[RuleSuggestion]:
        file_path = str(unit.get("file_path", "")).lower()
        metrics = unit.get("metrics", {}) or {}
        total_changed = self._total_changed(metrics)
        tags = set(unit.get("tags", []) or [])
        symbol = unit.get("symbol") or {}
        sym_name = symbol.get("name", "").lower() if isinstance(symbol, dict) else ""

        # 从配置加载路径规则
        path_rules = self._get_language_config("path_rules", [])
        path_match = self._match_path_rules(file_path, path_rules, unit)
        if path_match:
            return path_match

        # 从配置加载符号规则
        sym_rules = self._get_language_config("symbol_rules", [])
        if symbol:
            sym_match = self._match_symbol_rules(symbol, sym_rules, unit)
            if sym_match:
                return sym_match

        # 从配置加载度量规则
        metric_rules = self._get_language_config("metric_rules", [])
        metric_match = self._match_metric_rules(metrics, metric_rules, unit)
        if metric_match:
            return metric_match

        # 从配置加载关键词
        keywords = self._get_language_config("keywords", [])
        # 添加基础安全关键词
        keywords.extend(self._get_base_config("security_keywords", []))
        haystack = self._build_haystack(file_path, sym_name, tags)
        keyword_match = self._match_keywords(haystack, keywords, unit, note_prefix="lang_py:kw:")
        if keyword_match:
            return keyword_match

        # 默认返回：如果没有匹配到任何规则，返回低置信度的默认建议
        return RuleSuggestion(
            context_level="function",
            confidence=self._calculate_confidence({
                "base_confidence": 0.3,
                "confidence_adjusters": {
                    "file_size": 0.0,
                    "change_type": 0.0,
                    "security_sensitive": 0.0,
                    "rule_specificity": 0.0
                }
            }, unit),
            notes="py:default_rule",
        )


__all__ = ["PythonRuleHandler"]
