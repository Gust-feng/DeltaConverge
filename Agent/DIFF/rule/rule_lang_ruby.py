"""Ruby 规则：按路径/关键词给出上下文建议。"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
from Agent.DIFF.rule.rule_base import RuleHandler, RuleSuggestion, _detect_patterns, _patterns_to_notes

Unit = Dict[str, Any]
DEFAULT_LANGUAGE_SPECIFICITY_BONUS = 0.1

RUBY_RAILS_PATTERNS = {
    "rails_callbacks": {
        "patterns": [r"\bbefore_action\b", r"\bafter_action\b", r"\bbefore_save\b"],
        "risk": "high", "context_level": "file", "notes": "rb:rails:callback",
    },
    "rails_associations": {
        "patterns": [r"\bhas_many\b", r"\bhas_one\b", r"\bbelongs_to\b"],
        "risk": "high", "context_level": "file", "notes": "rb:rails:association",
    },
    "rails_validations": {
        "patterns": [r"\bvalidates\b", r"\bvalidate\b"],
        "risk": "medium", "context_level": "function", "notes": "rb:rails:validation",
    },
    "rails_scopes": {
        "patterns": [r"\bscope\s+:", r"\bdefault_scope\b"],
        "risk": "medium", "context_level": "function", "notes": "rb:rails:scope",
    },
}

RUBY_FRAMEWORK_PATH_RULES = [
    {"match": ["app/controllers/"], "context_level": "function", "base_confidence": 0.88,
     "notes": "rb:rails:controller", "confidence_adjusters": {"language_specificity_bonus": 0.1}},
    {"match": ["app/models/"], "context_level": "file", "base_confidence": 0.88,
     "notes": "rb:rails:model", "confidence_adjusters": {"language_specificity_bonus": 0.1}},
    {"match": ["app/views/"], "context_level": "file", "base_confidence": 0.82,
     "notes": "rb:rails:view", "confidence_adjusters": {"language_specificity_bonus": 0.1}},
    {"match": ["db/migrate/"], "context_level": "file", "base_confidence": 0.9,
     "notes": "rb:rails:migration", "confidence_adjusters": {"language_specificity_bonus": 0.1}},
]


class RubyRuleHandler(RuleHandler):
    def __init__(self):
        super().__init__(language="ruby")
        self._rails_patterns = RUBY_RAILS_PATTERNS
        self._framework_path_rules = RUBY_FRAMEWORK_PATH_RULES

    def _detect_rails_patterns(self, content: str) -> List[Dict[str, Any]]:
        matched = []
        for name, cfg in self._rails_patterns.items():
            for p in cfg.get("patterns", []):
                if re.search(p, content):
                    matched.append({"pattern_name": name, "risk": cfg.get("risk", "medium"),
                                    "context_level": cfg.get("context_level", "function"),
                                    "notes": cfg.get("notes", f"rb:rails:{name}")})
                    break
        matched.sort(key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.get("risk"), 2))
        return matched

    def _get_rails_suggestion(self, patterns: List[Dict[str, Any]], unit: Unit) -> Optional[RuleSuggestion]:
        if not patterns:
            return None
        p = patterns[0]
        rule = {"base_confidence": 0.85, "confidence_adjusters": {"language_specificity_bonus": 0.1},
                "risk_level": p.get("risk", "medium")}
        return RuleSuggestion(context_level=p.get("context_level", "function"),
                              confidence=self._calculate_confidence(rule, unit),
                              notes=f"rb:rails:{','.join(x['pattern_name'] for x in patterns)}")

    def _apply_bonus(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        r = rule.copy()
        adj = r.get("confidence_adjusters", {}).copy()
        adj.setdefault("language_specificity_bonus", DEFAULT_LANGUAGE_SPECIFICITY_BONUS)
        r["confidence_adjusters"] = adj
        return r


    def match(self, unit: Unit) -> Optional[RuleSuggestion]:
        file_path = str(unit.get("file_path", "")).lower()
        original_file_path = str(unit.get("file_path", ""))  # Keep original for scanner
        metrics = unit.get("metrics", {}) or {}
        tags = set(unit.get("tags", []) or [])
        symbol = unit.get("symbol") or {}
        sym_name = symbol.get("name", "").lower() if isinstance(symbol, dict) else ""
        diff_content = unit.get("diff_content", "") or unit.get("content", "") or ""

        # 执行扫描器获取问题列表（Requirements 1.5, 3.4, 3.5）
        scanner_issues = self._scan_file(original_file_path, diff_content) if original_file_path else []

        if diff_content:
            rails_patterns = self._detect_rails_patterns(diff_content)
            if rails_patterns:
                s = self._get_rails_suggestion(rails_patterns, unit)
                if s:
                    # 应用扫描器结果到建议（Requirements 3.5）
                    return self._apply_scanner_results(s, scanner_issues)

        fm = self._match_path_rules(file_path, self._framework_path_rules, unit)
        if fm:
            return self._apply_scanner_results(fm, scanner_issues)

        path_rules = self._get_language_config("path_rules", [])
        pm = self._match_path_rules(file_path, [self._apply_bonus(r) for r in path_rules], unit)
        if pm:
            return self._apply_scanner_results(pm, scanner_issues)

        sym_rules = self._get_language_config("symbol_rules", [])
        if symbol:
            sm = self._match_symbol_rules(symbol, [self._apply_bonus(r) for r in sym_rules], unit)
            if sm:
                return self._apply_scanner_results(sm, scanner_issues)

        metric_rules = self._get_language_config("metric_rules", [])
        mm = self._match_metric_rules(metrics, [self._apply_bonus(r) for r in metric_rules], unit)
        if mm:
            return self._apply_scanner_results(mm, scanner_issues)

        keywords = self._get_language_config("keywords", [])
        keywords.extend(self._get_base_config("security_keywords", []))
        haystack = self._build_haystack(file_path, sym_name, tags)
        km = self._match_keywords(haystack, keywords, unit, note_prefix="lang_rb:kw:")
        if km:
            return self._apply_scanner_results(km, scanner_issues)

        if diff_content:
            patterns = _detect_patterns(diff_content, file_path)
            if patterns:
                p = patterns[0]
                rule = {"base_confidence": 0.5, "confidence_adjusters": {"rule_specificity": 0.05},
                        "risk_level": p.get("risk", "medium")}
                pattern_suggestion = RuleSuggestion(context_level=p.get("context_level", "function"),
                                      confidence=self._calculate_confidence(rule, unit),
                                      notes=f"rb:{_patterns_to_notes(patterns)}")
                return self._apply_scanner_results(pattern_suggestion, scanner_issues)

        default_suggestion = RuleSuggestion(context_level="function",
                              confidence=self._calculate_confidence({"base_confidence": 0.35}, unit),
                              notes="rb:default_fallback")
        return self._apply_scanner_results(default_suggestion, scanner_issues)

__all__ = ["RubyRuleHandler", "RUBY_RAILS_PATTERNS", "RUBY_FRAMEWORK_PATH_RULES"]
