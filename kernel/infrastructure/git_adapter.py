"""Legacy Git 操作适配器

包装旧内核的 git_operations 模块，实现新的 GitPort 接口。
"""
from __future__ import annotations

import logging
import subprocess
from typing import List, Optional, Tuple

from kernel.ports.git import (
    CommitInfo,
    DiffMode,
    DiffResult,
    FileChange,
    FileDiff,
    GitConfig,
    GitPort,
)

logger = logging.getLogger(__name__)


class LegacyGitAdapter(GitPort):
    """包装旧 Git 操作的适配器"""
    
    def __init__(self, default_cwd: Optional[str] = None) -> None:
        self._default_cwd = default_cwd
    
    def run_git(
        self,
        args: List[str],
        *,
        cwd: Optional[str] = None,
        capture_output: bool = True,
        check: bool = True,
    ) -> Tuple[str, str, int]:
        """运行 Git 命令"""
        work_dir = cwd or self._default_cwd
        cmd = ["git"] + args
        
        try:
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=capture_output,
                text=True,
                check=check,
            )
            return (result.stdout, result.stderr, result.returncode)
        except subprocess.CalledProcessError as e:
            if check:
                raise
            return (e.stdout or "", e.stderr or "", e.returncode)
    
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
        """获取 Diff"""
        diff_text = self.get_diff_text(
            mode,
            cwd=cwd,
            base_ref=base_ref,
            head_ref=head_ref,
            paths=paths,
            context_lines=context_lines,
        )
        
        # 简化实现：返回原始 diff
        return DiffResult(
            mode=mode,
            base_ref=base_ref,
            head_ref=head_ref,
            raw_diff=diff_text,
        )
    
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
        """获取原始 Diff 文本"""
        from Agent.DIFF.git_operations import get_commit_diff, DiffMode as LegacyDiffMode
        
        work_dir = cwd or self._default_cwd
        
        # 转换 DiffMode
        legacy_mode_map = {
            DiffMode.STAGED: LegacyDiffMode.STAGED,
            DiffMode.UNSTAGED: LegacyDiffMode.UNSTAGED,
            DiffMode.BRANCH: LegacyDiffMode.BRANCH,
            DiffMode.COMMIT: LegacyDiffMode.COMMIT,
            DiffMode.WORKING: LegacyDiffMode.WORKING,
        }
        legacy_mode = legacy_mode_map.get(mode, LegacyDiffMode.WORKING)
        
        return get_commit_diff(
            from_ref=base_ref or "",
            to_ref=head_ref or "",
            mode=legacy_mode,
            cwd=work_dir,
        )
    
    def get_commit(
        self,
        ref: str = "HEAD",
        *,
        cwd: Optional[str] = None,
    ) -> CommitInfo:
        """获取提交信息"""
        work_dir = cwd or self._default_cwd
        
        # 获取提交信息
        stdout, _, _ = self.run_git(
            ["show", "--no-patch", "--format=%H%n%s%n%an%n%ae%n%ai%n%P", ref],
            cwd=work_dir,
        )
        
        lines = stdout.strip().split("\n")
        return CommitInfo(
            sha=lines[0] if len(lines) > 0 else "",
            message=lines[1] if len(lines) > 1 else "",
            author=lines[2] if len(lines) > 2 else "",
            author_email=lines[3] if len(lines) > 3 else "",
            date=lines[4] if len(lines) > 4 else "",
            parent_shas=lines[5].split() if len(lines) > 5 else [],
        )
    
    def get_commit_history(
        self,
        *,
        cwd: Optional[str] = None,
        ref: str = "HEAD",
        limit: int = 10,
        paths: Optional[List[str]] = None,
    ) -> List[CommitInfo]:
        """获取提交历史"""
        work_dir = cwd or self._default_cwd
        
        args = [
            "log",
            f"-{limit}",
            "--format=%H%x00%s%x00%an%x00%ae%x00%ai%x00%P%x00",
            ref,
        ]
        if paths:
            args.extend(["--"] + paths)
        
        stdout, _, _ = self.run_git(args, cwd=work_dir)
        
        commits = []
        for line in stdout.strip().split("\x00\n"):
            if not line:
                continue
            parts = line.split("\x00")
            if len(parts) >= 6:
                commits.append(
                    CommitInfo(
                        sha=parts[0],
                        message=parts[1],
                        author=parts[2],
                        author_email=parts[3],
                        date=parts[4],
                        parent_shas=parts[5].split() if parts[5] else [],
                    )
                )
        
        return commits
    
    def get_file_at_ref(
        self,
        path: str,
        ref: str = "HEAD",
        *,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """获取指定版本的文件内容"""
        work_dir = cwd or self._default_cwd
        
        try:
            stdout, _, _ = self.run_git(
                ["show", f"{ref}:{path}"],
                cwd=work_dir,
            )
            return stdout
        except Exception:
            return None
    
    def get_changed_files(
        self,
        mode: DiffMode,
        *,
        cwd: Optional[str] = None,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
    ) -> List[FileChange]:
        """获取变更文件列表"""
        work_dir = cwd or self._default_cwd
        
        if mode == DiffMode.STAGED:
            args = ["diff", "--cached", "--name-status"]
        elif mode == DiffMode.UNSTAGED:
            args = ["diff", "--name-status"]
        elif mode == DiffMode.WORKING:
            args = ["diff", "HEAD", "--name-status"]
        elif mode in (DiffMode.BRANCH, DiffMode.COMMIT):
            args = ["diff", "--name-status", base_ref or "HEAD", head_ref or "HEAD"]
        else:
            args = ["diff", "--name-status"]
        
        stdout, _, _ = self.run_git(args, cwd=work_dir)
        
        changes = []
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0][0]
                path = parts[1]
                old_path = parts[2] if len(parts) > 2 else None
                
                status_map = {
                    "A": "added",
                    "M": "modified",
                    "D": "deleted",
                    "R": "renamed",
                    "C": "copied",
                }
                
                changes.append(
                    FileChange(
                        path=path,
                        old_path=old_path,
                        status=status_map.get(status, "modified"),
                    )
                )
        
        return changes
    
    def get_config(self, cwd: Optional[str] = None) -> GitConfig:
        """获取 Git 配置信息"""
        work_dir = cwd or self._default_cwd
        
        config = GitConfig()
        
        try:
            stdout, _, _ = self.run_git(["config", "user.name"], cwd=work_dir, check=False)
            config.user_name = stdout.strip() if stdout else None
        except Exception:
            pass
        
        try:
            stdout, _, _ = self.run_git(["config", "user.email"], cwd=work_dir, check=False)
            config.user_email = stdout.strip() if stdout else None
        except Exception:
            pass
        
        config.current_branch = self.get_current_branch(work_dir)
        config.remote_url = self.get_remote_url(cwd=work_dir)
        
        return config
    
    def get_current_branch(self, cwd: Optional[str] = None) -> Optional[str]:
        """获取当前分支名"""
        work_dir = cwd or self._default_cwd
        
        try:
            stdout, _, _ = self.run_git(["branch", "--show-current"], cwd=work_dir)
            return stdout.strip() if stdout else None
        except Exception:
            return None
    
    def get_remote_url(
        self,
        remote: str = "origin",
        *,
        cwd: Optional[str] = None,
    ) -> Optional[str]:
        """获取远程仓库 URL"""
        work_dir = cwd or self._default_cwd
        
        try:
            stdout, _, _ = self.run_git(["remote", "get-url", remote], cwd=work_dir, check=False)
            return stdout.strip() if stdout else None
        except Exception:
            return None
    
    def is_git_repo(self, path: str) -> bool:
        """检查路径是否为 Git 仓库"""
        try:
            self.run_git(["rev-parse", "--git-dir"], cwd=path)
            return True
        except Exception:
            return False
    
    def get_repo_root(self, path: str) -> Optional[str]:
        """获取仓库根目录"""
        try:
            stdout, _, _ = self.run_git(["rev-parse", "--show-toplevel"], cwd=path)
            return stdout.strip() if stdout else None
        except Exception:
            return None
