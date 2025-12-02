"""审查单元构建模块：处理审查单元的创建、合并、规则应用等。"""

from __future__ import annotations

import ast
import uuid
from typing import List, Dict, Any, Optional, cast
from unidiff import PatchSet

from Agent.DIFF.file_utils import read_file_lines, guess_language, parse_python_ast, _truncate_doc_block
from Agent.DIFF.diff_processing import (
    extract_unified_diff_view,
    extract_unified_diff_view_with_lines,
    extract_before_after_from_hunk,
    _collect_line_numbers,
    _compact_line_spans,
    extract_context,
)
from Agent.DIFF.code_analysis import (
    smart_expand_context,
    infer_symbol_and_scope_tag,
    infer_simple_change_tags,
    infer_file_level_tags,
)
from Agent.DIFF.git_operations import DiffMode

# 导入规则层模块，使用可选导入以确保降级兼容性
_RULES_AVAILABLE = False
try:
    from Agent.DIFF.rule.context_decision import (
        build_rule_suggestion,
        build_decision_from_rules,
        Unit,
    )
    _RULES_AVAILABLE = True
except ImportError:
    print("[警告] 规则层模块未找到，将跳过规则决策")
    Unit = Any


def merge_nearby_hunks(
    units: List[Dict[str, Any]],
    file_lines: Optional[List[str]] = None,
    max_gap: int = 20,
) -> List[Dict[str, Any]]:
    """合并距离很近的 hunk，避免碎片化。
    
    Args:
        units: 同一文件的审查单元列表
        file_lines: 用于重新提取上下文的完整文件内容
        max_gap: 最大行间隔，小于此值的 hunk 会被合并
    
    Returns:
        合并后的审查单元列表
    """
    if len(units) <= 1:
        return units
    
    # 按行号排序
    sorted_units = sorted(units, key=lambda u: u["hunk_range"]["new_start"])
    
    merged: List[Dict[str, Any]] = []
    current_group = [sorted_units[0]]
    
    for unit in sorted_units[1:]:
        prev_unit = current_group[-1]
        prev_end = prev_unit["hunk_range"]["new_start"] + prev_unit["hunk_range"]["new_lines"]
        curr_start = unit["hunk_range"]["new_start"]
        
        # 如果间隔小于阈值，加入当前组
        if curr_start - prev_end <= max_gap:
            current_group.append(unit)
        else:
            # 否则合并当前组，开始新组
            if len(current_group) > 1:
                merged.append(merge_unit_group(current_group, file_lines))
            else:
                merged.append(current_group[0])
            current_group = [unit]
    
    # 处理最后一组
    if len(current_group) > 1:
        merged.append(merge_unit_group(current_group, file_lines))
    else:
        merged.append(current_group[0])
    
    return merged


def merge_unit_group(
    group: List[Dict[str, Any]],
    file_lines: Optional[List[str]],
) -> Dict[str, Any]:
    """合并一组 hunk 为单个审查单元。"""
    first = group[0]
    last = group[-1]
    
    # 合并 unified_diff
    all_diffs = [u.get("unified_diff", "") for u in group]
    merged_diff = "\n...\n".join(all_diffs)
    all_diffs_with_lines = [
        str(u.get("unified_diff_with_lines", "")) for u in group if u.get("unified_diff_with_lines")
    ]
    merged_diff_with_lines = "\n...\n".join(all_diffs_with_lines) if all_diffs_with_lines else merged_diff
    
    # 计算总的行变更
    total_added = sum(u["metrics"]["added_lines"] for u in group)
    total_removed = sum(u["metrics"]["removed_lines"] for u in group)
    
    # 计算新的范围
    def _range_end(unit: Dict[str, Any], key: str) -> int:
        start = unit["hunk_range"][f"{key}_start"]
        length = unit["hunk_range"][f"{key}_lines"]
        if start <= 0:
            return start
        return start + max(length - 1, 0)

    new_starts = []
    for unit in group:
        start_val = unit["hunk_range"]["new_start"]
        if start_val > 0:
            new_starts.append(start_val)
    new_start = min(new_starts) if new_starts else 1
    new_end_candidates = []
    for unit in group:
        candidate = _range_end(unit, "new")
        if candidate > 0:
            new_end_candidates.append(candidate)
    new_end = max(new_end_candidates) if new_end_candidates else new_start

    old_starts = []
    for unit in group:
        start_val = unit["hunk_range"]["old_start"]
        if start_val > 0:
            old_starts.append(start_val)
    old_start = min(old_starts) if old_starts else first["hunk_range"]["old_start"]
    old_end_candidates = []
    for unit in group:
        candidate = _range_end(unit, "old")
        if candidate > 0:
            old_end_candidates.append(candidate)
    old_end = max(old_end_candidates) if old_end_candidates else old_start

    # 重新提取上下文以覆盖合并后的范围
    if file_lines:
        context_snippet, ctx_start, ctx_end = extract_context(
            file_lines, new_start, new_end
        )
    else:
        context_snippet = "\n...\n".join(u["code_snippets"]["context"] for u in group if u["code_snippets"]["context"])
        ctx_start = first["code_snippets"]["context_start"]
        ctx_end = last["code_snippets"]["context_end"]

    combined_tags = sorted({tag for unit in group for tag in unit.get("tags", [])})
    if any(unit.get("is_merged") for unit in group):
        combined_tags.append("merged_block")
        combined_tags = sorted(set(combined_tags))

    new_line_numbers: List[int] = []
    old_line_numbers: List[int] = []
    for unit in group:
        ln = unit.get("line_numbers") or {}
        new_line_numbers.extend(ln.get("new") or [])
        old_line_numbers.extend(ln.get("old") or [])
    new_line_numbers = sorted(set(new_line_numbers))
    old_line_numbers = sorted(set(old_line_numbers))
    line_numbers = {
        "new": new_line_numbers,
        "old": old_line_numbers,
        "new_compact": _compact_line_spans(new_line_numbers),
        "old_compact": _compact_line_spans(old_line_numbers),
    }
    
    return {
        "id": first["id"],
        "file_path": first["file_path"],
        "language": first["language"],
        "change_type": first["change_type"],
        "unified_diff": merged_diff,
        "unified_diff_with_lines": merged_diff_with_lines,
        "hunk_range": {
            "new_start": new_start,
            "new_lines": max(new_end - new_start + 1, first["hunk_range"]["new_lines"]),
            "old_start": old_start,
            "old_lines": max(old_end - old_start + 1, first["hunk_range"]["old_lines"]),
        },
        "code_snippets": {
            "before": "\n...\n".join(u["code_snippets"]["before"] for u in group),
            "after": "\n...\n".join(u["code_snippets"]["after"] for u in group),
            "context": context_snippet,
            "context_start": ctx_start,
            "context_end": ctx_end,
        },
        "tags": combined_tags,
        "line_numbers": line_numbers,
        "metrics": {
            "added_lines": total_added,
            "removed_lines": total_removed,
            "hunk_count": len(group),
        },
        "is_merged": True,
        "merged_count": len(group)
    }


def _apply_rules_to_units(units: List[Dict[str, Any]]) -> None:
    """为审查单元附加规则建议/决策；规则缺失时填充占位值。"""

    if not units:
        return
    if not _RULES_AVAILABLE:
        for unit in units:
            unit["rule_suggestion"] = {
                "context_level": "unknown",
                "confidence": 0.0,
                "notes": "rule_unavailable",
            }
            unit["rule_context_level"] = "unknown"
            unit["rule_confidence"] = 0.0
            unit["rule_notes"] = "rule_unavailable"
        return

    def _normalize_context_level(level: str) -> str:
        """将规则层的上下文级别映射到统一的 review_index 语义。"""
        if level == "local":
            return "diff_only"
        if level == "function":
            return "function"
        if level == "file":
            return "file_context"
        return "unknown"

    for unit in units:
        rule_unit = cast(Unit, { # type: ignore
            "file_path": unit.get("file_path", ""),
            "language": unit.get("language", "unknown"),
            "change_type": unit.get("change_type", "modify"),
            "metrics": unit.get("metrics", {}),
            "tags": unit.get("tags", []),
            "symbol": unit.get("symbol"),
        })
        try:
            suggestion = build_rule_suggestion(rule_unit)
            unit["rule_suggestion"] = suggestion
            unit["rule_context_level"] = _normalize_context_level(
                str(suggestion.get("context_level", "unknown"))
            )
            unit["rule_confidence"] = round(float(suggestion.get("confidence", 0.0)), 2)
            unit["rule_notes"] = suggestion.get("notes")
            if suggestion.get("extra_requests"):
                unit["rule_extra_requests"] = suggestion.get("extra_requests")
        except Exception as exc:
            unit["rule_suggestion"] = {
                "context_level": "unknown",
                "confidence": 0.0,
                "notes": f"rule_error:{exc}",
            }
            unit["rule_context_level"] = "unknown"
            unit["rule_confidence"] = 0.0
            unit["rule_notes"] = f"rule_error:{exc}"
            continue

        try:
            # 主链路改为规划 LLM；规则层仅给出兜底决策，不再触发未实现的 context agent。
            decision = build_decision_from_rules(rule_unit, suggestion)
            unit["agent_decision"] = decision
        except Exception as exc:  # pragma: no cover - 防御性兜底
            unit["agent_decision"] = {
                "context_level": "function",
                "before_lines": 8,
                "after_lines": 8,
                "focus": ["logic", "security"],
                "priority": "medium",
                "reason": f"rule_error:{exc}",
            }


def build_review_units_from_patch(
    patch: PatchSet, use_smart_context: bool = True, apply_rules: bool = True
) -> List[Dict[str, Any]]:
    """从 PatchSet 构建审查单元，可选智能上下文与规则层处理。"""

    units: List[Dict[str, Any]] = []
    for patched_file in patch:
        if patched_file.is_removed_file:
            continue

        file_path = patched_file.path
        # 处理 Git 转义的文件路径（如 "\346\226\207\344\273\266.md"）
        if file_path.startswith('"') and file_path.endswith('"'):
            try:
                file_path = file_path[1:-1].encode('latin1').decode('unicode_escape').encode('latin1').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                file_path = file_path.strip('"')
        full_lines = read_file_lines(file_path)
        change_type = "add" if patched_file.is_added_file else "modify"
        language = guess_language(file_path)
        is_doc_file = language == "text"
        file_ast: Optional[ast.AST] = None
        if language == "python" and full_lines:
            file_ast = parse_python_ast(full_lines)

        base_tags = infer_file_level_tags(file_path, language)

        for hunk in patched_file:
            before_snippet, after_snippet = extract_before_after_from_hunk(hunk)
            unified_diff = extract_unified_diff_view(hunk)
            unified_diff_with_lines = extract_unified_diff_view_with_lines(hunk)
            new_line_numbers, old_line_numbers = _collect_line_numbers(hunk)
            line_numbers = {
                "new": new_line_numbers,
                "old": old_line_numbers,
                "new_compact": _compact_line_spans(new_line_numbers),
                "old_compact": _compact_line_spans(old_line_numbers),
            }

            new_start = hunk.target_start if hunk.target_start > 0 else 1
            if hunk.target_length > 0:
                new_end = new_start + hunk.target_length - 1
            else:
                new_end = new_start

            # 使用智能上下文扩展
            tags: List[str] = list(base_tags)

            symbol_info, scope_tags = infer_symbol_and_scope_tag(
                language, file_ast, full_lines, new_start, new_end
            )
            tags.extend(scope_tags)
            if use_smart_context and language == "python" and full_lines:
                expanded_start, expanded_end, smart_tags = smart_expand_context(
                    full_lines, hunk, new_start, new_end, language, file_ast
                )
                tags.extend(smart_tags)
                
                # 使用扩展后的范围
                context_snippet = "\n".join(full_lines[expanded_start - 1 : expanded_end])
                ctx_start = expanded_start
                ctx_end = expanded_end
            else:
                # 降级到固定上下文
                context_snippet, ctx_start, ctx_end = extract_context(
                    full_lines, new_start, new_end
                )

            # 简单模式标签：only_imports/only_comments/only_logging
            tags.extend(infer_simple_change_tags(hunk, language))

            # 文本文档的上下文做截断，避免全文膨胀
            if is_doc_file:
                unified_diff = _truncate_doc_block(unified_diff, max_lines=60)
                before_snippet = _truncate_doc_block(before_snippet, max_lines=40)
                after_snippet = _truncate_doc_block(after_snippet, max_lines=40)
                context_snippet = _truncate_doc_block(context_snippet, max_lines=50)
                tags.append("doc_file")

            # 去重保持稳定顺序
            if tags:
                # 保留首次出现的顺序。
                seen: set[str] = set()
                deduped: List[str] = []
                for t in tags:
                    if t not in seen:
                        seen.add(t)
                        deduped.append(t)
                tags = deduped

            added_lines = sum(1 for line in hunk if line.line_type == "+")
            removed_lines = sum(1 for line in hunk if line.line_type == "-")

            unit_id = str(uuid.uuid4())
            in_single_function = "in_single_function" in tags

            units.append(
                {
                    "id": unit_id,
                    "unit_id": unit_id,
                    "file_path": file_path,
                    "language": language,
                    "change_type": change_type,
                    "patch_type": change_type,
                    "context_mode": "doc_light" if is_doc_file else None,
                    "unified_diff": unified_diff,
                    "unified_diff_with_lines": unified_diff_with_lines,
                    "hunk_range": {
                        "old_start": hunk.source_start,
                        "old_lines": hunk.source_length,
                        "new_start": hunk.target_start,
                        "new_lines": hunk.target_length,
                    },
                    "code_snippets": {
                        "before": before_snippet,
                        "after": after_snippet,
                        "context": context_snippet,
                        "context_start": ctx_start,
                        "context_end": ctx_end,
                    },
                    "line_numbers": line_numbers,
                    "tags": tags,
                    "symbol": symbol_info,
                    "metrics": {
                        "added_lines": added_lines,
                        "removed_lines": removed_lines,
                        "hunk_count": 1,
                        "in_single_function": in_single_function,
                    },
                }
            )

    if apply_rules:
        _apply_rules_to_units(units)

    return units
