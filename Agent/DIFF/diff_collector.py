"""Diff 感知层：收集 git diff、解析 PatchSet 并构建审查单元供后续规划/审查使用。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from unidiff import PatchSet

import sys
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Agent.core.logging.fallback_tracker import fallback_tracker, record_fallback

# 导入拆分后的模块
from Agent.DIFF.git_operations import (
    DiffMode,
    get_diff_text,
)
from Agent.DIFF.review_units import (
    build_review_units_from_patch,
)
from Agent.DIFF.output_formatting import (
    build_review_index,
    build_llm_friendly_output,
)


def main() -> None:
    """CLI 入口。"""

    fallback_tracker.reset()
    parser = argparse.ArgumentParser(
        description="AI Code Review - Diff Collector"
    )
    parser.add_argument(
        "--mode",
        choices=[m.value for m in DiffMode],
        default=DiffMode.AUTO.value,
        help="diff 模式：working / staged / pr / auto（默认 auto）",
    )
    args = parser.parse_args()

    mode = DiffMode(args.mode)

    try:
        diff_text, actual_mode, base = get_diff_text(mode)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)

    print(f"[感知层] 使用模式: {actual_mode.value}")
    if actual_mode == DiffMode.PR and base is not None:
        print(f"[感知层] 基线分支: {base} (origin/{base}...HEAD)")

    if not diff_text.strip():
        print("没有检测到任何变更。")
        raise SystemExit(0)

    patch = PatchSet(diff_text)
    units = build_review_units_from_patch(patch)
    print(f"[感知层] 构建审查单元数量: {len(units)}")

    if units:
        llm_friendly_output = build_llm_friendly_output(units, actual_mode, base)

        log_dir = Path("log") / "diff_log"
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        llm_output_file = log_dir / f"review_for_llm_{timestamp}.json"
        raw_output_file = log_dir / f"review_raw_{timestamp}.json"

        with open(llm_output_file, "w", encoding="utf-8") as f:
            json.dump(llm_friendly_output, f, ensure_ascii=False, indent=2)

        with open(raw_output_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mode": actual_mode.value,
                    "base_branch": base,
                    "total_units": len(units),
                    "units": units,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        print(f"\n[感知层] 已保存 LLM 友好格式: {llm_output_file}")
        print(f"[感知层] 已保存原始格式: {raw_output_file}")
        
        # 打印摘要
        print(f"\n[摘要] 变更概览：")
        print(f"  - 修改文件数: {llm_friendly_output['summary']['changes_by_type']['modify']}")
        print(f"  - 新增文件数: {llm_friendly_output['summary']['changes_by_type']['add']}")
        print(f"  - 总新增行: +{llm_friendly_output['summary']['total_lines']['added']}")
        print(f"  - 总删除行: -{llm_friendly_output['summary']['total_lines']['removed']}")
        fb_summary = fallback_tracker.emit_summary()
        if fb_summary.get("total"):
            print(f"\n[回退告警] 本次触发 {fb_summary['total']} 次：{fb_summary['by_key']}")


if __name__ == "__main__":
    main()
