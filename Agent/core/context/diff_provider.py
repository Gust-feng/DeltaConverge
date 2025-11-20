"""Utilities to collect diff-based context for prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import json

try:
    from unidiff import PatchSet
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("unidiff package is required for diff context collection") from exc

from DIFF import diff_collector


@dataclass
class DiffContext:
    """Structured representation of collected diff context."""

    summary: str
    files: List[str]
    units: List[Dict[str, Any]]
    mode: diff_collector.DiffMode
    base_branch: str | None


def _safe_int(value: Any, default: int = 0) -> int:
    """Best-effort int conversion used for metadata fields."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def collect_diff_context(
    mode: diff_collector.DiffMode = diff_collector.DiffMode.AUTO,
    max_units: int = 20,
) -> DiffContext:
    """Collect diff context and return a textual summary plus metadata."""

    diff_text, actual_mode, base_branch = diff_collector.get_diff_text(mode)
    if not diff_text.strip():
        raise RuntimeError("No diff detected for the selected mode.")

    patch = PatchSet(diff_text)
    units = diff_collector.build_review_units_from_patch(patch)
    if not units:
        raise RuntimeError("Diff detected but no review units were produced.")

    summary_parts: List[str] = []
    for idx, unit in enumerate(units[:max_units], start=1):
        path = unit.get("file_path")
        change_type = unit.get("change_type")
        metrics = unit.get("metrics", {})
        hunk = unit.get("hunk_range", {})
        context = unit.get("code_snippets", {}).get("context", "").strip()
        diff_view = unit.get("unified_diff", "").strip()
        summary_parts.append(
            "\n".join(
                [
                    f"[Change {idx}] File: {path}",
                    f"Type: {change_type}, Added: {metrics.get('added_lines', 0)}, "
                    f"Removed: {metrics.get('removed_lines', 0)}",
                    f"Hunk new_start: {hunk.get('new_start')} length: {hunk.get('new_lines')}",
                    "Context:",
                    context or "(context unavailable)",
                    "Diff:",
                    diff_view or "(diff unavailable)",
                ]
            )
        )

    if len(units) > max_units:
        summary_parts.append(
            f"... truncated {len(units) - max_units} additional change(s) ..."
        )

    files = sorted({unit["file_path"] for unit in units if unit.get("file_path")})
    return DiffContext(
        summary="\n\n".join(summary_parts),
        files=files,
        units=units,
        mode=actual_mode,
        base_branch=base_branch,
    )


def build_markdown_and_json_context(
    diff_ctx: DiffContext,
    max_files: int = 5,
    max_changes_per_file: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    """基于 DiffContext 构建“Markdown + 精简 JSON”混合上下文。

    设计目标：
    - 用少量 token 告诉模型“这个 PR 重点改了什么”。
    - 优先展示高风险 / 高影响 / 结构性变更，弱化纯导入/注释等噪音。
    """

    llm_output = diff_collector.build_llm_friendly_output(
        diff_ctx.units, diff_ctx.mode, diff_ctx.base_branch
    )

    # 基于简单启发式对 change 打分，用于排序与筛选
    files = llm_output.get("files", []) or []

    def score_change(change: Dict[str, Any]) -> float:
        metrics = change.get("metrics") or {}
        added = _safe_int(metrics.get("added_lines"))
        removed = _safe_int(metrics.get("removed_lines"))
        size = added + removed

        tags = change.get("tags") or []
        tag_set = set(tags)

        score = float(size)

        # 高价值标签加权
        if "security_sensitive" in tag_set:
            score += 40
        if "config_file" in tag_set or "routing_file" in tag_set:
            score += 25
        if any(t.startswith("complete_") for t in tag_set):
            score += 20
        if "merged_block" in tag_set:
            score += 10

        # 低价值（噪音）标签减权
        if "only_imports" in tag_set:
            score *= 0.2
        if "only_comments" in tag_set:
            score *= 0.1
        if "only_logging" in tag_set:
            score *= 0.3

        return score

    # 先为每个文件的 change 打分并排序，再按文件“最高分”排序文件本身
    scored_files: List[Dict[str, Any]] = []
    for file_entry in files:
        changes = file_entry.get("changes", []) or []
        for c in changes:
            c["_score"] = score_change(c)
        changes.sort(key=lambda c: c["_score"], reverse=True)
        top_score = changes[0]["_score"] if changes else 0.0
        file_entry["_top_score"] = top_score
        scored_files.append(file_entry)

    scored_files.sort(key=lambda f: f.get("_top_score", 0.0), reverse=True)

    # 精简 JSON：只保留前 max_files 个文件、每个文件前 max_changes_per_file 个变更
    pruned_files: List[Dict[str, Any]] = []
    truncated_changes_count = 0
    noise_only_files = 0

    def is_noise_change(ch: Dict[str, Any]) -> bool:
        tags = set(ch.get("tags") or [])
        return bool(
            {"only_imports", "only_comments", "only_logging"}.intersection(tags)
        )

    for file_entry in scored_files[:max_files]:
        changes = file_entry.get("changes", []) or []
        # 在前 max_changes_per_file 中优先选“非纯噪音”变更
        important = [c for c in changes if not is_noise_change(c)]
        fallback = [c for c in changes if is_noise_change(c)]
        ordered_changes = important + fallback

        selected = ordered_changes[:max_changes_per_file]
        if len(changes) > len(selected):
            truncated_changes_count += len(changes) - len(selected)

        if changes and all(is_noise_change(c) for c in changes):
            noise_only_files += 1

        # 去掉内部评分字段
        for c in selected:
            c.pop("_score", None)

        pruned_files.append(
            {
                "path": file_entry.get("path"),
                "language": file_entry.get("language"),
                "change_type": file_entry.get("change_type"),
                "changes": selected,
            }
        )

    pruned_json: Dict[str, Any] = {
        "review_metadata": llm_output.get("review_metadata", {}),
        "summary": llm_output.get("summary", {}),
        "files": pruned_files,
    }

    meta = pruned_json.get("review_metadata", {})
    summary = pruned_json.get("summary", {})

    mode_str = meta.get("mode", "")
    base_branch = meta.get("base_branch") or "(未检测到 base 分支)"
    total_files = _safe_int(meta.get("total_files"))
    total_changes = _safe_int(meta.get("total_changes"))

    total_lines = summary.get("total_lines", {})
    added = _safe_int(total_lines.get("added"))
    removed = _safe_int(total_lines.get("removed"))

    files_changed = summary.get("files_changed", [])
    if files_changed:
        files_list_md = "\n".join(
            f"- `{path}`" for path in files_changed[:max_files]
        )
        if len(files_changed) > max_files:
            files_list_md += (
                f"\n- ... 共 {len(files_changed)} 个文件（此处仅展示前 {max_files} 个，按影响力排序）"
            )
    else:
        files_list_md = "(无文件信息)"

    # 构建 Markdown 概览和重点变更列表
    lines: List[str] = []
    lines.append("# 代码审查上下文")
    lines.append("")
    lines.append("## 变更概要")
    lines.append("")
    lines.append(f"- Diff 模式：`{mode_str}`")
    lines.append(f"- 基线分支：`{base_branch}`")
    lines.append(f"- 变更文件数：{total_files}")
    lines.append(f"- 审查单元数：{total_changes}")
    lines.append(f"- 行数统计：`+{added} / -{removed}`")
    lines.append("")
    lines.append("### 涉及文件（截断视图）")
    lines.append("")
    lines.append(files_list_md)
    lines.append("")

    lines.append("## 重点变更列表（按文件，已按风险和影响排序）")
    lines.append("")
    if not pruned_files:
        lines.append("_当前 diff 中未检测到可用的变更单元。_")
    else:
        for file_entry in pruned_files:
            path = file_entry.get("path")
            language = file_entry.get("language", "unknown")
            change_type = file_entry.get("change_type", "modify")
            lines.append(
                f"### 文件：`{path}`  （语言：{language}，类型：{change_type}）"
            )
            lines.append("")
            changes = file_entry.get("changes", [])
            if not changes:
                lines.append("- （此文件的变更已被截断，仅在 JSON 中保留）")
                lines.append("")
                continue
            for idx, change in enumerate(changes, start=1):
                location = change.get("location", "")
                change_size = change.get("change_size", "")
                tags = change.get("tags") or []
                tags_text = ", ".join(tags) if tags else "无特别标签"
                lines.append(
                    f"- 变更 {idx}：位置 {location}，规模 `{change_size}`，标签：{tags_text}"
                )
            lines.append("")

    # 嵌入精简 JSON 作为结构化视图
    lines.append("## 结构化 diff 视图（精简 JSON）")
    lines.append("")
    note_parts: List[str] = [
        "下面是对本次 PR 关键变更的结构化表示，采用 JSON 格式，仅保留部分文件和变更，",
        "用于帮助你进行精细分析和交叉引用。",
    ]
    if truncated_changes_count:
        note_parts.append(
            f"另外还有 {truncated_changes_count} 个次要变更已被省略细节（多为注释/导入/日志微调），如有需要可以显式说明再展开。"
        )
    if noise_only_files:
        note_parts.append(
            f"其中有 {noise_only_files} 个文件仅包含注释/导入/日志等噪音级变更，已尽量缩短展示。"
        )
    lines.append("".join(note_parts))
    lines.append("")
    json_snippet = json.dumps(pruned_json, ensure_ascii=False, indent=2)
    lines.append("```json")
    lines.append(json_snippet)
    lines.append("```")

    markdown = "\n".join(lines)
    return markdown, pruned_json
