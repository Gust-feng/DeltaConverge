"""Go 规则：按路径/关键词给出上下文建议。

优化内容（Requirements 6.1, 6.2, 6.7）：
- 添加 goroutine 和 channel 操作识别
- 优化 gin/echo 相关规则
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

# Go 并发模式定义
GO_CONCURRENCY_PATTERNS: Dict[str, Dict[str, Any]] = {
    # Goroutine 模式
    "goroutine_spawn": {
        "patterns": [r"\bgo\s+func\b", r"\bgo\s+\w+\("],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:goroutine",
        "category": "concurrency",
    },
    # Channel 操作
    "channel_create": {
        "patterns": [r"\bmake\s*\(\s*chan\b", r"\bchan\s+\w+"],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:channel_create",
        "category": "concurrency",
    },
    "channel_send": {
        "patterns": [r"\w+\s*<-\s*\w+", r"<-\s*\w+"],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:channel_send",
        "category": "concurrency",
    },
    "channel_receive": {
        "patterns": [r"\w+\s*:?=\s*<-\s*\w+"],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:channel_receive",
        "category": "concurrency",
    },
    # Select 语句
    "select_statement": {
        "patterns": [r"\bselect\s*\{"],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:select",
        "category": "concurrency",
    },
    # Sync 包
    "sync_mutex": {
        "patterns": [r"\bsync\.Mutex\b", r"\bsync\.RWMutex\b", r"\.Lock\(\)", r"\.Unlock\(\)", r"\.RLock\(\)", r"\.RUnlock\(\)"],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:mutex",
        "category": "concurrency",
    },
    "sync_waitgroup": {
        "patterns": [r"\bsync\.WaitGroup\b", r"\.Add\(\d+\)", r"\.Done\(\)", r"\.Wait\(\)"],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:waitgroup",
        "category": "concurrency",
    },
    "sync_once": {
        "patterns": [r"\bsync\.Once\b", r"\.Do\("],
        "risk": "medium",
        "context_level": "function",
        "notes": "go:concurrency:once",
        "category": "concurrency",
    },
    # Context 包
    "context_usage": {
        "patterns": [r"\bcontext\.Context\b", r"\bcontext\.Background\(\)", r"\bcontext\.TODO\(\)", 
                     r"\bcontext\.WithCancel\b", r"\bcontext\.WithTimeout\b", r"\bcontext\.WithDeadline\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "go:concurrency:context",
        "category": "concurrency",
    },
    # Atomic 操作
    "atomic_ops": {
        "patterns": [r"\batomic\.\w+", r"\bsync/atomic\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "go:concurrency:atomic",
        "category": "concurrency",
    },
}

# Go 框架特定路径规则
GO_FRAMEWORK_PATH_RULES: List[Dict[str, Any]] = [
    # Gin 框架
    {
        "match": ["handlers/", "handler/", "controllers/", "controller/"],
        "context_level": "function",
        "base_confidence": 0.88,
        "notes": "go:gin:handler",
        "framework": "gin",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["routes/", "router/", "routers/"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "go:gin:routes",
        "framework": "gin",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["middleware/", "middlewares/"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "go:gin:middleware",
        "framework": "gin",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # Echo 框架
    {
        "match": ["api/", "apis/"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "go:echo:api",
        "framework": "echo",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # 通用 Go 项目结构
    {
        "match": ["cmd/", "main.go"],
        "context_level": "file",
        "base_confidence": 0.85,
        "notes": "go:cmd:main",
        "framework": "go",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["internal/", "pkg/"],
        "context_level": "function",
        "base_confidence": 0.82,
        "notes": "go:pkg:internal",
        "framework": "go",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["models/", "model/", "entities/", "entity/"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "go:model",
        "framework": "go",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["repository/", "repositories/", "repo/"],
        "context_level": "function",
        "base_confidence": 0.88,
        "notes": "go:repository",
        "framework": "go",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["service/", "services/"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "go:service",
        "framework": "go",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # gRPC
    {
        "match": ["proto/", "pb/", ".pb.go"],
        "context_level": "file",
        "base_confidence": 0.9,
        "notes": "go:grpc:proto",
        "framework": "grpc",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # 测试文件
    {
        "match": ["_test.go"],
        "context_level": "function",
        "base_confidence": 0.75,
        "notes": "go:test",
        "framework": "go",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    # 配置文件（Requirements 8.3: 配置文件变更添加 search_config_usage 建议）
    {
        "match": ["config/", "configs/", ".yaml", ".yml", "config.go"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "go:config",
        "framework": "go",
        "extra_requests": [{"type": "search_config_usage"}],
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
]

# 默认的 language_specificity_bonus
DEFAULT_LANGUAGE_SPECIFICITY_BONUS = 0.1


class GoRuleHandler(RuleHandler):
    """Go 语言规则处理器
    
    优化内容：
    - goroutine 和 channel 操作识别
    - gin/echo 框架规则
    - language_specificity_bonus 加成
    """
    
    def __init__(self):
        super().__init__(language="go")
        self._concurrency_patterns = GO_CONCURRENCY_PATTERNS
        self._framework_path_rules = GO_FRAMEWORK_PATH_RULES
    
    def _detect_concurrency_patterns(self, content: str) -> List[Dict[str, Any]]:
        """检测代码中的并发模式（goroutine、channel 等）
        
        Args:
            content: 代码内容（diff 内容或源代码）
            
        Returns:
            匹配的并发模式列表
        """
        matched_patterns: List[Dict[str, Any]] = []
        
        for pattern_name, pattern_config in self._concurrency_patterns.items():
            patterns = pattern_config.get("patterns", [])
            matched_indicators: List[str] = []
            
            for pattern in patterns:
                if re.search(pattern, content):
                    matched_indicators.append(pattern)
            
            if matched_indicators:
                matched_patterns.append({
                    "pattern_name": pattern_name,
                    "risk": pattern_config.get("risk", "medium"),
                    "context_level": pattern_config.get("context_level", "function"),
                    "notes": pattern_config.get("notes", f"go:concurrency:{pattern_name}"),
                    "category": pattern_config.get("category", "concurrency"),
                    "matched_indicators": matched_indicators,
                })
        
        # 按风险等级排序
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        matched_patterns.sort(key=lambda x: risk_order.get(x.get("risk", "medium"), 2))
        
        return matched_patterns
    
    def _get_concurrency_suggestion(self, patterns: List[Dict[str, Any]], unit: Unit) -> Optional[RuleSuggestion]:
        """根据并发模式生成建议
        
        Args:
            patterns: 匹配的并发模式列表
            unit: 变更单元
            
        Returns:
            RuleSuggestion 或 None
        """
        if not patterns:
            return None
        
        # 使用风险最高的模式
        highest_risk_pattern = patterns[0]
        
        # 构建规则用于置信度计算
        # 并发代码风险高，给予较高基础置信度
        rule = {
            "base_confidence": 0.88,
            "confidence_adjusters": {
                "rule_specificity": 0.1,
                "language_specificity_bonus": DEFAULT_LANGUAGE_SPECIFICITY_BONUS,
            },
            "risk_level": highest_risk_pattern.get("risk", "high"),
        }
        
        confidence = self._calculate_confidence(rule, unit)
        
        # 构建 notes
        pattern_names = [p.get("pattern_name", "") for p in patterns]
        notes = f"go:concurrency:{','.join(pattern_names)}"
        
        return RuleSuggestion(
            context_level=highest_risk_pattern.get("context_level", "function"),
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
        
        # 获取 diff 内容用于并发模式检测
        diff_content = unit.get("diff_content", "") or unit.get("content", "") or ""
        
        # 1. 检测并发模式（goroutine、channel 等）（Requirements 6.7）
        if diff_content:
            concurrency_patterns = self._detect_concurrency_patterns(diff_content)
            if concurrency_patterns:
                concurrency_suggestion = self._get_concurrency_suggestion(concurrency_patterns, unit)
                if concurrency_suggestion:
                    return concurrency_suggestion
        
        # 2. 匹配框架特定路径规则（gin/echo）
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
        keyword_match = self._match_keywords(haystack, keywords, unit, note_prefix="lang_go:kw:")
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
                    notes=f"go:{pattern_notes}",
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
            notes="go:default_fallback",
        )


__all__ = ["GoRuleHandler", "GO_CONCURRENCY_PATTERNS", "GO_FRAMEWORK_PATH_RULES"]
