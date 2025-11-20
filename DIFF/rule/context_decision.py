"""Rule-based context decision layer for AI code review.

This module consumes structured change units (e.g. ReviewUnit/file_change)
and decides:

1. What context level to use: local / function / file.
2. Whether a future context-agent (LLM) should be involved.
"""

from __future__ import annotations

from typing import List, Literal, Optional, TypedDict


ContextLevel = Literal["local", "function", "file"]
PriorityLevel = Literal["low", "medium", "high"]
FocusKind = Literal["logic", "security", "performance", "style"]
ChangeType = Literal["add", "modify", "delete"]


class UnitSymbol(TypedDict, total=False):
    """Optional symbol-level information for a change unit."""

    kind: Literal["function", "method", "class", "block", "global"]
    name: str
    start_line: int
    end_line: int


class UnitMetrics(TypedDict):
    """Line-level metrics for a change unit."""

    added_lines: int
    removed_lines: int


class Unit(TypedDict):
    """Minimal shape of a review/change unit used by the rules."""

    file_path: str
    language: str
    change_type: ChangeType
    metrics: UnitMetrics
    tags: List[str]
    symbol: Optional[UnitSymbol]


class RuleSuggestion(TypedDict, total=False):
    """Initial rule-based suggestion for context selection."""

    context_level: Literal["local", "function", "file", "unknown"]
    confidence: float
    notes: str


class AgentDecision(TypedDict):
    """Final decision structure consumed by the context scheduler."""

    context_level: ContextLevel
    before_lines: int
    after_lines: int
    focus: List[FocusKind]
    priority: PriorityLevel
    reason: str


def _total_changed(metrics: UnitMetrics) -> int:
    """Return total changed lines based on metrics."""

    added = metrics.get("added_lines", 0)
    removed = metrics.get("removed_lines", 0)
    return int(added) + int(removed)


def build_rule_suggestion(unit: Unit) -> RuleSuggestion:
    """Build a rule-based suggestion for context level.

    Rules:
    - Small and simple changes → local.
    - Large changes → function/file.
    - Security-sensitive → function.
    - Medium changes inside a single function → function.
    - Otherwise → unknown.
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))
    file_path = unit.get("file_path", "")
    lower_path = file_path.lower()

    # 1) Extremely small and simple changes (safe to keep local).
    if total_changed <= 2:
        simple_tags = {"only_imports", "only_comments", "only_logging"}
        sensitive_keywords = ("auth", "security", "payment", "config")
        has_simple_tag = bool(simple_tags.intersection(tags))
        is_sensitive_path = any(keyword in lower_path for keyword in sensitive_keywords)

        if has_simple_tag and not is_sensitive_path:
            return {
                "context_level": "local",
                "confidence": 0.9,
                "notes": "rule: small_safe_change",
            }

    # 2) Very large changes.
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

    # 3) Explicitly security-sensitive code.
    if "security_sensitive" in tags:
        return {
            "context_level": "function",
            "confidence": 0.9,
            "notes": "rule: security_sensitive_change",
        }

    # 4) Medium changes, limited to a single function.
    if "in_single_function" in tags and 3 <= total_changed <= 15:
        if "security_sensitive" not in tags:
            return {
                "context_level": "function",
                "confidence": 0.8,
                "notes": "rule: medium_single_function_change",
            }

    # 5) Fallback – rules are unsure.
    return {"context_level": "unknown", "confidence": 0.0, "notes": "rule: unknown"}


def should_use_context_agent(unit: Unit, suggestion: RuleSuggestion) -> bool:
    """Decide whether a dedicated context agent should be invoked.

    The agent is used when:
    - Rules are uncertain (low confidence or unknown), and
    - The change is not trivially small or extremely large, and
    - It is not clearly security-sensitive.
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))

    context_level = suggestion.get("context_level", "unknown")
    confidence = float(suggestion.get("confidence", 0.0))

    # Rule is confident and explicit.
    if context_level != "unknown" and confidence >= 0.8:
        return False

    # Extremely small and simple – don't bother the agent.
    if total_changed <= 2 and {"only_imports", "only_comments"}.intersection(tags):
        return False

    # Very large change – always go with large context strategy.
    if total_changed >= 80:
        return False

    # Security-sensitive – better to stick with deterministic rule plan.
    if "security_sensitive" in tags:
        return False

    # Medium or ambiguous changes – let the agent decide.
    return True


def build_decision_from_rules(unit: Unit, suggestion: RuleSuggestion) -> AgentDecision:
    """Build final AgentDecision purely from rules.

    This is used when `should_use_context_agent` returns False or
    when the agent is not available.
    """

    metrics = unit.get("metrics", {"added_lines": 0, "removed_lines": 0})
    total_changed = _total_changed(metrics)
    tags = set(unit.get("tags", []))

    suggested_level = suggestion.get("context_level", "unknown")
    notes = suggestion.get("notes", "rule: unknown")

    # Default to function-level context if rules are unsure.
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
        # Ensure security is emphasized for sensitive changes.
        if "security_sensitive" in tags and "security" not in focus:
            focus.append("security")
        priority = "medium"
    else:  # context_level == "file"
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
    """Placeholder for future context agent integration.

    In the future, this will call a large language model to refine or
    override rule-based decisions based on the full change unit.
    """

    raise NotImplementedError("Context agent is not implemented yet.")


def decide_context(unit: Unit) -> AgentDecision:
    """Top-level entry for deciding review context for one change unit.

    Steps:
    1. Build a rule suggestion.
    2. Decide whether to use a context agent.
    3. If no agent is needed, return rule-based decision.
       Otherwise, delegate to the (future) context agent.
    """

    suggestion = build_rule_suggestion(unit)
    if not should_use_context_agent(unit, suggestion):
        return build_decision_from_rules(unit, suggestion)

    # For now this will raise NotImplementedError.
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

