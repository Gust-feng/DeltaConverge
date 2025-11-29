"""Git 操作模块：处理 Git 仓库检测、diff 获取、分支管理等。"""

from __future__ import annotations

import subprocess
from enum import Enum
from typing import Optional, Tuple


class DiffMode(str, Enum):
    """支持的 diff 模式。"""

    WORKING = "working"
    STAGED = "staged"
    PR = "pr"
    AUTO = "auto"


_GIT_REPO_VERIFIED = False


def ensure_git_repository() -> None:
    """确保当前目录在 git 仓库内，否则拒绝继续。"""

    global _GIT_REPO_VERIFIED
    if _GIT_REPO_VERIFIED:
        return

    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or "Current directory is not a git repository."
        raise RuntimeError(f"Git repository check failed: {error}")

    _GIT_REPO_VERIFIED = True


def run_git(*args: str) -> str:
    """运行 git 命令并返回标准输出。"""

    ensure_git_repository()
    result = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        cmd = " ".join(["git", *args])
        raise RuntimeError(f"Git command failed ({cmd}): {stderr}")
    return result.stdout


def _run_git_quiet(*args: str) -> subprocess.CompletedProcess[str]:
    """运行 git 命令并通过返回码传递状态。"""

    ensure_git_repository()
    return subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        check=False,
    )

def has_working_changes() -> bool:
    """如果工作区有未暂存变更则返回 True。"""

    result = _run_git_quiet("diff", "--quiet")
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --quiet failed."
    raise RuntimeError(error)


def has_staged_changes() -> bool:
    """如果暂存区存在未提交变更则返回 True。"""

    result = _run_git_quiet("diff", "--cached", "--quiet")
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --cached --quiet failed."
    raise RuntimeError(error)


def detect_base_branch() -> str:
    """在常见默认分支中检测基线分支名称。"""

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
    """检查当前 HEAD 是否领先于 origin/<base_branch>。"""

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
    """根据仓库状态决定最佳 diff 模式。"""

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
    """按模式获取 diff 文本，返回实际模式与基线分支。"""

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
