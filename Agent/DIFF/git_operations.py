"""Git 操作模块：处理 Git 仓库检测、diff 获取、分支管理等。"""

from __future__ import annotations

import subprocess
from enum import Enum
from typing import Optional, Tuple
from pathlib import Path


class DiffMode(str, Enum):
    """支持的 diff 模式。"""

    WORKING = "working"
    STAGED = "staged"
    PR = "pr"
    AUTO = "auto"


def ensure_git_repository(cwd: Optional[str] = None) -> None:
    """确保指定目录（或当前目录）在 git 仓库内，否则拒绝继续。"""
    
    # 移除全局状态 _GIT_REPO_VERIFIED 的简单检查，因为 cwd 可能会变
    # 为了鲁棒性，每次都检查，或者基于 (cwd, verified) 做缓存。
    # 这里为了简化且安全，每次调用 git 前都检查一次其实开销极小（git rev-parse 很快）。
    
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or "Current directory is not a git repository."
            raise RuntimeError(f"Git repository check failed: {error} (cwd={cwd or 'current'})")
    except FileNotFoundError:
         raise RuntimeError("Git executable not found in PATH.")
    except Exception as e:
         raise RuntimeError(f"Failed to check git repository: {e}")


def run_git(command: str, *args: str, cwd: Optional[str] = None) -> str:
    """运行 git 命令并返回标准输出。"""
    
    # 显式参数 command 避免解包混淆
    ensure_git_repository(cwd)
    
    # 添加 -c core.quotepath=false 确保中文路径不被转义
    full_cmd = ["git", "-c", "core.quotepath=false", command, *args]
    
    try:
        # 不使用 text=True 或 encoding，直接获取 bytes
        result = subprocess.run(
            full_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to execute git command: {e}")

    if result.returncode != 0:
        # 尝试解码 stderr
        stderr = _decode_output(result.stderr).strip()
        cmd_str = " ".join(full_cmd)
        raise RuntimeError(f"Git command failed ({cmd_str}): {stderr}")
    
    return _decode_output(result.stdout)


def _decode_output(data: bytes) -> str:
    """尝试多种编码解码输出。"""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            # 尝试本地编码 (Windows通常是cp936/gbk)
            import locale
            return data.decode(locale.getpreferredencoding(), errors="replace")
        except Exception:
            # 最后的兜底
            return data.decode("utf-8", errors="replace")


def _run_git_quiet(command: str, *args: str, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    """运行 git 命令并通过返回码传递状态。"""

    ensure_git_repository(cwd)
    # 同样移除 encoding 参数，避免解码错误导致崩溃
    # 添加 -c core.quotepath=false 保持一致性
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", command, *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def has_working_changes(cwd: Optional[str] = None) -> bool:
    """如果工作区有未暂存变更则返回 True。"""

    result = _run_git_quiet("diff", "--quiet", cwd=cwd)
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --quiet failed."
    raise RuntimeError(error)


def has_staged_changes(cwd: Optional[str] = None) -> bool:
    """如果暂存区存在未提交变更则返回 True。"""

    result = _run_git_quiet("diff", "--cached", "--quiet", cwd=cwd)
    if result.returncode in (0, 1):
        return result.returncode == 1
    error = result.stderr.strip() or "git diff --cached --quiet failed."
    raise RuntimeError(error)


def detect_base_branch(cwd: Optional[str] = None) -> str:
    """在常见默认分支中检测基线分支名称。"""

    output = run_git("branch", "--list", cwd=cwd)
    branches = {
        line.replace("*", "").strip()
        for line in output.splitlines()
        if line.strip()
    }
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    # 尝试远程分支
    output_remote = run_git("branch", "-r", cwd=cwd)
    remote_branches = {
        line.strip().replace("origin/", "")
        for line in output_remote.splitlines()
        if line.strip()
    }
    if "main" in remote_branches:
        return "main"
    if "master" in remote_branches:
        return "master"
        
    raise RuntimeError("Unable to detect base branch (main/master not found).")


def branch_has_pr_changes(base_branch: str, cwd: Optional[str] = None) -> bool:
    """检查当前 HEAD 是否领先于 origin/<base_branch>。"""

    try:
        run_git("fetch", "origin", base_branch, cwd=cwd)
    except RuntimeError:
        return False

    output = run_git(
        "rev-list",
        "--left-right",
        "--count",
        f"origin/{base_branch}...HEAD",
        cwd=cwd,
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


def auto_detect_mode(cwd: Optional[str] = None) -> DiffMode:
    """根据仓库状态决定最佳 diff 模式。"""

    if has_staged_changes(cwd=cwd):
        return DiffMode.STAGED
    if has_working_changes(cwd=cwd):
        return DiffMode.WORKING

    try:
        base_branch = detect_base_branch(cwd=cwd)
        if branch_has_pr_changes(base_branch, cwd=cwd):
            return DiffMode.PR
    except RuntimeError:
        pass

    raise RuntimeError("No changes detected for working, staged, or PR diff modes.")


def get_diff_text(
    mode: DiffMode,
    base_branch: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Tuple[str, DiffMode, Optional[str]]:
    """按模式获取 diff 文本，返回实际模式与基线分支。"""

    if mode == DiffMode.AUTO:
        detected = auto_detect_mode(cwd=cwd)
        return get_diff_text(detected, base_branch, cwd=cwd)

    if mode == DiffMode.WORKING:
        return run_git("diff", cwd=cwd), DiffMode.WORKING, None

    if mode == DiffMode.STAGED:
        return run_git("diff", "--cached", cwd=cwd), DiffMode.STAGED, None

    if mode == DiffMode.PR:
        actual_base = base_branch or detect_base_branch(cwd=cwd)
        try:
            run_git("fetch", "origin", actual_base, cwd=cwd)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to fetch base branch '{actual_base}': {exc}"
            ) from exc
        diff_text = run_git("diff", f"origin/{actual_base}...HEAD", cwd=cwd)
        return diff_text, DiffMode.PR, actual_base

    raise ValueError(f"Unsupported diff mode: {mode}")
