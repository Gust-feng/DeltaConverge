"""融合规则层与 LLM 规划输出，生成最终的上下文计划。

置信度语义说明（Requirements 3.1, 3.2, 3.3）：
- confidence >= T_HIGH (0.8): 规则建议为权威来源，优先采用规则的 context_level
- confidence < T_LOW (0.3): 优先采用 LLM 规划输出的 context_level
- T_LOW <= confidence < T_HIGH: 根据上下文级别优先级决定

风险等级说明：
- 高风险（high/critical）: 通过 notes 中的 risk_level 或特定标签识别
- 高风险变更的 skip_review 应始终为 false
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import logging
import json
from datetime import datetime
from pathlib import Path

from Agent.DIFF.rule.context_levels import ctx_rank
from Agent.DIFF.rule.rule_config import ConfigDefaults

# 可选导入冲突追踪器（避免循环依赖）
_CONFLICT_TRACKER_AVAILABLE = False
try:
    from Agent.DIFF.issue.conflict_tracker import record_conflict as _record_conflict
    _CONFLICT_TRACKER_AVAILABLE = True
except ImportError:
    _record_conflict = None  # type: ignore

# 使用配置中的统一阈值
T_HIGH = ConfigDefaults.CONFIDENCE_HIGH
T_MEDIUM = ConfigDefaults.CONFIDENCE_MEDIUM
T_LOW = ConfigDefaults.CONFIDENCE_LOW

# 高风险标签集合
HIGH_RISK_TAGS = {"security_sensitive", "config_file", "routing_file"}

# 中等风险标签集合
MEDIUM_RISK_TAGS = {"in_single_function", "complete_function"}


def _simplify_scanner_issues(extra_requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """精简 scanner_issues，只保留统计信息。
    
    完整的 issues 列表可能包含数百个条目，传递给 Reviewer 会导致：
    1. 上下文过大，消耗大量 token
    2. Reviewer 处理时间过长
    3. 可能导致 LLM 输出卡死
    
    Args:
        extra_requests: 原始的 extra_requests 列表
        
    Returns:
        精简后的 extra_requests 列表，scanner_issues 只保留统计信息
    """
    if not extra_requests:
        return []
    
    simplified = []
    for req in extra_requests:
        if not isinstance(req, dict):
            continue
        if req.get("type") == "scanner_issues":
            # 只保留统计信息，不传递完整的 issues 列表
            simplified.append({
                "type": "scanner_issues",
                "issue_count": req.get("issue_count", 0),
                "error_count": req.get("error_count", 0),
                "warning_count": req.get("warning_count", 0),
                "scanners": req.get("scanners", []),
            })
        else:
            simplified.append(req)
    
    return simplified


def _extract_patterns_from_notes(notes: str) -> set:
    """从 notes 字段中提取模式列表。
    
    notes 格式示例: "patterns:security_sensitive,data_access" 或 "lang:python;patterns:import_only"
    
    Args:
        notes: 规则建议的 notes 字段
        
    Returns:
        提取的模式名称集合
    """
    if not notes:
        return set()
    
    patterns: set = set()
    
    # 查找 "patterns:" 前缀
    for part in notes.split(";"):
        part = part.strip()
        if part.startswith("patterns:"):
            pattern_str = part[len("patterns:"):]
            # 分割模式名称
            for pattern in pattern_str.split(","):
                pattern = pattern.strip()
                if pattern:
                    patterns.add(pattern)
    
    return patterns


# 高风险模式集合（对应 CHANGE_PATTERNS 中 risk="high" 或 "critical" 的模式）
HIGH_RISK_PATTERNS = {"security_sensitive", "signature_change", "data_access"}

# 中等风险模式集合（对应 CHANGE_PATTERNS 中 risk="medium" 的模式）
MEDIUM_RISK_PATTERNS = {"error_handling", "config_change"}


def _extract_risk_level_from_notes(notes: str) -> Optional[str]:
    """从 notes 字段中提取风险等级。
    
    风险等级提取逻辑：
    1. 直接检查 notes 中的风险等级标记（risk_level:xxx, risk:xxx, xxx_risk）
    2. 检查 patterns 中的高风险/中等风险模式
    
    Args:
        notes: 规则建议的 notes 字段
        
    Returns:
        风险等级字符串（low/medium/high/critical），如果未找到则返回 None
    """
    if not notes:
        return None
    
    notes_lower = notes.lower()
    
    # 检查 notes 中是否包含风险等级信息
    # 格式可能是 "risk_level:high" 或 "risk:high" 或直接包含 "high_risk"
    if "critical" in notes_lower:
        return "critical"
    if "high_risk" in notes_lower or "risk_level:high" in notes_lower or "risk:high" in notes_lower:
        return "high"
    if "medium_risk" in notes_lower or "risk_level:medium" in notes_lower or "risk:medium" in notes_lower:
        return "medium"
    if "low_risk" in notes_lower or "risk_level:low" in notes_lower or "risk:low" in notes_lower:
        return "low"
    
    # 检查 patterns 中的风险模式
    patterns = _extract_patterns_from_notes(notes)
    
    # 高风险模式
    if HIGH_RISK_PATTERNS.intersection(patterns):
        return "high"
    
    # 中等风险模式
    if MEDIUM_RISK_PATTERNS.intersection(patterns):
        return "medium"
    
    # 直接检查安全敏感模式（兼容旧格式）
    if "security_sensitive" in notes_lower:
        return "high"
    
    # 检查数据访问模式（兼容旧格式）
    if "data_access" in notes_lower:
        return "high"
    
    return None


def _is_high_risk(unit: Dict[str, Any]) -> bool:
    """判断规则侧的高置信/高风险单元，用于 planner 为空时的兜底。
    
    高风险判断逻辑（Requirements 3.1, 3.3）：
    1. confidence >= T_HIGH (0.8): 高置信度，规则建议为权威来源
    2. 包含高风险标签（security_sensitive, config_file, routing_file）
    3. notes 中包含高风险等级（high/critical）
    
    Args:
        unit: 变更单元字典
        
    Returns:
        是否为高风险单元
    """
    # 检查置信度
    conf = round(float(unit.get("rule_confidence") or 0.0), 2)
    if conf >= T_HIGH:
        return True
    
    # 检查高风险标签
    tags_raw = unit.get("tags") or []
    tags = {str(t) for t in tags_raw if t is not None}
    if HIGH_RISK_TAGS.intersection(tags):
        return True
    
    # 检查 notes 中的风险等级
    notes = unit.get("rule_notes") or ""
    risk_level = _extract_risk_level_from_notes(notes)
    if risk_level in ("high", "critical"):
        return True
    
    return False


def _is_medium_risk(unit: Dict[str, Any]) -> bool:
    """判断规则侧的中等置信/中等风险单元。
    
    中等风险判断逻辑（Requirements 3.2）：
    1. T_MEDIUM <= confidence < T_HIGH: 中等置信度
    2. 包含中等风险标签（in_single_function, complete_function）
    3. notes 中包含中等风险等级（medium）
    
    Args:
        unit: 变更单元字典
        
    Returns:
        是否为中等风险单元
    """
    # 检查置信度
    conf = round(float(unit.get("rule_confidence") or 0.0), 2)
    if T_MEDIUM <= conf < T_HIGH:
        return True
    
    # 检查中等风险标签
    tags_raw = unit.get("tags") or []
    tags = {str(t) for t in tags_raw if t is not None}
    if MEDIUM_RISK_TAGS.intersection(tags):
        return True
    
    # 检查 notes 中的风险等级
    notes = unit.get("rule_notes") or ""
    risk_level = _extract_risk_level_from_notes(notes)
    if risk_level == "medium":
        return True
    
    return False


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
    selected_ids: set[str] = {str(k) for k in llm_by_id.keys()}
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
        
        # 规范化 rule_level，防止空值或 unknown 触发回退
        rule_level = unit.get("rule_context_level")
        if not rule_level or rule_level == "unknown":
            rule_level = "diff_only"
            
        rule_conf = round(float(unit.get("rule_confidence") or 0.0), 2)

        if not unit_id:
            fused_items.append(
                {
                    "unit_id": None,
                    "rule_context_level": rule_level,
                    "rule_confidence": rule_conf,
                    "llm_context_level": None,
                    "final_context_level": rule_level,
                    "extra_requests": [],
                    "skip_review": True,
                    "reason": missing_id_reason,
                }
            )
            continue

        llm_item = llm_by_id.get(unit_id, {})
        llm_level = llm_item.get("llm_context_level")
        # 规范化 llm_level：严格白名单校验，过滤幻觉
        valid_levels = {"function", "file_context", "full_file", "diff_only"}
        if llm_level not in valid_levels:
            llm_level = None 

        llm_extra = llm_item.get("extra_requests") or llm_item.get("final_extra_requests") or []
        rule_extra = unit.get("rule_extra_requests") or []
        
        # 精简 scanner_issues：只保留统计信息，避免传递大量 issues 给 Reviewer
        # 这可以显著减少上下文大小，防止 Reviewer 卡死
        rule_extra = _simplify_scanner_issues(rule_extra)
        
        # 保存原始 LLM 决策，用于冲突检测（在高风险兜底修正之前）
        original_llm_skip = bool(llm_item.get("skip_review", False))
        original_llm_reason = llm_item.get("reason")
        
        skip_review = original_llm_skip
        reason = original_llm_reason
        
        # Requirements 3.3: 高风险变更不可跳过
        # 如果是高风险单元，强制 skip_review 为 False
        is_unit_high_risk = _is_high_risk(unit)
        if is_unit_high_risk and skip_review:
            skip_review = False
            if reason:
                reason = f"{reason}; high_risk_cannot_skip"
            else:
                reason = "high_risk_cannot_skip"

        if unit_id not in selected_ids:
            fused_items.append(
                {
                    "unit_id": unit_id,
                    "rule_context_level": rule_level,
                    "rule_confidence": rule_conf,
                    "llm_context_level": llm_level,
                    "final_context_level": rule_level,
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

        fused_item = {
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
        fused_items.append(fused_item)
        
        # 自成长机制：检测并记录规则与 LLM 决策之间的冲突
        # 使用原始 LLM 决策（未经高风险兜底修正），确保冲突能被正确检测
        if _CONFLICT_TRACKER_AVAILABLE and _record_conflict:
            try:
                original_llm_decision = {
                    "llm_context_level": llm_level,
                    "skip_review": original_llm_skip,
                    "reason": original_llm_reason,
                    "extra_requests": llm_extra,
                    "final_context_level": final_level,
                }
                _record_conflict(unit, original_llm_decision)
            except Exception as exc:
                logger = logging.getLogger(__name__)
                unit_id = unit.get("unit_id") or unit.get("id")
                logger.warning(
                    "Failed to record conflict for unit %s: %s",
                    unit_id,
                    exc,
                    exc_info=True,
                )
                try:
                    conflict_dir = Path(__file__).resolve().parent.parent / "DIFF" / "issue" / "conflicts"
                    conflict_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    filename = f"{timestamp}_record_error.json"
                    error_payload = {
                        "type": "conflict_record_error",
                        "unit_id": unit_id,
                        "timestamp": datetime.now().isoformat(),
                        "error": str(exc),
                        "unit": unit,
                        "llm_decision": original_llm_decision,
                    }
                    with open(conflict_dir / filename, "w", encoding="utf-8") as f:
                        json.dump(error_payload, f, ensure_ascii=False, indent=2)
                except Exception:
                    logger.exception("Failed to persist conflict record error for unit %s", unit_id)

    return {"plan": fused_items}


__all__ = [
    "fuse_plan", 
    "T_HIGH", 
    "T_MEDIUM",
    "T_LOW",
    "_is_high_risk",
    "_is_medium_risk",
    "_extract_risk_level_from_notes",
    "_extract_patterns_from_notes",
    "_simplify_scanner_issues",
    "HIGH_RISK_TAGS",
    "MEDIUM_RISK_TAGS",
    "HIGH_RISK_PATTERNS",
    "MEDIUM_RISK_PATTERNS",
    "_CONFLICT_TRACKER_AVAILABLE",
]
