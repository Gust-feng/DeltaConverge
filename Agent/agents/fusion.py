"""融合规则层与 LLM 规划输出，生成最终的上下文计划。"""

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


def _is_high_risk(unit: Dict[str, Any]) -> bool:
    """判断规则侧的高置信/高风险单元，用于 planner 为空时的兜底。"""

    conf = float(unit.get("rule_confidence") or 0.0)
    if conf >= T_HIGH:
        return True
    tags = set(unit.get("tags") or [])
    return bool({"security_sensitive", "config_file", "routing_file"}.intersection(tags))


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

    # planner 未选中任何单元时，不再回退“全量”，只保留规则侧高置信/高风险兜底。
    selected_ids: set[str] = set(llm_by_id.keys())
    if not selected_ids:
        selected_ids = {
            unit_id for unit_id, unit in units.items() if _is_high_risk(unit)
        }

    # 如果 planner 选了部分单元，再补充遗漏的高风险单元（避免遗漏安全/配置文件）。
    if llm_by_id:
        for unit_id, unit in units.items():
            if unit_id not in selected_ids and _is_high_risk(unit):
                selected_ids.add(unit_id)

    for unit_id in selected_ids:
        unit = units.get(unit_id, {})
        rule_level = unit.get("rule_context_level") or "diff_only"
        rule_conf = float(unit.get("rule_confidence") or 0.0)

        llm_item = llm_by_id.get(unit_id, {})
        llm_level = llm_item.get("llm_context_level")
        llm_extra = llm_item.get("extra_requests") or llm_item.get("final_extra_requests") or []
        skip_review = bool(llm_item.get("skip_review", False))
        reason = llm_item.get("reason") or (
            "rule_high_confidence_fallback" if unit_id not in llm_by_id else None
        )

        # 规则层/LLM 上下文层级融合：高置信规则优先，低置信倾向采用 LLM 建议。
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

    # 其余未入选的单元显式标记为跳过，防止回退到旧版“全量上下文”。
    dropped_reason = "dropped_by_fusion_low_confidence"
    for unit_id, unit in units.items():
        if unit_id in selected_ids:
            continue
        rule_level = unit.get("rule_context_level") or "diff_only"
        rule_conf = float(unit.get("rule_confidence") or 0.0)
        fused_items.append(
            {
                "unit_id": unit_id,
                "rule_context_level": rule_level,
                "rule_confidence": rule_conf,
                "llm_context_level": None,
                "final_context_level": rule_level if rule_level != "unknown" else "diff_only",
                "extra_requests": [],
                "skip_review": True,
                "reason": dropped_reason,
            }
        )

    return {"plan": fused_items}


__all__ = ["fuse_plan", "T_HIGH", "T_LOW"]
