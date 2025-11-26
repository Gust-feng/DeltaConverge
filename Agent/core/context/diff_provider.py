"""基于 git diff 构建审查上下文的工具（供规划/审查提示使用）。"""

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
    """收集到的 diff 上下文的结构化表示。"""

    summary: str
    files: List[str]
    units: List[Dict[str, Any]]
    mode: diff_collector.DiffMode
    base_branch: str | None
    review_index: Dict[str, Any]


def _safe_int(value: Any, default: int = 0) -> int:
    """用于元数据字段的尽力 int 转换。"""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def collect_diff_context(
    mode: diff_collector.DiffMode = diff_collector.DiffMode.AUTO,
) -> DiffContext:
    """收集 diff 并生成元数据摘要：ReviewUnit + review_index + 简要文本概览。"""

    diff_text, actual_mode, base_branch = diff_collector.get_diff_text(mode)
    if not diff_text.strip():
        raise RuntimeError("No diff detected for the selected mode.")

    patch = PatchSet(diff_text)
    units = diff_collector.build_review_units_from_patch(patch)
    if not units:
        raise RuntimeError("Diff detected but no review units were produced.")

    review_index = diff_collector.build_review_index(
        units, actual_mode, base_branch
    )
    meta = review_index.get("review_metadata", {})
    summary_meta = review_index.get("summary", {})
    total_lines = summary_meta.get("total_lines", {}) if isinstance(summary_meta, dict) else {}

    files = sorted({unit["file_path"] for unit in units if unit.get("file_path")})
    top_files = summary_meta.get("files_changed") or files
    files_preview = ", ".join(top_files[:5]) if top_files else "(none)"
    if top_files and len(top_files) > 5:
        files_preview += f", ... (+{len(top_files) - 5})"

    summary_text = (
        f"mode={meta.get('mode', '-')}, base={meta.get('base_branch') or '-'}, "
        f"files={meta.get('total_files', 0)}, units={meta.get('total_changes', 0)}, "
        f"lines=+{_safe_int(total_lines.get('added'))}/-{_safe_int(total_lines.get('removed'))}; "
        f"changed_files=[{files_preview}]"
    )

    files = sorted({unit["file_path"] for unit in units if unit.get("file_path")})
    return DiffContext(
        summary=summary_text,
        files=files,
        units=units,
        mode=actual_mode,
        base_branch=base_branch,
        review_index=review_index,
    )


def build_markdown_and_json_context(
    diff_ctx: DiffContext,
    max_files: int = 5,
    max_changes_per_file: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    """基于 ReviewUnit 索引构建轻量 Markdown+JSON 上下文（不携带 diff/代码正文）。

    设计目标：
    - 让 LLM 看到“有哪些审查单元、规模、标签、规则决策”，但不直接塞入上下文正文。
    - 提醒模型按需调用工具获取代码片段，减少首轮 token 消耗。
    """

    review_index = diff_ctx.review_index or diff_collector.build_review_index(
        diff_ctx.units, diff_ctx.mode, diff_ctx.base_branch
    )
    files = review_index.get("files", []) or []

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

        # 规则层的优先级可作为轻量加权
        agent_decision = change.get("agent_decision") or {}
        priority = str(agent_decision.get("priority", "")).lower()
        if priority == "high":
            score += 15
        elif priority == "medium":
            score += 5

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
        changes = list(file_entry.get("changes", []) or [])
        for c in changes:
            c["_score"] = score_change(c)
        changes.sort(key=lambda c: c["_score"], reverse=True)
        top_score = changes[0]["_score"] if changes else 0.0
        scored_files.append(
            {
                **file_entry,
                "changes": changes,
                "_top_score": top_score,
            }
        )

    scored_files.sort(key=lambda f: f.get("_top_score", 0.0), reverse=True)

    # 精简 JSON：只保留前 max_files 个文件、每文件前 max_changes_per_file 个变更
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

        clean_changes: List[Dict[str, Any]] = []
        for c in selected:
            c = dict(c)
            c.pop("_score", None)
            clean_changes.append(c)

        pruned_files.append(
            {
                "path": file_entry.get("path"),
                "language": file_entry.get("language"),
                "change_type": file_entry.get("change_type"),
                "metrics": file_entry.get("metrics"),
                "tags": file_entry.get("tags"),
                "changes": clean_changes,
            }
        )

    pruned_json: Dict[str, Any] = {
        "review_metadata": review_index.get("review_metadata", {}),
        "summary": review_index.get("summary", {}),
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
                f"\n- ... 共 {len(files_changed)} 个文件（仅列出前 {max_files} 个）"
            )
    else:
        files_list_md = "(无文件信息)"

    # 构建 Markdown 概览和重点变更列表（无 diff/正文）
    lines: List[str] = []
    lines.append("# 代码审查索引（轻量版）")
    lines.append("")
    lines.append("## 变更概要")
    lines.append("")
    lines.append(f"- Diff 模式：`{mode_str}`")
    lines.append(f"- 基线分支：`{base_branch}`")
    lines.append(f"- 变更文件数：{total_files}")
    lines.append(f"- 审查单元数：{total_changes}")
    lines.append(f"- 行数统计：`+{added} / -{removed}`")
    lines.append("- 说明：此处仅包含 ReviewUnit 索引（位置/行数/标签/规则决策），不含 diff/代码片段；如需代码请调用工具获取。")
    lines.append("- 字段速览：`rule_context_level`=规则建议的上下文粒度，`rule_confidence`=规则置信度(0-1)，`agent_decision`=规则层决策摘要，`tags`=变更标签（安全/配置/噪音等）。")
    lines.append("")
    lines.append("### 涉及文件（索引）")
    lines.append("")
    lines.append(files_list_md)
    lines.append("")

    lines.append("## 重点变更列表（按规则/规模排序，仅索引）")
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
                hunk = change.get("hunk_range", {}) or {}
                line_numbers = change.get("line_numbers") or {}
                location = (
                    line_numbers.get("new_compact")
                    or (f"(removed) {line_numbers.get('old_compact')}" if line_numbers.get("old_compact") else None)
                    or f"L{hunk.get('new_start')} (+{hunk.get('new_lines')})"
                )
                metrics = change.get("metrics", {}) or {}
                change_size = f"+{_safe_int(metrics.get('added_lines'))} / -{_safe_int(metrics.get('removed_lines'))}"
                tags = change.get("tags") or []
                tags_text = ", ".join(tags) if tags else "无特别标签"
                agent_decision = change.get("agent_decision") or {}
                ctx_level = agent_decision.get("context_level") or "function"
                priority = agent_decision.get("priority") or "medium"
                lines.append(
                    f"- 变更 {idx}：位置 {location}，规模 `{change_size}`，标签：{tags_text}，规则：{ctx_level}/{priority}"
                )
            lines.append("")

    # 嵌入精简 JSON 作为结构化视图（索引）
    lines.append("## 审查索引 JSON（精简，无 diff 正文）")
    lines.append("")
    note_parts: List[str] = [
        "下面是本次变更的结构化索引（去掉统一 diff/上下文，仅保留元数据），",
        "需要查看代码或上下文时，请通过工具调用获取。",
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
