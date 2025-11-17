"""Utilities to collect diff-based context for prompts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

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
