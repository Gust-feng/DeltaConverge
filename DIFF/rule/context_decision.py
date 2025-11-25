"""基于规则的上下文决策层。

本模块消费结构化的变更单元（如 ReviewUnit/file_change），并决定：

1. 采用何种上下文级别：local / function / file。
2. 是否需要调用未来的上下文 Agent（LLM）。"""

from __future__ import annotations

from typing import List, Literal, Optional, TypedDict


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
    """上下文选择的初始规则建议。"""

    context_level: Literal["local", "function", "file", "unknown"]
    confidence: float
    notes: str


class AgentDecision(TypedDict):
    """提供给上下文调度器的最终决策结构。"""

    context_level: ContextLevel
    before_lines: int
    after_lines: int
    focus: List[FocusKind]
    priority: PriorityLevel
    reason: str


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
    - 大改动 / 安全敏感 → function/file 高置信度。
    - 单函数中等改动 → function 中置信度。
    - 其他 → unknown 低置信度。
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))
    file_path = unit.get("file_path", "")
    lower_path = file_path.lower()
    hunk_count = int(metrics.get("hunk_count", 1) or 1)

    simple_tags = {"only_imports", "only_comments", "only_logging"}
    is_simple = bool(simple_tags.intersection(tags))
    is_doc = "doc_file" in tags
    is_config_like = {"config_file", "routing_file"}.intersection(tags)
    is_security = "security_sensitive" in tags
    sensitive_keywords = ("auth", "security", "payment", "config")
    is_sensitive_path = any(keyword in lower_path for keyword in sensitive_keywords)

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
            "confidence": 0.92,
            "notes": "rule: small_safe_change",
        }
    if is_simple and total_changed <= 5 and not is_sensitive_path:
        return {
            "context_level": "local",
            "confidence": 0.9,
            "notes": "rule: simple_change",
        }

    # 小型配置/路由变更 → diff_only 中置信度
    if is_config_like and total_changed <= 6 and not is_security:
        return {
            "context_level": "local",
            "confidence": 0.85,
            "notes": "rule: small_config_or_routing",
        }

    # 2) 规模很大的改动。
    if total_changed >= 80:
        if {"config_file", "routing_file"}.intersection(tags):
            return {
                "context_level": "file",
                "confidence": 0.9,
                "notes": "rule: large_change_config_or_routing",
            }
        return {
            "context_level": "function",
            "confidence": 0.9,
            "notes": "rule: large_change_function_scope",
        }

    # 3) 明确的安全敏感代码。
    if is_security:
        return {
            "context_level": "function",
            "confidence": 0.9,
            "notes": "rule: security_sensitive_change",
        }

    # 4) 中等改动且限定在单个函数内。
    if "in_single_function" in tags and 3 <= total_changed <= 20 and hunk_count <= 2:
        if not is_security:
            return {
                "context_level": "function",
                "confidence": 0.8,
                "notes": "rule: medium_single_function_change",
            }
        return {
            "context_level": "function",
            "confidence": 0.75,
            "notes": "rule: medium_single_function_security",
        }

    # 5) 兜底：规则无法确定。
    return {"context_level": "unknown", "confidence": 0.0, "notes": "rule: unknown"}


def should_use_context_agent(unit: Unit, suggestion: RuleSuggestion) -> bool:
    """判断是否需要调用专用的上下文 Agent。

    使用 Agent 的情形：
    - 规则不确定（低置信度或 unknown），且
    - 变更既不是微小也不是极大，且
    - 也非明显的安全敏感。
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))

    context_level = suggestion.get("context_level", "unknown")
    confidence = float(suggestion.get("confidence", 0.0))

    # 规则已明确且置信度高。
    if context_level != "unknown" and confidence >= 0.8:
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

    suggested_level = suggestion.get("context_level", "unknown")
    notes = suggestion.get("notes", "rule: unknown")

    # 规则不确定时默认采用函数级上下文。
    if suggested_level == "unknown":
        context_level: ContextLevel = "function"
    else:
        context_level = suggested_level  # type: ignore[assignment]

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
    """未来的上下文 Agent 集成占位。

    后续会调用大模型基于完整变更单元细化或覆盖规则决策。
    """

    raise NotImplementedError("Context agent is not implemented yet.")


def decide_context(unit: Unit) -> AgentDecision:
    """单个变更单元上下文选择的顶层入口。

    步骤：
    1. 构建规则建议；
    2. 判断是否需要上下文 Agent；
    3. 无需 Agent 时返回规则决策，否则交给（未来的）上下文 Agent。
    """

    suggestion = build_rule_suggestion(unit)
    if not should_use_context_agent(unit, suggestion):
        return build_decision_from_rules(unit, suggestion)

    # 目前会抛出 NotImplementedError。
    return call_context_agent(unit, suggestion)


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
