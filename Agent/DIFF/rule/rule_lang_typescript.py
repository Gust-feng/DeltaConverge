"""TypeScript/JavaScript 规则：按路径/关键词给出上下文建议。

优化内容（Requirements 6.1, 6.2, 6.6）：
- 添加 React Hooks 模式识别（use* 函数）
- 优化 Next.js/Prisma 相关规则
- 添加 language_specificity_bonus 加成
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from Agent.DIFF.rule.rule_base import (
    RuleHandler, 
    RuleSuggestion,
    _detect_patterns,
    _patterns_to_notes,
)

Unit = Dict[str, Any]

# React Hooks 模式定义
REACT_HOOKS_PATTERNS: Dict[str, Dict[str, Any]] = {
    # 内置 Hooks
    "state_hooks": {
        "patterns": [r"\buseState\b", r"\buseReducer\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "ts:hook:state",
        "category": "state",
    },
    "effect_hooks": {
        "patterns": [r"\buseEffect\b", r"\buseLayoutEffect\b", r"\buseInsertionEffect\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "ts:hook:effect",
        "category": "effect",
    },
    "ref_hooks": {
        "patterns": [r"\buseRef\b", r"\buseImperativeHandle\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "ts:hook:ref",
        "category": "ref",
    },
    "context_hooks": {
        "patterns": [r"\buseContext\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "ts:hook:context",
        "category": "context",
    },
    "memo_hooks": {
        "patterns": [r"\buseMemo\b", r"\buseCallback\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "ts:hook:memo",
        "category": "performance",
    },
    # 自定义 Hooks（以 use 开头的函数）
    "custom_hooks": {
        "patterns": [r"\buse[A-Z][a-zA-Z]*\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "ts:hook:custom",
        "category": "custom",
    },
    # React Query / TanStack Query Hooks
    "query_hooks": {
        "patterns": [r"\buseQuery\b", r"\buseMutation\b", r"\buseInfiniteQuery\b",
                     r"\buseQueryClient\b", r"\buseSuspenseQuery\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "ts:hook:query",
        "category": "data-fetching",
    },
    # SWR Hooks
    "swr_hooks": {
        "patterns": [r"\buseSWR\b", r"\buseSWRMutation\b", r"\buseSWRInfinite\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "ts:hook:swr",
        "category": "data-fetching",
    },
    # Next.js Hooks
    "nextjs_hooks": {
        "patterns": [r"\buseRouter\b", r"\busePathname\b", r"\buseSearchParams\b",
                     r"\buseParams\b", r"\buseSelectedLayoutSegment\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "ts:hook:nextjs",
        "category": "routing",
    },
    # Form Hooks
    "form_hooks": {
        "patterns": [r"\buseForm\b", r"\buseFormContext\b", r"\buseFieldArray\b",
                     r"\buseWatch\b", r"\buseController\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "ts:hook:form",
        "category": "form",
    },
}

# TypeScript/JavaScript 框架特定路径规则
TYPESCRIPT_FRAMEWORK_PATH_RULES: List[Dict[str, Any]] = [
    # Next.js App Router
    {
        "match": ["app/page.tsx", "app/page.ts", "app/page.jsx", "app/page.js"],
        "context_level": "file",
        "base_confidence": 0.9,
        "notes": "ts:nextjs:page",
        "framework": "nextjs",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["app/layout.tsx", "app/layout.ts", "app/layout.jsx", "app/layout.js"],
        "context_level": "file",
        "base_confidence": 0.92,
        "notes": "ts:nextjs:layout",
        "framework": "nextjs",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["app/loading.tsx", "app/error.tsx", "app/not-found.tsx"],
        "context_level": "file",
        "base_confidence": 0.85,
        "notes": "ts:nextjs:special_page",
        "framework": "nextjs",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["app/api/", "pages/api/"],
        "context_level": "function",
        "base_confidence": 0.92,
        "notes": "ts:nextjs:api_route",
        "framework": "nextjs",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1, "security_sensitive": 0.1},
    },
    # Next.js Pages Router
    {
        "match": ["pages/", "pages/_app", "pages/_document"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "ts:nextjs:pages",
        "framework": "nextjs",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # Prisma
    {
        "match": ["prisma/schema.prisma"],
        "context_level": "file",
        "base_confidence": 0.95,
        "notes": "ts:prisma:schema",
        "framework": "prisma",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["prisma/migrations/"],
        "context_level": "file",
        "base_confidence": 0.9,
        "notes": "ts:prisma:migration",
        "framework": "prisma",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["prisma/seed.ts", "prisma/seed.js"],
        "context_level": "file",
        "base_confidence": 0.85,
        "notes": "ts:prisma:seed",
        "framework": "prisma",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # React Components
    {
        "match": ["components/", "src/components/"],
        "context_level": "function",
        "base_confidence": 0.82,
        "notes": "ts:react:component",
        "framework": "react",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["hooks/", "src/hooks/"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "ts:react:hooks",
        "framework": "react",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # State Management
    {
        "match": ["store/", "stores/", "src/store/", "src/stores/"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "ts:state:store",
        "framework": "state-management",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["redux/", "src/redux/", "slices/"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "ts:redux:slice",
        "framework": "redux",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # tRPC
    {
        "match": ["trpc/", "server/trpc/", "src/trpc/"],
        "context_level": "function",
        "base_confidence": 0.9,
        "notes": "ts:trpc:router",
        "framework": "trpc",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
]

# 默认的 language_specificity_bonus
DEFAULT_LANGUAGE_SPECIFICITY_BONUS = 0.1


class TypeScriptRuleHandler(RuleHandler):
    """TypeScript/JavaScript 语言规则处理器
    
    优化内容：
    - React Hooks 模式识别
    - Next.js/Prisma 框架规则
    - language_specificity_bonus 加成
    """
    
    def __init__(self):
        super().__init__(language="typescript")
        self._hooks_patterns = REACT_HOOKS_PATTERNS
        self._framework_path_rules = TYPESCRIPT_FRAMEWORK_PATH_RULES
    
    def _detect_react_hooks(self, content: str) -> List[Dict[str, Any]]:
        """检测代码中的 React Hooks 模式
        
        Args:
            content: 代码内容（diff 内容或源代码）
            
        Returns:
            匹配的 Hooks 模式列表
        """
        matched_hooks: List[Dict[str, Any]] = []
        
        for hook_name, hook_config in self._hooks_patterns.items():
            patterns = hook_config.get("patterns", [])
            matched_patterns: List[str] = []
            
            for pattern in patterns:
                if re.search(pattern, content):
                    matched_patterns.append(pattern)
            
            if matched_patterns:
                matched_hooks.append({
                    "hook_name": hook_name,
                    "risk": hook_config.get("risk", "medium"),
                    "context_level": hook_config.get("context_level", "function"),
                    "notes": hook_config.get("notes", f"ts:hook:{hook_name}"),
                    "category": hook_config.get("category", "custom"),
                    "matched_patterns": matched_patterns,
                })
        
        # 按风险等级排序
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        matched_hooks.sort(key=lambda x: risk_order.get(x.get("risk", "medium"), 2))
        
        return matched_hooks
    
    def _get_hooks_suggestion(self, hooks: List[Dict[str, Any]], unit: Unit) -> Optional[RuleSuggestion]:
        """根据 Hooks 模式生成建议
        
        Args:
            hooks: 匹配的 Hooks 列表
            unit: 变更单元
            
        Returns:
            RuleSuggestion 或 None
        """
        if not hooks:
            return None
        
        # 使用风险最高的 Hook
        highest_risk_hook = hooks[0]
        
        # 构建规则用于置信度计算
        rule = {
            "base_confidence": 0.82,  # Hooks 匹配给予较高基础置信度
            "confidence_adjusters": {
                "rule_specificity": 0.1,
                "language_specificity_bonus": DEFAULT_LANGUAGE_SPECIFICITY_BONUS,
            },
            "risk_level": highest_risk_hook.get("risk", "medium"),
        }
        
        confidence = self._calculate_confidence(rule, unit)
        
        # 构建 notes
        hook_names = [h.get("hook_name", "") for h in hooks]
        notes = f"ts:hooks:{','.join(hook_names)}"
        
        # 添加类别信息
        categories = set(h.get("category", "") for h in hooks if h.get("category"))
        if categories:
            notes += f";categories:{','.join(categories)}"
        
        return RuleSuggestion(
            context_level=highest_risk_hook.get("context_level", "function"),
            confidence=confidence,
            notes=notes,
        )
    
    def _match_framework_path_rules(self, file_path: str, unit: Unit) -> Optional[RuleSuggestion]:
        """匹配框架特定的路径规则
        
        Args:
            file_path: 文件路径
            unit: 变更单元
            
        Returns:
            RuleSuggestion 或 None
        """
        return self._match_path_rules(file_path, self._framework_path_rules, unit)
    
    def _apply_language_specificity_bonus(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """应用语言特定加成
        
        Args:
            rule: 原始规则
            
        Returns:
            添加了语言特定加成的规则
        """
        enhanced_rule = rule.copy()
        adjusters = enhanced_rule.get("confidence_adjusters", {}).copy()
        
        # 添加语言特定加成
        if "language_specificity_bonus" not in adjusters:
            adjusters["language_specificity_bonus"] = DEFAULT_LANGUAGE_SPECIFICITY_BONUS
        
        enhanced_rule["confidence_adjusters"] = adjusters
        return enhanced_rule
    
    def match(self, unit: Unit) -> Optional[RuleSuggestion]:
        file_path = str(unit.get("file_path", "")).lower()
        metrics = unit.get("metrics", {}) or {}
        total_changed = self._total_changed(metrics)
        tags = set(unit.get("tags", []) or [])
        symbol = unit.get("symbol") or {}
        sym_name = symbol.get("name", "").lower() if isinstance(symbol, dict) else ""
        
        # 获取 diff 内容用于 Hooks 检测
        diff_content = unit.get("diff_content", "") or unit.get("content", "") or ""
        
        # 1. 检测 React Hooks 模式（Requirements 6.6）
        if diff_content:
            hooks = self._detect_react_hooks(diff_content)
            if hooks:
                hooks_suggestion = self._get_hooks_suggestion(hooks, unit)
                if hooks_suggestion:
                    return hooks_suggestion
        
        # 2. 匹配框架特定路径规则（Next.js/Prisma）
        framework_match = self._match_framework_path_rules(file_path, unit)
        if framework_match:
            return framework_match
        
        # 3. 从配置加载路径规则
        path_rules = self._get_language_config("path_rules", [])
        # 应用语言特定加成
        enhanced_path_rules = [self._apply_language_specificity_bonus(r) for r in path_rules]
        path_match = self._match_path_rules(file_path, enhanced_path_rules, unit)
        if path_match:
            return path_match

        # 4. 从配置加载符号规则
        sym_rules = self._get_language_config("symbol_rules", [])
        if symbol:
            # 应用语言特定加成
            enhanced_sym_rules = [self._apply_language_specificity_bonus(r) for r in sym_rules]
            sym_match = self._match_symbol_rules(symbol, enhanced_sym_rules, unit)
            if sym_match:
                return sym_match

        # 5. 从配置加载度量规则
        metric_rules = self._get_language_config("metric_rules", [])
        # 应用语言特定加成
        enhanced_metric_rules = [self._apply_language_specificity_bonus(r) for r in metric_rules]
        metric_match = self._match_metric_rules(metrics, enhanced_metric_rules, unit)
        if metric_match:
            return metric_match

        # 6. 从配置加载关键词
        keywords = self._get_language_config("keywords", [])
        # 添加基础安全关键词
        keywords.extend(self._get_base_config("security_keywords", []))
        haystack = self._build_haystack(file_path, sym_name, tags)
        keyword_match = self._match_keywords(haystack, keywords, unit, note_prefix="lang_ts:kw:")
        if keyword_match:
            return keyword_match

        # 7. 检测变更模式
        if diff_content:
            patterns = _detect_patterns(diff_content, file_path)
            if patterns:
                highest_risk_pattern = patterns[0]
                pattern_notes = _patterns_to_notes(patterns)
                
                rule = {
                    "base_confidence": 0.5,
                    "confidence_adjusters": {
                        "rule_specificity": 0.05,
                    },
                    "risk_level": highest_risk_pattern.get("risk", "medium"),
                }
                
                return RuleSuggestion(
                    context_level=highest_risk_pattern.get("context_level", "function"),
                    confidence=self._calculate_confidence(rule, unit),
                    notes=f"ts:{pattern_notes}",
                )

        # 8. 默认返回：如果没有匹配到任何规则，返回低置信度的默认建议
        # 使用 "function" 而非 "unknown"，确保每个变更单元都有明确的审查策略
        # confidence 在 0.3-0.45 范围内（Requirements 7.1, 7.2）
        return RuleSuggestion(
            context_level="function",
            confidence=self._calculate_confidence({
                "base_confidence": 0.35,
                "confidence_adjusters": {
                    "file_size": 0.0,
                    "change_type": 0.0,
                    "security_sensitive": 0.0,
                    "rule_specificity": 0.0
                }
            }, unit),
            notes="ts:default_fallback",
        )


__all__ = ["TypeScriptRuleHandler", "REACT_HOOKS_PATTERNS", "TYPESCRIPT_FRAMEWORK_PATH_RULES"]
