"""Python 规则：按路径/关键词给出上下文建议。

优化内容（Requirements 6.1, 6.2, 6.5）：
- 添加装饰器模式识别（@decorator）
- 优化 Django/Flask/FastAPI 相关规则
- 添加 language_specificity_bonus 加成
- 预编译正则表达式提升性能
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Pattern

from Agent.DIFF.rule.rule_base import (
    RuleHandler, 
    RuleSuggestion,
    _detect_patterns,
    _patterns_to_notes,
    _analyze_symbols,  
)

Unit = Dict[str, Any]

# Python 装饰器模式定义（原始字符串模式）
_PYTHON_DECORATOR_PATTERNS_RAW: Dict[str, Dict[str, Any]] = {
    # Django 装饰器
    "django_view": {
        "patterns": [r"@login_required", r"@permission_required", r"@require_http_methods", 
                     r"@csrf_exempt", r"@csrf_protect", r"@cache_page", r"@vary_on_cookie"],
        "risk": "high",
        "context_level": "function",
        "notes": "py:decorator:django_view",
        "framework": "django",
    },
    "django_model": {
        "patterns": [r"@property", r"@cached_property", r"@classmethod", r"@staticmethod",
                     r"@receiver", r"@transaction\.atomic"],
        "risk": "medium",
        "context_level": "function",
        "notes": "py:decorator:django_model",
        "framework": "django",
    },
    # Flask 装饰器
    "flask_route": {
        "patterns": [r"@app\.route", r"@blueprint\.route", r"@bp\.route", 
                     r"@.*\.before_request", r"@.*\.after_request", r"@.*\.errorhandler"],
        "risk": "high",
        "context_level": "function",
        "notes": "py:decorator:flask_route",
        "framework": "flask",
    },
    # FastAPI 装饰器
    "fastapi_route": {
        "patterns": [r"@app\.get", r"@app\.post", r"@app\.put", r"@app\.delete", r"@app\.patch",
                     r"@router\.get", r"@router\.post", r"@router\.put", r"@router\.delete",
                     r"@.*\.on_event", r"@.*\.middleware"],
        "risk": "high",
        "context_level": "function",
        "notes": "py:decorator:fastapi_route",
        "framework": "fastapi",
    },
    # 通用 Python 装饰器
    "async_decorator": {
        "patterns": [r"@asyncio\.coroutine", r"@async_generator", r"@contextmanager",
                     r"@asynccontextmanager"],
        "risk": "medium",
        "context_level": "function",
        "notes": "py:decorator:async",
        "framework": "python",
    },
    "test_decorator": {
        "patterns": [r"@pytest\.", r"@mock\.", r"@patch", r"@unittest\.", r"@fixture"],
        "risk": "low",
        "context_level": "function",
        "notes": "py:decorator:test",
        "framework": "pytest",
    },
    "celery_task": {
        "patterns": [r"@app\.task", r"@shared_task", r"@celery\.task", r"@task"],
        "risk": "high",
        "context_level": "function",
        "notes": "py:decorator:celery_task",
        "framework": "celery",
    },
    "pydantic_validator": {
        "patterns": [r"@validator", r"@root_validator", r"@field_validator", 
                     r"@model_validator", r"@computed_field"],
        "risk": "medium",
        "context_level": "function",
        "notes": "py:decorator:pydantic",
        "framework": "pydantic",
    },
}


def _compile_decorator_patterns() -> Dict[str, Dict[str, Any]]:
    """预编译装饰器正则表达式，提升性能。"""
    compiled: Dict[str, Dict[str, Any]] = {}
    for name, config in _PYTHON_DECORATOR_PATTERNS_RAW.items():
        compiled[name] = {
            **config,
            "compiled_patterns": [
                re.compile(p, re.IGNORECASE) for p in config.get("patterns", [])
            ],
        }
    return compiled


# 预编译的装饰器模式（模块加载时编译一次）
PYTHON_DECORATOR_PATTERNS: Dict[str, Dict[str, Any]] = _compile_decorator_patterns()

# Python 框架特定路径规则
PYTHON_FRAMEWORK_PATH_RULES: List[Dict[str, Any]] = [
    # Django
    {
        "match": ["admin.py"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "py:django:admin",
        "framework": "django",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["models.py", "models/"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "py:django:models",
        "framework": "django",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["forms.py", "forms/"],
        "context_level": "function",
        "base_confidence": 0.82,
        "notes": "py:django:forms",
        "framework": "django",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["signals.py"],
        "context_level": "file",
        "base_confidence": 0.85,
        "notes": "py:django:signals",
        "framework": "django",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    # Flask
    {
        "match": ["routes.py", "routes/", "blueprints/"],
        "context_level": "function",
        "base_confidence": 0.88,
        "notes": "py:flask:routes",
        "framework": "flask",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["extensions.py", "extensions/"],
        "context_level": "file",
        "base_confidence": 0.82,
        "notes": "py:flask:extensions",
        "framework": "flask",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    # FastAPI
    {
        "match": ["routers/", "endpoints/", "api/"],
        "context_level": "function",
        "base_confidence": 0.88,
        "notes": "py:fastapi:routers",
        "framework": "fastapi",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["schemas.py", "schemas/"],
        "context_level": "function",
        "base_confidence": 0.82,
        "notes": "py:fastapi:schemas",
        "framework": "fastapi",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["dependencies.py", "deps.py"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "py:fastapi:dependencies",
        "framework": "fastapi",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
]

# 默认的 language_specificity_bonus
DEFAULT_LANGUAGE_SPECIFICITY_BONUS = 0.1


class PythonRuleHandler(RuleHandler):
    """Python 语言规则处理器
    
    优化内容：
    - 装饰器模式识别
    - Django/Flask/FastAPI 框架规则
    - language_specificity_bonus 加成
    """
    
    def __init__(self):
        super().__init__(language="python")
        self._decorator_patterns = PYTHON_DECORATOR_PATTERNS
        self._framework_path_rules = PYTHON_FRAMEWORK_PATH_RULES
    
    def _detect_decorators(self, content: str) -> List[Dict[str, Any]]:
        """检测代码中的装饰器模式
        
        使用预编译的正则表达式提升性能。
        
        Args:
            content: 代码内容（diff 内容或源代码）
            
        Returns:
            匹配的装饰器模式列表
        """
        matched_decorators: List[Dict[str, Any]] = []
        
        for decorator_name, decorator_config in self._decorator_patterns.items():
            # 使用预编译的正则表达式
            compiled_patterns = decorator_config.get("compiled_patterns", [])
            raw_patterns = decorator_config.get("patterns", [])
            matched_patterns: List[str] = []
            
            for i, compiled_pattern in enumerate(compiled_patterns):
                if compiled_pattern.search(content):
                    # 记录原始模式字符串用于日志
                    matched_patterns.append(raw_patterns[i] if i < len(raw_patterns) else str(compiled_pattern.pattern))
            
            if matched_patterns:
                matched_decorators.append({
                    "decorator_name": decorator_name,
                    "risk": decorator_config.get("risk", "medium"),
                    "context_level": decorator_config.get("context_level", "function"),
                    "notes": decorator_config.get("notes", f"py:decorator:{decorator_name}"),
                    "framework": decorator_config.get("framework", "python"),
                    "matched_patterns": matched_patterns,
                })
        
        # 按风险等级排序
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        matched_decorators.sort(key=lambda x: risk_order.get(x.get("risk", "medium"), 2))
        
        return matched_decorators
    
    def _get_decorator_suggestion(self, decorators: List[Dict[str, Any]], unit: Unit) -> Optional[RuleSuggestion]:
        """根据装饰器模式生成建议
        
        Args:
            decorators: 匹配的装饰器列表
            unit: 变更单元
            
        Returns:
            RuleSuggestion 或 None
        """
        if not decorators:
            return None
        
        # 使用风险最高的装饰器
        highest_risk_decorator = decorators[0]
        
        # 构建规则用于置信度计算
        rule = {
            "base_confidence": 0.85,  # 装饰器匹配给予较高基础置信度
            "confidence_adjusters": {
                "rule_specificity": 0.1,
                "language_specificity_bonus": DEFAULT_LANGUAGE_SPECIFICITY_BONUS,
            },
            "risk_level": highest_risk_decorator.get("risk", "medium"),
        }
        
        confidence = self._calculate_confidence(rule, unit)
        
        # 构建 notes
        decorator_names = [d.get("decorator_name", "") for d in decorators]
        notes = f"py:decorator:{','.join(decorator_names)}"
        
        # 添加框架信息
        frameworks = set(d.get("framework", "") for d in decorators if d.get("framework"))
        if frameworks:
            notes += f";frameworks:{','.join(frameworks)}"
        
        return RuleSuggestion(
            context_level=highest_risk_decorator.get("context_level", "function"),
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
        
        # 获取 diff 内容用于装饰器检测
        diff_content = unit.get("diff_content", "") or unit.get("content", "") or ""
        
        # 1. 检测装饰器模式（Requirements 6.5）
        if diff_content:
            decorators = self._detect_decorators(diff_content)
            if decorators:
                decorator_suggestion = self._get_decorator_suggestion(decorators, unit)
                if decorator_suggestion:
                    return decorator_suggestion
        
        # 2. 匹配框架特定路径规则（Django/Flask/FastAPI）
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
            # 添加基于符号分析的依赖提示（Requirements 8.1, 8.2, 8.3, 8.4）
            symbol_analysis = _analyze_symbols(unit)
            dependency_hints = symbol_analysis.get_dependency_hints()
            if dependency_hints:
                existing_requests = list(metric_match.extra_requests) if metric_match.extra_requests else []
                for hint in dependency_hints:
                    if not any(r.get("type") == hint.get("type") for r in existing_requests):
                        existing_requests.append(hint)
                return RuleSuggestion(
                    context_level=metric_match.context_level,
                    confidence=metric_match.confidence,
                    notes=metric_match.notes,
                    extra_requests=existing_requests,
                )
            return metric_match

        # 6. 从配置加载关键词
        keywords = self._get_language_config("keywords", [])
        # 添加基础安全关键词
        keywords.extend(self._get_base_config("security_keywords", []))
        haystack = self._build_haystack(file_path, sym_name, tags)
        keyword_match = self._match_keywords(haystack, keywords, unit, note_prefix="lang_py:kw:")
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
                    notes=f"py:{pattern_notes}",
                )

        # 8. 默认返回：如果没有匹配到任何规则，返回低置信度的默认建议
        # 使用 "function" 而非 "unknown"，确保每个变更单元都有明确的审查策略
        # confidence 在 0.3-0.45 范围内（Requirements 7.1, 7.2）
        symbol_analysis = _analyze_symbols(unit)
        extra_requests = symbol_analysis.get_dependency_hints()
        
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
            notes="py:default_fallback",
            extra_requests=extra_requests if extra_requests else [],
        )


__all__ = ["PythonRuleHandler", "PYTHON_DECORATOR_PATTERNS", "PYTHON_FRAMEWORK_PATH_RULES"]
