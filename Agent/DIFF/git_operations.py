"""Git 操作模块：处理 Git 仓库检测、diff 获取、分支管理等。"""

from __future__ import annotations

import subprocess
import os
from enum import Enum
from typing import Optional, Tuple
from pathlib import Path


_GIT_TIMEOUT_SECONDS = 60


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def _allow_unsafe_git_repo() -> bool:
    raw = os.getenv("GIT_ALLOW_UNSAFE_REPOS")
    if raw is not None:
        return str(raw).lower() in ("1", "true", "yes", "on")
    flags = (
        os.environ.get("RUNNING_IN_DOCKER"),
        os.environ.get("DOCKER"),
        os.environ.get("IS_DOCKER"),
    )
    return any(f for f in flags if str(f).lower() in ("1", "true", "yes"))


class DiffMode(str, Enum):
    """支持的 diff 模式。"""

    WORKING = "working"
    STAGED = "staged"
    PR = "pr"
    COMMIT = "commit"  # 新增: 审查特定commit范围
    AUTO = "auto"


def ensure_git_repository(cwd: Optional[str] = None) -> None:
    """确保指定目录（或当前目录）在 git 仓库内，否则拒绝继续。"""
    
    # 移除全局状态 _GIT_REPO_VERIFIED 的简单检查，因为 cwd 可能会变
    # 为了鲁棒性，每次都检查，或者基于 (cwd, verified) 做缓存。
    # 这里为了简化且安全，每次调用 git 前都检查一次其实开销极小（git rev-parse 很快）。
    
    try:
        cmd = ["git"]
        if _allow_unsafe_git_repo():
            cmd.extend(["-c", "safe.directory=*"])
        cmd.extend(["rev-parse", "--is-inside-work-tree"])
        result = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
        if result.returncode != 0:
            # 宽容解码错误，避免中文路径或本地编码导致崩溃
            try:
                stderr_text = result.stderr.decode("utf-8") if isinstance(result.stderr, (bytes, bytearray)) else str(result.stderr)
            except Exception:
                try:
                    import locale
                    stderr_text = result.stderr.decode(locale.getpreferredencoding(), errors="replace")
                except Exception:
                    stderr_text = str(result.stderr)
            error = (stderr_text or "Current directory is not a git repository.").strip()
            raise RuntimeError(f"Git repository check failed: {error} (cwd={cwd or 'current'})")
    except FileNotFoundError:
         raise RuntimeError("Git executable not found in PATH.")
    except Exception as e:
         raise RuntimeError(f"Failed to check git repository: {e}")


def run_git(command: str, *args: str, cwd: Optional[str] = None) -> str:
    """运行 git 命令并返回标准输出。"""
    
    # 显式参数 command 避免解包混淆
    ensure_git_repository(cwd)
    
    full_cmd = ["git", "-c", "core.quotepath=false"]
    if _allow_unsafe_git_repo():
        full_cmd.extend(["-c", "safe.directory=*"])
    full_cmd.extend([command, *args])
    
    try:
        # 不使用 text=True 或 encoding，直接获取 bytes
        result = subprocess.run(
            full_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
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
    cmd = ["git", "-c", "core.quotepath=false"]
    if _allow_unsafe_git_repo():
        cmd.extend(["-c", "safe.directory=*"])
    cmd.extend([command, *args])
    return subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=_GIT_TIMEOUT_SECONDS,
        env=_git_env(),
    )


def has_working_changes(cwd: Optional[str] = None) -> bool:
    """如果工作区有未暂存变更（包括未跟踪文件）则返回 True。"""

    # 检查已跟踪文件的未暂存变更
    result = _run_git_quiet("diff", "--quiet", cwd=cwd)
    if result.returncode == 1:
        return True
    
    # 检查未跟踪的新文件
    untracked_result = _run_git_quiet("status", "--porcelain", cwd=cwd)
    if untracked_result.returncode == 0:
        output = untracked_result.stdout
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        # 检查是否有未跟踪文件（以 ?? 开头的行）
        for line in output.splitlines():
            if line.startswith("??"):
                return True
    
    return False


def get_remote_name(cwd: Optional[str] = None) -> str:
    """动态获取远程仓库名称(优先origin,否则使用第一个可用的远程)。"""
    
    try:
        output = run_git("remote", cwd=cwd)
        remotes = [r.strip() for r in output.splitlines() if r.strip()]
        
        if not remotes:
            return "origin"  # 默认回退
        
        # 优先使用origin
        if "origin" in remotes:
            return "origin"
        
        # 否则使用第一个可用的远程
        return remotes[0]
    except RuntimeError:
        return "origin"  # 出错时回退到默认值


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
    """检查当前 HEAD 是否领先于远程base_branch。"""
    
    remote = get_remote_name(cwd=cwd)
    remote_ref = f"{remote}/{base_branch}"

    try:
        run_git("rev-parse", "--verify", remote_ref, cwd=cwd)
    except RuntimeError:
        return False

    output = run_git(
        "rev-list",
        "--left-right",
        "--count",
        f"{remote_ref}...HEAD",
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

    raise RuntimeError("未检测到工作区、暂存或拉取请求差异模式中的更改:)")


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
        return run_git("diff", "-M", cwd=cwd), DiffMode.WORKING, None

    if mode == DiffMode.STAGED:
        return run_git("diff", "--cached", "-M", cwd=cwd), DiffMode.STAGED, None

    if mode == DiffMode.PR:
        actual_base = base_branch or detect_base_branch(cwd=cwd)
        remote = get_remote_name(cwd=cwd)
        base_ref: Optional[str] = None
        
        # 尝试远程分支
        try:
            run_git("rev-parse", "--verify", f"{remote}/{actual_base}", cwd=cwd)
            base_ref = f"{remote}/{actual_base}"
        except RuntimeError:
            pass
        
        # 尝试本地分支
        if base_ref is None:
            try:
                run_git("rev-parse", "--verify", actual_base, cwd=cwd)
                base_ref = actual_base
            except RuntimeError as exc:
                raise RuntimeError(
                f"Base branch '{actual_base}' not found locally or in "
                    f"remote '{remote}'."
                ) from exc
        
        diff_text = run_git("diff", "-M", f"{base_ref}...HEAD", cwd=cwd)
        return diff_text, DiffMode.PR, actual_base

    # COMMIT模式不在这里处理,需要通过专用函数get_commit_diff处理
    raise ValueError(f"Unsupported diff mode: {mode}")


def get_commit_diff(
    commit_from: str,
    commit_to: Optional[str] = None,
    cwd: Optional[str] = None,
    use_merge_base: bool = True,
) -> str:
    """获取指定commit范围的diff。
    
    Args:
        commit_from: 起始commit (base commit)
        commit_to: 结束commit (head commit), 默认为HEAD
        cwd: 工作目录
        use_merge_base: 是否使用 merge-base 计算差异（推荐用于 PR 审查）
                       True: 只显示从公共祖先到 head 的变更（PR 的真实变更）
                       False: 显示两个 commit 之间的所有差异
        
    Returns:
        diff文本
    """
    if not commit_from:
        raise ValueError("commit_from is required")
    
    commit_to = commit_to or "HEAD"
    
    # 验证commit是否存在
    try:
        run_git("rev-parse", "--verify", commit_from, cwd=cwd)
    except RuntimeError as e:
        raise RuntimeError(f"Invalid commit: {commit_from}") from e
    
    if commit_to != "HEAD":
        try:
            run_git("rev-parse", "--verify", commit_to, cwd=cwd)
        except RuntimeError as e:
            raise RuntimeError(f"Invalid commit: {commit_to}") from e
    
    # 获取diff
    if use_merge_base:
        # 使用 merge-base 方式：只显示 PR/分支 引入的变更
        # 这等价于 git diff commit_from...commit_to
        try:
            merge_base = run_git("merge-base", commit_from, commit_to, cwd=cwd).strip()
            diff_text = run_git("diff", "-M", merge_base, commit_to, cwd=cwd)
        except RuntimeError:
            # 如果 merge-base 失败（比如没有公共祖先），退回到直接比较
            diff_text = run_git("diff", "-M", commit_from, commit_to, cwd=cwd)
    else:
        # 直接比较两个 commit（传统方式）
        diff_text = run_git("diff", "-M", commit_from, commit_to, cwd=cwd)
    
    return diff_text


# =============================================================================
# PR 提交相关的 Git 操作
# =============================================================================

def get_current_branch(cwd: Optional[str] = None) -> str:
    """获取当前分支名称。
    
    Args:
        cwd: 工作目录
        
    Returns:
        当前分支名称
    """
    return run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).strip()


def branch_exists(branch_name: str, cwd: Optional[str] = None, remote: bool = False) -> bool:
    """检查分支是否存在。
    
    Args:
        branch_name: 分支名称
        cwd: 工作目录
        remote: 是否检查远程分支
        
    Returns:
        分支是否存在
    """
    try:
        if remote:
            remote_name = get_remote_name(cwd=cwd)
            run_git("rev-parse", "--verify", f"refs/remotes/{remote_name}/{branch_name}", cwd=cwd)
        else:
            run_git("rev-parse", "--verify", f"refs/heads/{branch_name}", cwd=cwd)
        return True
    except RuntimeError:
        return False


def create_branch(branch_name: str, cwd: Optional[str] = None, base: Optional[str] = None) -> None:
    """创建新分支。
    
    Args:
        branch_name: 新分支名称
        cwd: 工作目录
        base: 可选的基础提交/分支，默认为当前HEAD
        
    Raises:
        RuntimeError: 如果分支已存在或创建失败
    """
    if branch_exists(branch_name, cwd=cwd):
        raise RuntimeError(f"Branch '{branch_name}' already exists")
    
    if base:
        run_git("branch", branch_name, base, cwd=cwd)
    else:
        run_git("branch", branch_name, cwd=cwd)


def checkout_branch(branch_name: str, cwd: Optional[str] = None, create: bool = False) -> None:
    """切换到指定分支。
    
    Args:
        branch_name: 分支名称
        cwd: 工作目录
        create: 如果为True，则创建新分支并切换（相当于 git checkout -b）
        
    Raises:
        RuntimeError: 如果切换失败
    """
    if create:
        run_git("checkout", "-b", branch_name, cwd=cwd)
    else:
        run_git("checkout", branch_name, cwd=cwd)


def push_branch(
    branch_name: str,
    cwd: Optional[str] = None,
    remote: Optional[str] = None,
    force: bool = False,
    set_upstream: bool = True
) -> None:
    """推送分支到远程仓库。
    
    Args:
        branch_name: 分支名称
        cwd: 工作目录
        remote: 远程仓库名称，默认自动检测
        force: 是否强制推送
        set_upstream: 是否设置上游分支
        
    Raises:
        RuntimeError: 如果推送失败
    """
    remote_name = remote or get_remote_name(cwd=cwd)
    
    args = ["push"]
    if set_upstream:
        args.extend(["-u"])
    if force:
        args.extend(["--force"])
    args.extend([remote_name, branch_name])
    
    run_git(*args, cwd=cwd)


def add_files(files: list[str], cwd: Optional[str] = None, all_files: bool = False) -> None:
    """添加文件到暂存区。
    
    Args:
        files: 文件路径列表
        cwd: 工作目录
        all_files: 如果为True，添加所有变更的文件
        
    Raises:
        RuntimeError: 如果添加失败
    """
    if all_files:
        run_git("add", "-A", cwd=cwd)
    elif files:
        run_git("add", "--", *files, cwd=cwd)


def commit_changes(message: str, cwd: Optional[str] = None, allow_empty: bool = False) -> str:
    """提交暂存区的变更。
    
    Args:
        message: 提交信息
        cwd: 工作目录
        allow_empty: 是否允许空提交
        
    Returns:
        新提交的SHA
        
    Raises:
        RuntimeError: 如果提交失败
    """
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    
    run_git(*args, cwd=cwd)
    
    # 返回新提交的SHA
    return run_git("rev-parse", "HEAD", cwd=cwd).strip()


def stash_changes(cwd: Optional[str] = None) -> bool:
    """将当前工作区变更存储到stash。
    
    Args:
        cwd: 工作目录
        
    Returns:
        是否存储了变更（如果没有变更则返回False）
    """
    result = _run_git_quiet("stash", "push", "-m", "Auto stash before PR operation", cwd=cwd)
    # 如果stash成功且有内容被存储
    return result.returncode == 0 and b"No local changes" not in result.stdout


def stash_pop(cwd: Optional[str] = None) -> None:
    """恢复最近的stash。
    
    Args:
        cwd: 工作目录
    """
    run_git("stash", "pop", cwd=cwd)


def get_remote_url(cwd: Optional[str] = None, remote: Optional[str] = None) -> Optional[str]:
    """获取远程仓库URL。
    
    Args:
        cwd: 工作目录
        remote: 远程仓库名称，默认自动检测
        
    Returns:
        远程仓库URL，如果不存在则返回None
    """
    remote_name = remote or get_remote_name(cwd=cwd)
    try:
        return run_git("config", "--get", f"remote.{remote_name}.url", cwd=cwd).strip()
    except RuntimeError:
        return None


def parse_github_remote_url(url: str) -> Optional[Tuple[str, str]]:
    """从GitHub远程URL解析owner和repo。
    
    Args:
        url: GitHub远程URL（支持HTTPS和SSH格式）
        
    Returns:
        (owner, repo) 元组，如果解析失败则返回None
    """
    import re
    
    # SSH格式: git@github.com:owner/repo.git
    ssh_pattern = r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$"
    match = re.match(ssh_pattern, url)
    if match:
        return (match.group(1), match.group(2))
    
    # HTTPS格式: https://github.com/owner/repo.git
    https_pattern = r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$"
    match = re.match(https_pattern, url)
    if match:
        return (match.group(1), match.group(2))
    
    return None

