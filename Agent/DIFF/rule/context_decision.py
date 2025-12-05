"""基于规则的上下文决策层（兼容/保留接口）。

说明：
- 主链路已改为“规则层 + 规划 LLM（上下文 Agent）+ 融合”：
  在 `Agent/agents/fusion.py` 内完成规则/LLM 计划融合，再由
  `Agent/agents/context_scheduler.py` 拉取上下文。
- 本模块仅保留规则侧的建议与决策数据结构，避免旧代码 import 失败。
- 兼容调用的 `decide_context` 现在只返回规则决策，不会再尝试调用未实现的
  context agent，以免产生 “context_agent_not_implemented” 的告警。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

from Agent.DIFF.rule.rule_config import get_rule_config, ConfigDefaults
from Agent.DIFF.rule.rule_registry import get_rule_handler
from Agent.DIFF.rule.rule_base import RuleSuggestion as RuleSuggestionObj

ContextLevel = Literal["local", "function", "file"]
PriorityLevel = Literal["low", "medium", "high"]
FocusKind = Literal["logic", "security", "performance", "style"]
ChangeType = Literal["add", "modify", "delete"]


class UnitSymbol(TypedDict, total=False):
    """变更单元的可选符号级信息。"""

    kind: Literal["function", "method", "class", "block", "global"]
    name: str
    start_line: int
    end_line: int


class UnitMetrics(TypedDict, total=False):
    """变更单元的行级指标。"""

    added_lines: int
    removed_lines: int
    hunk_count: int


class Unit(TypedDict):
    """规则使用的最小变更单元结构。"""

    file_path: str
    language: str
    change_type: ChangeType
    metrics: UnitMetrics
    tags: List[str]
    symbol: Optional[UnitSymbol]


class RuleSuggestion(TypedDict, total=False):
    """上下文选择的初始规则建议（输出契约）。
    
    注意：context_level 不再返回 "unknown"，而是使用 "function" 作为默认值。
    这确保每个变更单元都有明确的审查策略（Requirements 7.1, 7.2）。
    """

    context_level: Literal["local", "function", "file"]
    confidence: float
    notes: str
    extra_requests: List[Dict[str, Any]]


class AgentDecision(TypedDict):
    """提供给上下文调度器的最终决策结构。"""

    context_level: ContextLevel
    before_lines: int
    after_lines: int
    focus: List[FocusKind]
    priority: PriorityLevel
    reason: str


def _language_override_suggestion(unit: Unit) -> Optional[RuleSuggestion]:
    """按语言规则集提供更细的建议（命中则直接返回）。"""

    lang = str(unit.get("language", "")).lower()
    
    # 处理器实例可重用；构建一次并缓存。
    if not hasattr(_language_override_suggestion, "_handlers"):
        _language_override_suggestion._handlers = {}
    handlers = getattr(_language_override_suggestion, "_handlers")
    
    # 检查缓存中是否已有处理器实例
    if lang not in handlers:
        # 尝试获取处理器
        handler = get_rule_handler(lang)
        if not handler:
            # 为常见别名创建映射
            lang_aliases = {
                "py": "python",
                "ts": "typescript",
                "js": "javascript",
                "golang": "go"
            }
            # 尝试使用别名
            if lang in lang_aliases:
                handler = get_rule_handler(lang_aliases[lang])
        handlers[lang] = handler
    
    handler = handlers[lang]
    if not handler:
        return None
    
    try:
        suggestion_obj = handler.match(unit)
        if suggestion_obj is None:
            return None
        if isinstance(suggestion_obj, RuleSuggestionObj):
            return suggestion_obj.to_dict()
        return suggestion_obj  # type: ignore[return-value]
    except (AttributeError, TypeError, ValueError) as e:
        # 只捕获特定异常，避免隐藏所有错误
        print(f"Language override suggestion error: {e}")
        return None


def _total_changed(metrics: UnitMetrics) -> int:
    """基于指标返回变更行总数。"""

    added = metrics.get("added_lines", 0)
    removed = metrics.get("removed_lines", 0)
    return int(added) + int(removed)


def build_rule_suggestion(unit: Unit) -> RuleSuggestion:
    """构建上下文级别的规则化建议。

    Rules:
    - Small / 纯噪音 → local(diff_only) 高置信度。
    - 文档/轻量配置 → local(diff_only) 中高置信度。
    - 语言/路径特定规则优先命中，补充置信度/上下文级别。
    - 大改动 / 安全敏感 / 配置 → function/file 高置信度。
    - 单函数中等改动 → function 中置信度。
    - 其他 → unknown 低置信度。
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))
    file_path = unit.get("file_path", "")
    lower_path = file_path.lower()
    hunk_count = int(metrics.get("hunk_count", 1) or 1)
    cfg = get_rule_config()
    base_cfg = cfg.get("base") or {}
    large_change = int(base_cfg.get("large_change_lines", 80) or 80)
    moderate_change = int(base_cfg.get("moderate_change_lines", 20) or 20)
    simple_tags = set(base_cfg.get("noise_tags") or ["only_imports", "only_comments", "only_logging"])
    doc_tags = set(base_cfg.get("doc_tags") or ["doc_file"])
    config_keywords = [k.lower() for k in (base_cfg.get("config_keywords") or [])]
    security_keywords = [k.lower() for k in (base_cfg.get("security_keywords") or [])]
    
    # 处理symbol信息
    symbol = unit.get("symbol") or {}
    # 增强symbol处理，支持多种结构
    processed_symbol = symbol.copy() if isinstance(symbol, dict) else {}
    if "functions" in processed_symbol and processed_symbol["functions"]:
        func = processed_symbol["functions"][0]
        processed_symbol.update({
            "kind": "function",
            "name": func.get("name", ""),
            "start_line": func.get("start_line", 0),
            "end_line": func.get("end_line", 0)
        })
    elif "classes" in processed_symbol and processed_symbol["classes"]:
        cls = processed_symbol["classes"][0]
        processed_symbol.update({
            "kind": "class",
            "name": cls.get("name", ""),
            "start_line": cls.get("start_line", 0),
            "end_line": cls.get("end_line", 0)
        })
    
    sym_kind = processed_symbol.get("kind")
    sym_name = processed_symbol.get("name", "").lower()

    # 计算各种标志
    is_simple = bool(simple_tags.intersection(tags))
    is_doc = bool(doc_tags.intersection(tags))
    is_config_like = {"config_file", "routing_file"}.intersection(tags)
    is_security = "security_sensitive" in tags
    is_sensitive_path = any(keyword in lower_path for keyword in security_keywords)
    is_config_path = any(keyword in lower_path for keyword in config_keywords)

    # 文档/纯噪音/极小改动 → diff_only，高置信度
    if is_doc:
        return {
            "context_level": "local",
            "confidence": 0.9,
            "notes": "rule: doc_file_light",
        }
    if total_changed <= 2 and is_simple and not is_sensitive_path:
        return {
            "context_level": "local",
            "confidence": 0.9,
            "notes": "rule: small_safe_change",
        }
    if is_simple and total_changed <= 6 and not is_sensitive_path:
        return {
            "context_level": "local",
            "confidence": 0.88,
            "notes": "rule: simple_change",
        }

    # 语言/路径覆盖：命中即返回
    lang_suggestion = _language_override_suggestion(unit)
    if lang_suggestion:
        return lang_suggestion

    # 基于symbol的规则建议
    if sym_kind:
        # 测试函数/类 → function级别
        if sym_name and any(pattern in sym_name for pattern in ["test", "spec", "unit"]):
            return {
                "context_level": "function",
                "confidence": 0.8,
                "notes": "rule: symbol_test_function",
            }
        # 控制器/服务类 → file级别
        if sym_kind == "class" and any(pattern in sym_name for pattern in ["controller", "service", "manager"]):
            return {
                "context_level": "file",
                "confidence": 0.85,
                "notes": "rule: symbol_class_component",
            }
        # 主函数 → file级别
        if sym_name == "main":
            return {
                "context_level": "file",
                "confidence": 0.9,
                "notes": "rule: symbol_main_function",
            }

    # 小型配置/路由变更 → diff_only 中置信度
    # Requirements 8.3: 配置文件变更添加 search_config_usage 建议
    if (is_config_like or is_config_path) and total_changed <= 8 and not is_security:
        return {
            "context_level": "local",
            "confidence": 0.82,
            "notes": "rule: small_config_or_routing",
            "extra_requests": [{"type": "search_config_usage"}],
        }

    # 规模很大的改动。
    if total_changed >= large_change:
        # Requirements 8.3: 配置文件变更添加 search_config_usage 建议
        if {"config_file", "routing_file"}.intersection(tags) or is_config_path:
            return {
                "context_level": "file",
                "confidence": 0.92,
                "notes": "rule: large_change_config_or_routing",
                "extra_requests": [{"type": "search_config_usage"}],
            }
        return {
            "context_level": "function",
            "confidence": 0.9,
            "notes": "rule: large_change_function_scope",
        }

    # 明确的安全敏感代码。
    if is_security or is_sensitive_path:
        return {
            "context_level": "function",
            "confidence": 0.95,
            "notes": "rule: security_sensitive_change",
        }

    # 中等改动且限定在单个函数内。
    if "in_single_function" in tags and 3 <= total_changed <= moderate_change and hunk_count <= 2:
        if not is_security:
            return {
                "context_level": "function",
                "confidence": 0.8,
                "notes": "rule: medium_single_function_change",
            }
        return {
            "context_level": "function",
            "confidence": 0.78,
            "notes": "rule: medium_single_function_security",
        }

    # 兜底：规则无法确定时返回默认值（Requirements 7.1, 7.2, 7.3, 7.4）
    # 使用 "function" 而非 "unknown"，确保每个变更单元都有明确的审查策略
    # confidence 使用配置中的默认值，在 CONFIDENCE_MIN-CONFIDENCE_MAX 范围内
    return {
        "context_level": "function",
        "confidence": ConfigDefaults.CONFIDENCE_DEFAULT,
        "notes": "rule: default_fallback",
    }


def should_use_context_agent(unit: Unit, suggestion: RuleSuggestion) -> bool:
    """判断是否需要调用专用的上下文 Agent。

    使用 Agent 的情形：
    - 规则置信度低（< 0.8），且
    - 变更既不是微小也不是极大，且
    - 也非明显的安全敏感。
    
    注意：规则层现在不再返回 "unknown"，而是使用 "function" 作为默认值。
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))

    context_level = suggestion.get("context_level", "function")  # 默认值改为 "function"
    confidence = float(suggestion.get("confidence", 0.0))

    # 规则已明确且置信度高。
    if confidence >= ConfigDefaults.CONFIDENCE_HIGH:
        return False

    # 极小且简单的改动，无需调用 Agent。
    if total_changed <= 2 and {"only_imports", "only_comments"}.intersection(tags):
        return False

    # 非常大的改动，直接采用大上下文策略。
    if total_changed >= 80:
        return False

    # 安全敏感场景，保持确定性的规则方案。
    if "security_sensitive" in tags:
        return False

    # 中等或模糊的改动交给 Agent 判定。
    return True


def build_decision_from_rules(unit: Unit, suggestion: RuleSuggestion) -> AgentDecision:
    """仅依靠规则生成最终 AgentDecision。

    在 `should_use_context_agent` 返回 False 或 Agent 不可用时使用。
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))

    suggested_level = suggestion.get("context_level", "function")  # 默认值改为 "function"
    notes = suggestion.get("notes", "rule: default_fallback")

    # 直接使用建议的级别（规则层现在不再返回 "unknown"）
    context_level: ContextLevel = suggested_level  # type: ignore[assignment]

    before_lines: int
    after_lines: int
    focus: List[FocusKind]
    priority: PriorityLevel

    if context_level == "local":
        before_lines = after_lines = 5
        focus = ["style", "logic"]
        priority = "low" if total_changed <= 2 else "medium"
    elif context_level == "function":
        before_lines = after_lines = 8
        focus = ["logic", "security"]
        # 对安全敏感改动确保关注项包含安全。
        if "security_sensitive" in tags and "security" not in focus:
            focus.append("security")
        priority = "medium"
    else:  # 文件级上下文分支
        before_lines = after_lines = 10
        focus = ["logic", "security", "performance"]
        priority = "high"

    reason = f"decision from rules ({notes})"

    return {
        "context_level": context_level,
        "before_lines": before_lines,
        "after_lines": after_lines,
        "focus": focus,
        "priority": priority,
        "reason": reason,
    }


def call_context_agent(unit: Unit, suggestion: RuleSuggestion) -> AgentDecision:
    """兼容占位：为旧调用方返回规则决策，避免 NotImplemented 告警。"""

    return build_decision_from_rules(unit, suggestion)


def decide_context(unit: Unit) -> AgentDecision:
    """兼容入口：仅返回规则决策，不再调用上下文 Agent。

    主链路使用规划 LLM，请参见 Agent/agents/fusion.py。
    """

    suggestion = build_rule_suggestion(unit)
    return build_decision_from_rules(unit, suggestion)


__all__ = [
    "ContextLevel",
    "PriorityLevel",
    "FocusKind",
    "ChangeType",
    "UnitSymbol",
    "UnitMetrics",
    "Unit",
    "RuleSuggestion",
    "AgentDecision",
    "build_rule_suggestion",
    "should_use_context_agent",
    "build_decision_from_rules",
    "call_context_agent",
    "decide_context",
]
