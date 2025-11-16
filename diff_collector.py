"""Diff collector module for AI code review system."""

from __future__ import annotations

import argparse
import subprocess
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from unidiff import PatchSet


class DiffMode(str, Enum):
    """Supported diff modes."""

    WORKING = "working"
    STAGED = "staged"
    PR = "pr"
    AUTO = "auto"


_GIT_REPO_VERIFIED = False


def ensure_git_repository() -> None:
    """Ensure current directory is inside a git repository."""

    global _GIT_REPO_VERIFIED
    if _GIT_REPO_VERIFIED:
        return

    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or "Current directory is not a git repository."
        raise RuntimeError(f"Git repository check failed: {error}")

    _GIT_REPO_VERIFIED = True


def run_git(*args: str) -> str:
    """Run git command and return stdout."""

    ensure_git_repository()
    result = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        cmd = " ".join(["git", *args])
        raise RuntimeError(f"Git command failed ({cmd}): {stderr}")
    return result.stdout


def _run_git_quiet(*args: str) -> subprocess.CompletedProcess[str]:
    """Run git command where return code conveys status."""

    ensure_git_repository()
    return subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def has_working_changes() -> bool:
    """Return True if the working tree has unstaged changes."""

    result = _run_git_quiet("diff", "--quiet")
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --quiet failed."
    raise RuntimeError(error)


def has_staged_changes() -> bool:
    """Return True if the index has staged but uncommitted changes."""

    result = _run_git_quiet("diff", "--cached", "--quiet")
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --cached --quiet failed."
    raise RuntimeError(error)


def detect_base_branch() -> str:
    """Detect base branch name among commonly used defaults."""

    output = run_git("branch", "--list")
    branches = {
        line.replace("*", "").strip()
        for line in output.splitlines()
        if line.strip()
    }
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    raise RuntimeError("Unable to detect base branch (main/master not found).")


def branch_has_pr_changes(base_branch: str) -> bool:
    """Check if current HEAD is ahead of origin/<base_branch>."""

    try:
        run_git("fetch", "origin", base_branch)
    except RuntimeError:
        return False

    output = run_git(
        "rev-list",
        "--left-right",
        "--count",
        f"origin/{base_branch}...HEAD",
    ).strip()
    if not output:
        return False

    parts = output.split()
    if len(parts) < 2:
        return False

    try:
        ahead = int(parts[1])
    except ValueError:
        return False

    return ahead > 0


def auto_detect_mode() -> DiffMode:
    """Determine best diff mode based on repository state."""

    if has_staged_changes():
        return DiffMode.STAGED
    if has_working_changes():
        return DiffMode.WORKING

    base_branch = detect_base_branch()
    if branch_has_pr_changes(base_branch):
        return DiffMode.PR

    raise RuntimeError("No changes detected for working, staged, or PR diff modes.")


def get_diff_text(
    mode: DiffMode,
    base_branch: Optional[str] = None,
) -> Tuple[str, DiffMode, Optional[str]]:
    """Collect diff text for the requested mode."""

    if mode == DiffMode.AUTO:
        detected = auto_detect_mode()
        return get_diff_text(detected, base_branch)

    if mode == DiffMode.WORKING:
        return run_git("diff"), DiffMode.WORKING, None

    if mode == DiffMode.STAGED:
        return run_git("diff", "--cached"), DiffMode.STAGED, None

    if mode == DiffMode.PR:
        actual_base = base_branch or detect_base_branch()
        try:
            run_git("fetch", "origin", actual_base)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to fetch base branch '{actual_base}': {exc}"
            ) from exc
        diff_text = run_git("diff", f"origin/{actual_base}...HEAD")
        return diff_text, DiffMode.PR, actual_base

    raise ValueError(f"Unsupported diff mode: {mode}")


def read_file_lines(path: str) -> List[str]:
    """Read file contents into a list of lines without newline characters."""

    file_path = Path(path)
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8")
    return text.splitlines()


def extract_before_after_from_hunk(hunk) -> Tuple[str, str]:
    """Extract before and after snippets from a hunk."""

    before_lines: List[str] = []
    after_lines: List[str] = []
    for line in hunk:
        content = line.value.rstrip("\n")
        if line.line_type in ("-", " "):
            before_lines.append(content)
        if line.line_type in ("+", " "):
            after_lines.append(content)
    return "\n".join(before_lines), "\n".join(after_lines)


def extract_context(
    full_lines: List[str],
    new_start: int,
    new_end: int,
    before: int = 20,
    after: int = 20,
) -> Tuple[str, int, int]:
    """Extract surrounding context from the new file lines."""

    if not full_lines:
        ctx_start = new_start if new_start > 0 else 0
        ctx_end = new_end if new_end > 0 else ctx_start
        return "", ctx_start, ctx_end

    start_idx = max(1, new_start if new_start > 0 else 1)
    end_idx = max(start_idx, new_end if new_end > 0 else start_idx)
    ctx_start = max(1, start_idx - before)
    ctx_end = min(len(full_lines), end_idx + after)
    context_lines = full_lines[ctx_start - 1 : ctx_end]
    return "\n".join(context_lines), ctx_start, ctx_end


def guess_language(path: str) -> str:
    """Guess programming language based on file extension."""

    ext = Path(path).suffix.lower()
    if ext == ".py":
        return "python"
    if ext in {".js", ".ts", ".jsx", ".tsx"}:
        return "javascript"
    if ext == ".java":
        return "java"
    if ext == ".go":
        return "go"
    return "unknown"


def build_review_units_from_patch(patch: PatchSet) -> List[Dict[str, Any]]:
    """Build review units from PatchSet."""

    units: List[Dict[str, Any]] = []
    for patched_file in patch:
        if patched_file.is_removed_file:
            continue

        file_path = patched_file.path
        full_lines = read_file_lines(file_path)
        change_type = "add" if patched_file.is_added_file else "modify"
        language = guess_language(file_path)

        for hunk in patched_file:
            before_snippet, after_snippet = extract_before_after_from_hunk(hunk)

            new_start = hunk.target_start if hunk.target_start > 0 else 1
            if hunk.target_length > 0:
                new_end = new_start + hunk.target_length - 1
            else:
                new_end = new_start

            context_snippet, ctx_start, ctx_end = extract_context(
                full_lines, new_start, new_end
            )

            added_lines = sum(1 for line in hunk if line.line_type == "+")
            removed_lines = sum(1 for line in hunk if line.line_type == "-")

            units.append(
                {
                    "id": str(uuid.uuid4()),
                    "file_path": file_path,
                    "language": language,
                    "change_type": change_type,
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
                    "tags": [],
                    "metrics": {
                        "added_lines": added_lines,
                        "removed_lines": removed_lines,
                    },
                }
            )

    return units


def main() -> None:
    """CLI entry point."""

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


if __name__ == "__main__":
    main()
