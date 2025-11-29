"""融合规则层与 LLM 规划输出，生成最终的上下文计划。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from Agent.DIFF.rule.context_levels import ctx_rank

T_HIGH = 0.8
T_MEDIUM = 0.5
T_LOW = 0.3


def _is_high_risk(unit: Dict[str, Any]) -> bool:
    """判断规则侧的高置信/高风险单元，用于 planner 为空时的兜底。"""

    conf = float(unit.get("rule_confidence") or 0.0)
    if conf >= T_HIGH:
        return True
    tags = set(unit.get("tags") or [])
    return bool({"security_sensitive", "config_file", "routing_file"}.intersection(tags))


def _is_medium_risk(unit: Dict[str, Any]) -> bool:
    """判断规则侧的中等置信/中等风险单元。"""

    conf = float(unit.get("rule_confidence") or 0.0)
    if T_MEDIUM <= conf < T_HIGH:
        return True
    tags = set(unit.get("tags") or [])
    return bool({"in_single_function", "complete_function"}.intersection(tags))


def fuse_plan(review_index: Dict[str, Any], llm_plan: Dict[str, Any]) -> Dict[str, Any]:
    """融合规则层与 LLM 规划，生成最终上下文计划。

    Args:
        review_index: 原始元数据索引，需包含 units 列表（rule_context_level/rule_confidence）。
        llm_plan: 规划 Agent 输出的 JSON，对应 plan 数组。

    Returns:
        dict: {"plan": [...]}，每项包含 unit_id/final_context_level/extra_requests/skip_review/reason。
    """

    # 保留原始顺序，避免 dict 去重导致单元丢失或无序。
    units_list: List[Dict[str, Any]] = [
        u for u in review_index.get("units", []) if isinstance(u, dict)
    ]
    units_by_id: Dict[str, Dict[str, Any]] = {}
    for u in units_list:
        uid = u.get("unit_id") or u.get("id")
        if uid is None:
            continue
        units_by_id[str(uid)] = u

    llm_items = llm_plan.get("plan", []) if isinstance(llm_plan, dict) else []
    llm_by_id = {
        item.get("unit_id"): item
        for item in llm_items
        if isinstance(item, dict) and item.get("unit_id") in units_by_id
    }

    fused_items: List[Dict[str, Any]] = []

    # planner 未选中任何单元时，保留规则侧高置信/高风险/中等风险单元
    selected_ids: set[str] = set(llm_by_id.keys())
    if not selected_ids:
        selected_ids = {
            unit_id for unit_id, unit in units_by_id.items() 
            if _is_high_risk(unit) or _is_medium_risk(unit)
        }

    # 如果 planner 选了部分单元，再补充遗漏的高风险和中等风险单元
    if llm_by_id:
        for unit_id, unit in units_by_id.items():
            if unit_id not in selected_ids and (_is_high_risk(unit) or _is_medium_risk(unit)):
                selected_ids.add(unit_id)

    dropped_reason = "dropped_by_fusion_low_confidence"
    missing_id_reason = "dropped_missing_unit_id"

    for unit in units_list:
        uid_raw = unit.get("unit_id") or unit.get("id")
        unit_id = str(uid_raw) if uid_raw is not None else None
        rule_level = unit.get("rule_context_level") or "diff_only"
        rule_conf = float(unit.get("rule_confidence") or 0.0)

        if not unit_id:
            fused_items.append(
                {
                    "unit_id": None,
                    "rule_context_level": rule_level,
                    "rule_confidence": rule_conf,
                    "llm_context_level": None,
                    "final_context_level": rule_level if rule_level != "unknown" else "diff_only",
                    "extra_requests": [],
                    "skip_review": True,
                    "reason": missing_id_reason,
                }
            )
            continue

        llm_item = llm_by_id.get(unit_id, {})
        llm_level = llm_item.get("llm_context_level")
        llm_extra = llm_item.get("extra_requests") or llm_item.get("final_extra_requests") or []
        rule_extra = unit.get("rule_extra_requests") or []
        skip_review = bool(llm_item.get("skip_review", False))
        reason = llm_item.get("reason")

        if unit_id not in selected_ids:
            final_level = rule_level if rule_level != "unknown" else "diff_only"
            fused_items.append(
                {
                    "unit_id": unit_id,
                    "rule_context_level": rule_level,
                    "rule_confidence": rule_conf,
                    "llm_context_level": llm_level,
                    "final_context_level": final_level,
                    "extra_requests": [],
                    "skip_review": True,
                    "reason": dropped_reason,
                }
            )
            continue

        if reason is None and unit_id not in llm_by_id:
            if rule_conf >= T_HIGH:
                reason = "rule_high_confidence_fallback"
            elif T_MEDIUM <= rule_conf < T_HIGH:
                reason = "rule_medium_confidence_fallback"
            else:
                reason = "rule_low_confidence_fallback"

        # 规则层/LLM 上下文层级融合：高置信规则优先，低置信倾向采用 LLM 建议。
        if rule_conf >= T_HIGH:
            final_level = llm_level if ctx_rank(llm_level) > ctx_rank(rule_level) else rule_level
        elif rule_conf <= T_LOW:
            final_level = llm_level or rule_level
        else:
            # 中等置信度：根据上下文级别优先级决定
            if ctx_rank(llm_level) > ctx_rank(rule_level):
                final_level = llm_level
            elif ctx_rank(llm_level) < ctx_rank(rule_level):
                final_level = rule_level
            else:
                # 级别相同时，优先使用 LLM 建议
                final_level = llm_level or rule_level

        fused_items.append(
            {
                "unit_id": unit_id,
                "rule_context_level": rule_level,
                "rule_confidence": rule_conf,
                "llm_context_level": llm_level,
                "final_context_level": final_level,
                # 规则侧的 extra_requests 作为兜底提示；LLM 规划有则优先
                "extra_requests": llm_extra or rule_extra,
                "skip_review": skip_review,
                "reason": reason,
            }
        )

    return {"plan": fused_items}


__all__ = ["fuse_plan", "T_HIGH", "T_LOW"]
