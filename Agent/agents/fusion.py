"""Fusion of rule-based and LLM planning outputs into a final context plan."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# 上下文深度枚举顺序
_CTX_ORDER = ["diff_only", "function", "file_context", "full_file"]

T_HIGH = 0.8
T_LOW = 0.5


def _ctx_rank(level: Optional[str]) -> int:
    try:
        return _CTX_ORDER.index(str(level))
    except Exception:
        return 0


def fuse_plan(review_index: Dict[str, Any], llm_plan: Dict[str, Any]) -> Dict[str, Any]:
    """融合规则层与 LLM 规划，生成最终上下文计划。

    Args:
        review_index: 原始元数据索引，需包含 units 列表（rule_context_level/rule_confidence）。
        llm_plan: 规划 Agent 输出的 JSON，对应 plan 数组。

    Returns:
        dict: {"plan": [...]}，每项包含 unit_id/final_context_level/extra_requests/skip_review/reason。
    """

    units = {u.get("unit_id"): u for u in review_index.get("units", [])}
    llm_items = llm_plan.get("plan", []) if isinstance(llm_plan, dict) else []
    llm_by_id = {
        item.get("unit_id"): item
        for item in llm_items
        if isinstance(item, dict) and item.get("unit_id") in units
    }

    fused_items: List[Dict[str, Any]] = []

    # 优先使用规划选中的单元，兜底补充高置信度规则单元，避免全量膨胀。
    ordered_ids: List[str] = list(llm_by_id.keys())
    for unit_id, unit in units.items():
        if unit_id not in ordered_ids and float(unit.get("rule_confidence") or 0.0) >= T_HIGH:
            ordered_ids.append(unit_id)
    if not ordered_ids:
        ordered_ids = list(units.keys())

    for unit_id in ordered_ids:
        unit = units.get(unit_id, {})
        rule_level = unit.get("rule_context_level") or "diff_only"
        rule_conf = float(unit.get("rule_confidence") or 0.0)

        llm_item = llm_by_id.get(unit_id, {})
        llm_level = llm_item.get("llm_context_level")
        llm_extra = llm_item.get("extra_requests") or llm_item.get("final_extra_requests") or []
        skip_review = bool(llm_item.get("skip_review", False))
        reason = llm_item.get("reason")

        # 规则层/LLM 上下文层级融合
        if rule_conf >= T_HIGH:
            final_level = llm_level if _ctx_rank(llm_level) > _ctx_rank(rule_level) else rule_level
        elif rule_conf <= T_LOW:
            final_level = llm_level or rule_level
        else:
            if _ctx_rank(llm_level) > _ctx_rank(rule_level):
                final_level = llm_level
            elif _ctx_rank(llm_level) < _ctx_rank(rule_level):
                final_level = rule_level
            else:
                final_level = llm_level or rule_level

        fused_items.append(
            {
                "unit_id": unit_id,
                "rule_context_level": rule_level,
                "rule_confidence": rule_conf,
                "llm_context_level": llm_level,
                "final_context_level": final_level,
                "extra_requests": llm_extra,
                "skip_review": skip_review,
                "reason": reason,
            }
        )

    return {"plan": fused_items}


__all__ = ["fuse_plan", "T_HIGH", "T_LOW"]
