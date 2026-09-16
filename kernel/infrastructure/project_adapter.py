"""Legacy 项目信息与 Diff 查询适配器

包装旧内核的 ``Agent.core.api.project.ProjectAPI`` 与 ``Agent.core.api.diff.DiffAPI``，
实现新的 ProjectPort / ProjectDiffPort 接口。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from kernel.ports.project import ProjectDiffPort, ProjectPort

logger = logging.getLogger(__name__)


class LegacyProjectAdapter(ProjectPort):
    """包装旧项目 API 的适配器。"""

    def get_project_info(self, project_root: str) -> Dict[str, Any]:
        """获取项目基础信息。"""
        from Agent.core.api.project import ProjectAPI

        return ProjectAPI.get_project_info(project_root)

    def get_file_tree(self, project_root: str) -> Dict[str, Any]:
        """获取项目文件树。"""
        from Agent.core.api.project import ProjectAPI

        return ProjectAPI.get_file_tree(project_root)

    def get_readme_content(self, project_root: str) -> Dict[str, Any]:
        """获取 README 信息。"""
        from Agent.core.api.project import ProjectAPI

        return ProjectAPI.get_readme_content(project_root)

    def get_dependencies(self, project_root: str) -> Dict[str, Any]:
        """获取项目依赖信息。"""
        from Agent.core.api.project import ProjectAPI

        return ProjectAPI.get_dependencies(project_root)

    def get_git_info(self, project_root: str) -> Dict[str, Any]:
        """获取项目 Git 信息。"""
        from Agent.core.api.project import ProjectAPI

        return ProjectAPI.get_git_info(project_root)

    def get_git_index_paths(
        self,
        project_root: str,
        *,
        max_entries: int = 5000,
    ) -> List[str]:
        """读取 Git 索引中的文件路径列表，失败时返回空列表。"""
        from Agent.core.api.project import ProjectAPI

        try:
            index_path = ProjectAPI._get_git_index_path(Path(project_root).resolve())
            if index_path is None:
                return []
            return ProjectAPI._read_git_index_paths(index_path, max_entries=max_entries)
        except Exception:
            logger.warning(
                "读取 git index 文件列表失败 (project_root=%s)",
                project_root,
                exc_info=True,
            )
            return []

    def get_scanner_languages(self) -> List[Dict[str, Any]]:
        """列出已注册的静态扫描器（按语言聚合）。"""
        from Agent.DIFF.rule.scanner_registry import ScannerRegistry
        from Agent.DIFF.rule import (
            scanner_lang_go,
            scanner_lang_java,
            scanner_lang_python,
            scanner_lang_ruby,
            scanner_lang_typescript,
            scanner_performance,
            scanner_semgrep,
        )

        # 仅为触发装饰器注册，保持与旧实现一致的副作用导入
        _ = (
            scanner_lang_go,
            scanner_lang_java,
            scanner_lang_python,
            scanner_lang_ruby,
            scanner_lang_typescript,
            scanner_performance,
            scanner_semgrep,
        )
        ScannerRegistry.load_config()

        languages: List[Dict[str, Any]] = []
        for language in sorted(ScannerRegistry.get_registered_languages()):
            languages.append(
                {
                    "language": language,
                    "scanners": ScannerRegistry.get_scanner_info(language),
                }
            )
        return languages


class LegacyProjectDiffAdapter(ProjectDiffPort):
    """包装旧 Diff 查询 API 的适配器。"""

    def get_diff_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        """获取工作区 Diff 状态。"""
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_diff_status(project_root)

    def get_diff_summary(
        self,
        project_root: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """获取 Diff 汇总统计。"""
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_diff_summary(project_root, mode)

    def get_diff_files(
        self,
        project_root: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """获取 Diff 涉及的文件列表。"""
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_diff_files(project_root, mode)

    def get_file_diff(
        self,
        file_path: str,
        *,
        project_root: Optional[str] = None,
        mode: str = "auto",
        commit_from: Optional[str] = None,
        commit_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取单个文件的 Diff 详情。"""
        from Agent.core.api.diff import DiffAPI

        return DiffAPI.get_file_diff(
            file_path=file_path,
            project_root=project_root,
            mode=mode,
            commit_from=commit_from,
            commit_to=commit_to,
        )


__all__ = ["LegacyProjectAdapter", "LegacyProjectDiffAdapter"]
