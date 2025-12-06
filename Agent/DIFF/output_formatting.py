"""输出格式化模块：处理审查索引构建、LLM友好格式生成等。"""

from __future__ import annotations

from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any, Optional

from Agent.DIFF.git_operations import DiffMode
from Agent.DIFF.review_units import merge_nearby_hunks
from Agent.DIFF.file_utils import read_file_lines

# 针对 Planner 的轻量索引（无 files/changes、无 rule_notes/suggestion，压缩 line_numbers）。
def build_planner_index(
    units: List[Dict[str, Any]],
    actual_mode: DiffMode,
    base: Optional[str],
) -> Dict[str, Any]:
    files_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for unit in units:
        files_dict[unit["file_path"]].append(unit)

    total_lines_summary = {
        "added": sum(u["metrics"]["added_lines"] for u in units),
        "removed": sum(u["metrics"]["removed_lines"] for u in units),
    }
    changes_by_type = {"add": 0, "modify": 0, "delete": 0}
    for file_units in files_dict.values():
        change_kind = file_units[0].get("change_type", "modify")
        if change_kind in changes_by_type:
            changes_by_type[change_kind] += 1

    units_index: List[Dict[str, Any]] = []
    for file_path, file_units in files_dict.items():
        for unit in file_units:
            line_numbers = unit.get("line_numbers") or {}
            units_index.append(
                {
                    "unit_id": unit.get("unit_id") or unit.get("id"),
                    "file_path": file_path,
                    "patch_type": unit.get("patch_type") or unit.get("change_type"),
                    "tags": unit.get("tags", []),
                    "metrics": unit.get("metrics", {}),
                    "rule_context_level": unit.get("rule_context_level"),
                    "rule_confidence": unit.get("rule_confidence"),
                    "line_numbers": {
                        "new_compact": line_numbers.get("new_compact"),
                        "old_compact": line_numbers.get("old_compact"),
                    },
                    "rule_extra_requests": unit.get("rule_extra_requests"),
                }
            )

    return {
        "review_metadata": {
            "mode": actual_mode.value,
            "base_branch": base,
            "total_files": len(files_dict),
            "total_changes": len(units),
            "timestamp": datetime.now().isoformat(),
        },
        "summary": {
            "changes_by_type": changes_by_type,
            "total_lines": total_lines_summary,
            "files_changed": sorted(files_dict.keys()),
        },
        "units": units_index,
    }


def build_review_index(
    units: List[Dict[str, Any]],
    actual_mode: DiffMode,
    base: Optional[str],
) -> Dict[str, Any]:
    """构建轻量的“审查单元索引”（无上下文/大段 diff）。"""

    files_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for unit in units:
        files_dict[unit["file_path"]].append(unit)

    total_lines_summary = {
        "added": sum(u["metrics"]["added_lines"] for u in units),
        "removed": sum(u["metrics"]["removed_lines"] for u in units),
    }
    changes_by_type = {"add": 0, "modify": 0, "delete": 0}
    for file_units in files_dict.values():
        change_kind = file_units[0].get("change_type", "modify")
        if change_kind in changes_by_type:
            changes_by_type[change_kind] += 1

    file_entries: List[Dict[str, Any]] = []
    units_index: List[Dict[str, Any]] = []
    for file_path in sorted(files_dict.keys()):
        file_units = files_dict[file_path]
        file_tags = sorted({tag for u in file_units for tag in u.get("tags", [])})
        file_added = sum(u["metrics"]["added_lines"] for u in file_units)
        file_removed = sum(u["metrics"]["removed_lines"] for u in file_units)

        changes: List[Dict[str, Any]] = []
        for unit in file_units:
            hunk_range = unit.get("hunk_range", {})
            agent_decision = unit.get("agent_decision") or {}
            changes.append(
                {
                    "id": unit.get("id"),
                    "unit_id": unit.get("unit_id") or unit.get("id"),
                    "rule_context_level": unit.get("rule_context_level"),
                    "rule_confidence": unit.get("rule_confidence"),
                    # 精简决策信息，保留上下文字段与优先级
                    "agent_decision": {
                        "context_level": agent_decision.get("context_level"),
                        "priority": agent_decision.get("priority"),
                    }
                    if agent_decision
                    else None,
                    "hunk_range": hunk_range,
                    "line_numbers": unit.get("line_numbers"),
                    "metrics": unit.get("metrics", {}),
                    "tags": unit.get("tags", []),
                    "context_mode": unit.get("context_mode"),
                    "symbol": unit.get("symbol"),
                    "rule_extra_requests": unit.get("rule_extra_requests"),
                    # 移除 rule_suggestion/rule_notes/diff，保持 review_index 轻量
                }
            )
            units_index.append(
                {
                    "unit_id": unit.get("unit_id") or unit.get("id"),
                    "file_path": file_path,
                    "language": unit.get("language", "unknown"),
                    "patch_type": unit.get("patch_type") or unit.get("change_type"),
                    "tags": unit.get("tags", []),
                    "metrics": unit.get("metrics", {}),
                    "rule_context_level": unit.get("rule_context_level"),
                    "rule_confidence": unit.get("rule_confidence"),
                    "rule_notes": unit.get("rule_notes"),  # 添加规则备注，供融合层使用
                    "rule_extra_requests": unit.get("rule_extra_requests"),  # 添加额外请求
                    "line_numbers": unit.get("line_numbers"),
                }
            )

        file_entries.append(
            {
                "path": file_path,
                "language": file_units[0].get("language", "unknown"),
                "change_type": file_units[0].get("change_type", "modify"),
                "metrics": {
                    "added_lines": file_added,
                    "removed_lines": file_removed,
                    "changes": len(changes),
                },
                "tags": file_tags,
                "changes": changes,
            }
        )

    return {
        "review_metadata": {
            "mode": actual_mode.value,
            "base_branch": base,
            "total_files": len(files_dict),
            "total_changes": len(units),
            "timestamp": datetime.now().isoformat(),
        },
        "summary": {
            "changes_by_type": changes_by_type,
            "total_lines": total_lines_summary,
            "files_changed": sorted(files_dict.keys()),
        },
        "units": units_index,
        "files": file_entries,
    }


def build_llm_friendly_output(
    units: List[Dict[str, Any]],
    actual_mode: DiffMode,
    base: Optional[str],
) -> Dict[str, Any]:
    """构建供 LLM 使用的结构化 diff 视图（JSON 结构）。

    该函数在 CLI 模式和 Agent 上下文构建中复用，避免两套格式不一致。
    """

    # 按文件分组
    files_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for unit in units:
        files_dict[unit["file_path"]].append(unit)

    file_type_counts = {"add": 0, "modify": 0}
    for file_units in files_dict.values():
        change_kind = file_units[0]["change_type"]
        if change_kind in file_type_counts:
            file_type_counts[change_kind] += 1

    total_lines_summary = {
        "added": sum(u["metrics"]["added_lines"] for u in units),
        "removed": sum(u["metrics"]["removed_lines"] for u in units),
    }

    output: Dict[str, Any] = {
        "review_metadata": {
            "mode": actual_mode.value,
            "base_branch": base,
            "total_files": len(files_dict),
            "total_changes": len(units),
            "timestamp": datetime.now().isoformat(),
        },
        "summary": {
            "files_changed": list(files_dict.keys()),
            "changes_by_type": file_type_counts,
            "total_lines": total_lines_summary,
        },
        "files": [],
    }

    # 为每个文件构建清晰的变更描述
    for file_path, file_units in files_dict.items():
        file_info: Dict[str, Any] = {
            "path": file_path,
            "language": file_units[0]["language"],
            "change_type": file_units[0]["change_type"],
            "changes": [],
        }

        # 智能合并：如果多个 hunk 距离很近（<20 行），考虑合并
        file_lines_for_merge = read_file_lines(file_path)
        merged_units = merge_nearby_hunks(file_units, file_lines=file_lines_for_merge)

        for unit in merged_units:
            context_mode = unit.get("context_mode")
            # 获取完整上下文（不过度裁剪，LLM 需要足够信息）
            context = unit["code_snippets"]["context"]
            context_lines = context.split("\n") if context else []

            # 如果上下文超过 50 行，才进行裁剪
            if len(context_lines) > 50 and context_mode != "doc_light":
                hunk_range = unit["hunk_range"]
                start = hunk_range["new_start"]
                length = hunk_range["new_lines"]
                ctx_start = unit["code_snippets"]["context_start"]

                # 计算相对位置
                rel_start = start - ctx_start
                rel_end = rel_start + length

                # 保留前后 10 行（给 LLM 更多上下文）
                keep_start = max(0, rel_start - 10)
                keep_end = min(len(context_lines), rel_end + 10)

                trimmed = context_lines[keep_start:keep_end]
                if keep_start > 0:
                    trimmed.insert(0, "...")
                if keep_end < len(context_lines):
                    trimmed.append("...")
                context = "\n".join(trimmed)

            line_numbers = unit.get("line_numbers", {}) or {}
            new_compact = line_numbers.get("new_compact")
            old_compact = line_numbers.get("old_compact")
            if new_compact:
                location_str = new_compact
            elif old_compact:
                location_str = f"(removed) {old_compact}"
            else:
                location_str = (
                    f"L{unit['hunk_range']['new_start']}-"
                    f"L{unit['hunk_range']['new_start'] + unit['hunk_range']['new_lines'] - 1}"
                )

            change = {
                "location": location_str,
                "change_size": (
                    f"+{unit['metrics']['added_lines']}/"
                    f"-{unit['metrics']['removed_lines']}"
                ),
                "metrics": {
                    "added_lines": unit["metrics"]["added_lines"],
                    "removed_lines": unit["metrics"]["removed_lines"],
                },
                # 仅保留压缩行号，避免巨大列表噪音
                "line_numbers": {
                    "new_compact": line_numbers.get("new_compact"),
                    "old_compact": line_numbers.get("old_compact"),
                },
                "unified_diff": unit.get("unified_diff", ""),
                "unified_diff_with_lines": unit.get("unified_diff_with_lines"),
                "surrounding_context": (
                    context if context else "(no context available)"
                ),
                "tags": unit.get("tags", []),
                "structure_info": {
                    "before": unit["code_snippets"]["before"],
                    "after": unit["code_snippets"]["after"],
                },
                "rule_suggestion": unit.get("rule_suggestion"),
                "agent_decision": unit.get("agent_decision"),
            }

            if context_mode == "doc_light":
                change["surrounding_context"] = "(doc snippet)"
                change["structure_info"] = {
                    "before": "",
                    "after": unit["code_snippets"]["after"],
                }

            file_info["changes"].append(change)

        output["files"].append(file_info)

    return output
