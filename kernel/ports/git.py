"""Git 操作接口定义

定义与 Git 仓库交互的抽象接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable


class DiffMode(str, Enum):
    """Diff 模式"""
    STAGED = "staged"           # 暂存区变更
    UNSTAGED = "unstaged"       # 工作区变更
    BRANCH = "branch"           # 分支对比
    COMMIT = "commit"           # 提交对比
    WORKING = "working"         # 工作区 vs HEAD


@dataclass
class CommitInfo:
    """提交信息"""
    sha: str
    message: str
    author: str
    author_email: str
    date: str
    parent_shas: List[str] = field(default_factory=list)


@dataclass
class FileChange:
    """文件变更信息"""
    path: str
    old_path: Optional[str] = None  # 重命名时的原路径
    status: str = "modified"  # added, modified, deleted, renamed, copied
    additions: int = 0
    deletions: int = 0
    is_binary: bool = False


@dataclass
class DiffHunk:
    """Diff 块"""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: List[str]


@dataclass
class FileDiff:
    """单文件的 Diff 信息"""
    path: str
    old_path: Optional[str] = None
    status: str = "modified"
    hunks: List[DiffHunk] = field(default_factory=list)
    is_binary: bool = False
    old_mode: Optional[str] = None
    new_mode: Optional[str] = None


@dataclass
class DiffResult:
    """Diff 结果"""
    mode: DiffMode
    base_ref: Optional[str] = None  # 基准提交/分支
    head_ref: Optional[str] = None  # 目标提交/分支
    files: List[FileDiff] = field(default_factory=list)
    raw_diff: Optional[str] = None  # 原始 diff 文本
    stats: Optional[Dict[str, int]] = None  # files_changed, insertions, deletions


@dataclass
class GitConfig:
    """Git 配置"""
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    remote_url: Optional[str] = None
    current_branch: Optional[str] = None
    default_branch: Optional[str] = None


@runtime_checkable
class GitPort(Protocol):
    """Git 操作接口
    
    定义与 Git 仓库交互的标准接口。
    所有操作都相对于指定的仓库根目录。
    """
    
    def run_git(
        self,
        args: List[str],
        *,
        cwd: Optional[str] = None,
        capture_output: bool = True,
        check: bool = True,
    ) -> Tuple[str, str, int]:
        """运行 Git 命令
        
        Args:
            args: Git 命令参数（不包含 'git' 本身）
            cwd: 工作目录，默认为仓库根目录
            capture_output: 是否捕获输出
            check: 是否检查返回码
            
        Returns:
            (stdout, stderr, return_code) 元组
        """
        ...
    
    def get_diff(
        self,
        mode: DiffMode,
        *,
        cwd: Optional[str] = None,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
        paths: Optional[List[str]] = None,
        context_lines: int = 3,
    ) -> DiffResult:
        """获取 Diff
        
        Args:
            mode: Diff 模式
            cwd: 仓库目录
            base_ref: 基准引用（用于 BRANCH/COMMIT 模式）
            head_ref: 目标引用（用于 BRANCH/COMMIT 模式）
            paths: 限定的文件路径列表
            context_lines: 上下文行数
            
        Returns:
            结构化的 Diff 结果
        """
        ...
    
    def get_diff_text(
        self,
        mode: DiffMode,
        *,
        cwd: Optional[str] = None,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
        paths: Optional[List[str]] = None,
        context_lines: int = 3,
    ) -> str:
        """获取原始 Diff 文本
        
        与 get_diff 类似，但返回原始文本而非结构化数据。
        """
        ...
    
    def get_commit(
        self,
        ref: str = "HEAD",
        *,
        cwd: Optional[str] = None,
    ) -> CommitInfo:
        """获取提交信息"""
        ...
    
    def get_commit_history(
        self,
        *,
        cwd: Optional[str] = None,
        ref: str = "HEAD",
        limit: int = 10,
        paths: Optional[List[str]] = None,
    ) -> List[CommitInfo]:
        """获取提交历史"""
        ...
    
    def get_file_at_ref(
        self,
        path: str,
        ref: str = "HEAD",
        *,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """获取指定版本的文件内容"""
        ...
    
    def get_changed_files(
        self,
        mode: DiffMode,
        *,
        cwd: Optional[str] = None,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
    ) -> List[FileChange]:
        """获取变更文件列表"""
        ...
    
    def get_config(self, cwd: Optional[str] = None) -> GitConfig:
        """获取 Git 配置信息"""
        ...
    
    def get_current_branch(self, cwd: Optional[str] = None) -> Optional[str]:
        """获取当前分支名"""
        ...
    
    def get_remote_url(
        self,
        remote: str = "origin",
        *,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """获取远程仓库 URL"""
        ...
    
    def is_git_repo(self, path: str) -> bool:
        """检查路径是否为 Git 仓库"""
        ...
    
    def get_repo_root(self, path: str) -> Optional[str]:
        """获取仓库根目录"""
        ...
