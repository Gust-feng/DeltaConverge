"""项目信息与 Diff 查询接口定义

定义项目分析（文件树、README、依赖、Git 信息）与 Diff 只读查询的抽象接口。
对应旧实现 ``Agent.core.api.project.ProjectAPI`` 与 ``Agent.core.api.diff.DiffAPI``。

注意：本端口面向 Web/CLI 的**只读查询**场景，
与审查流水线内部采集 Diff 的 ``DiffPort`` 职责不同，不要混用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ProjectPort(Protocol):
    """项目信息查询接口。"""

    def get_project_info(self, project_root: str) -> Dict[str, Any]:
        """获取项目基础信息（名称、语言检测等）。"""
        ...

    def get_file_tree(self, project_root: str) -> Dict[str, Any]:
        """获取项目文件树。"""
        ...

    def get_readme_content(self, project_root: str) -> Dict[str, Any]:
        """获取 README 信息（含内容与是否存在等字段）。"""
        ...

    def get_dependencies(self, project_root: str) -> Dict[str, Any]:
        """获取项目依赖信息。"""
        ...

    def get_git_info(self, project_root: str) -> Dict[str, Any]:
        """获取项目 Git 信息（分支、远端等）。"""
        ...

    def get_git_index_paths(
        self,
        project_root: str,
        *,
        max_entries: int = 5000,
    ) -> List[str]:
        """读取 Git 索引中的文件路径列表。

        用于快速构建文件树；读取失败时应返回空列表而非抛出异常。
        """
        ...

    def get_scanner_languages(self) -> List[Dict[str, Any]]:
        """列出已注册的静态扫描器（按语言聚合）。

        每项至少包含 ``language`` 与 ``scanners``（扫描器明细列表），
        实现方需保证扫描器配置已加载。
        """
        ...


@runtime_checkable
class ProjectDiffPort(Protocol):
    """Diff 只读查询接口（面向 API 展示，而非审查流水线）。"""

    def get_diff_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        """获取工作区 Diff 状态。"""
        ...

    def get_diff_summary(
        self,
        project_root: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """获取 Diff 汇总统计。"""
        ...

    def get_diff_files(
        self,
        project_root: Optional[str] = None,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """获取 Diff 涉及的文件列表。"""
        ...

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
        ...


__all__ = ["ProjectPort", "ProjectDiffPort"]
