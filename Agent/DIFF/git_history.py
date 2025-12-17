"""Git 提交历史模块：获取和格式化 Git 提交信息"""

from __future__ import annotations

import subprocess
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from Agent.DIFF.git_operations import run_git


_GIT_TIMEOUT_SECONDS = 60


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def get_commit_history(
    cwd: Optional[str] = None,
    limit: int = 20,
    skip: int = 0,
    branch: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    获取 Git 提交历史
    
    Args:
        cwd: Git 仓库路径
        limit: 返回的提交数量限制
        branch: 指定分支，None 表示当前分支
    
    Returns:
        提交历史列表，每个元素包含：
        - hash: 完整 commit hash
        - short_hash: 短 hash (7位)
        - author: 作者名
        - email: 作者邮箱
        - date: 提交时间 (ISO 8601)
        - relative_date: 相对时间
        - message: 提交信息
        - refs: 引用（分支、标签）
        - parents: 父提交列表
    """
    
    # Git log 格式化输出 - 使用 %x00 (NUL) 作为字段分隔符
    # %H: 完整 hash
    # %h: 短 hash
    # %an: 作者名
    # %ae: 作者邮箱
    # %aI: 作者日期 (ISO 8601)
    # %ar: 相对日期
    # %B: 完整提交消息（包含多行）
    # %P: 父提交 hash
    # %D: refs (HEAD, branches, tags)
    # 使用 %x00 分隔字段，%x01 分隔记录
    format_str = "%H%x00%h%x00%an%x00%ae%x00%aI%x00%ar%x00%B%x00%P%x00%D%x01"
    
    args = [
        "log",
        f"--max-count={limit}",
        f"--skip={skip}",
        f"--pretty=format:{format_str}",
    ]
    if branch:
        args.append(branch)

    try:
        output = run_git(args[0], *args[1:], cwd=cwd)
    except Exception as e:
        raise RuntimeError(f"Failed to get commit history: {e}")
    
    # 解析输出 - 使用 NUL 和 SOH 字符分隔
    commits = []
    # 按 %x01 (SOH) 分隔记录
    entries = output.split("\x01")
    
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        
        # 按 %x00 (NUL) 分隔字段
        fields = entry.split("\x00")
        if len(fields) < 7:
            continue
        
        commit_hash = fields[0] if len(fields) > 0 else ""
        short_hash = fields[1] if len(fields) > 1 else ""
        author = fields[2] if len(fields) > 2 else ""
        email = fields[3] if len(fields) > 3 else ""
        date_iso = fields[4] if len(fields) > 4 else ""
        relative_date = fields[5] if len(fields) > 5 else ""
        message = fields[6] if len(fields) > 6 else ""
        parents = fields[7].split() if len(fields) > 7 and fields[7].strip() else []
        refs = fields[8] if len(fields) > 8 else ""
        
        if not commit_hash:
            continue
        
        commits.append({
            "hash": commit_hash,
            "short_hash": short_hash,
            "author": author,
            "email": email,
            "date": date_iso,
            "relative_date": relative_date,
            "message": message,
            "parents": parents,
            "refs": refs,
            "is_merge": len(parents) > 1,
        })
    
    return commits


def get_branch_graph(
    cwd: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    获取分支图数据（用于可视化）
    
    Returns:
        {
            "commits": [...],  # 提交列表
            "branches": [...], # 分支列表
            "graph": [...]     # 图形数据（每个提交的连线信息）
        }
    """
    
    # 使用 git log --graph --all 获取可视化信息
    format_str = "%H%n%h%n%an%n%aI%n%ar%n%s%n%D%n---END---"
    
    try:
        # 获取提交历史
        commits = get_commit_history(cwd=cwd, limit=limit)
        
        branches = []
        branch_output = ""
        try:
            branch_output = run_git("branch", "-a", cwd=cwd)
        except Exception:
            branch_output = ""

        if branch_output:
            for line in branch_output.splitlines():
                line = line.strip()
                if not line or "HEAD" in line:
                    continue

                is_current = line.startswith("*")
                branch_name = line.replace("*", "").strip()

                # 移除 remotes/origin/ 前缀
                if branch_name.startswith("remotes/origin/"):
                    branch_name = branch_name.replace("remotes/origin/", "")
                    branch_type = "remote"
                else:
                    branch_type = "local"

                branches.append({
                    "name": branch_name,
                    "type": branch_type,
                    "is_current": is_current,
                })
        
        # 简化的图形数据（用于前端绘制）
        graph = []
        for i, commit in enumerate(commits):
            graph.append({
                "index": i,
                "hash": commit["short_hash"],
                "column": 0,  # 简化版：所有提交在同一列
                "has_parent": len(commit["parents"]) > 0,
                "is_merge": commit["is_merge"],
            })
        
        return {
            "commits": commits,
            "branches": branches,
            "graph": graph,
        }
        
    except Exception as e:
        raise RuntimeError(f"Failed to get branch graph: {e}")


def get_current_branch(cwd: Optional[str] = None) -> str:
    """获取当前分支名"""
    try:
        out = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd).strip()
        return out or "unknown"
    except Exception:
        return "unknown"
