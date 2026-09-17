"""上下文管理接口定义

定义动态上下文构建和管理的抽象接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from kernel.ports.diff import ContextLevel, DiffContext, DiffUnit


class CacheStrategy(str, Enum):
    """缓存策略"""
    NONE = "none"           # 不缓存
    SESSION = "session"     # 会话级缓存
    PROJECT = "project"     # 项目级缓存
    GLOBAL = "global"       # 全局缓存


@dataclass
class ContextRequest:
    """上下文请求"""
    # 核心参数
    diff_context: DiffContext
    
    # 上下文级别
    level: ContextLevel = ContextLevel.FUNCTION
    
    # 可选的文件过滤
    include_files: Optional[List[str]] = None
    exclude_files: Optional[List[str]] = None
    
    # Token 限制
    max_tokens: Optional[int] = None
    
    # 缓存控制
    cache_strategy: CacheStrategy = CacheStrategy.SESSION
    force_refresh: bool = False
    
    # 扩展选项
    include_dependencies: bool = False  # 包含依赖文件
    include_tests: bool = False         # 包含测试文件
    expand_imports: bool = False        # 展开导入的符号


@dataclass
class FileContext:
    """单文件的上下文信息"""
    path: str
    language: str
    
    # 文件内容（可能是部分）
    content: Optional[str] = None
    
    # Diff 单元
    diff_unit: Optional[DiffUnit] = None
    
    # 函数/类级别上下文
    symbols: List[Dict[str, Any]] = field(default_factory=list)
    
    # 行范围（如果是部分内容）
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    
    # 元信息
    is_test: bool = False
    is_generated: bool = False
    estimated_tokens: int = 0


@dataclass
class ContextResult:
    """上下文构建结果"""
    # 文件上下文列表
    files: List[FileContext] = field(default_factory=list)
    
    # 汇总信息
    total_files: int = 0
    total_tokens: int = 0
    truncated: bool = False
    
    # 缓存信息
    cache_hits: int = 0
    cache_misses: int = 0
    
    # 原始请求
    request: Optional[ContextRequest] = None


@runtime_checkable
class ContextPort(Protocol):
    """上下文管理接口
    
    负责动态构建代码审查所需的上下文。
    """
    
    def build_context(
        self,
        request: ContextRequest,
        *,
        project_root: str,
    ) -> ContextResult:
        """构建上下文
        
        根据请求参数和 Diff 信息，构建适合代码审查的上下文。
        
        Args:
            request: 上下文请求
            project_root: 项目根目录
            
        Returns:
            构建完成的上下文
        """
        ...
    
    def build_context_bundle(
        self,
        diff_context: Any,
        fused_plan: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """根据融合计划组装上下文包（bundle item 列表）。

        这是审查流水线实际使用的上下文装配入口：
        输入运行时 diff 上下文与融合后的计划，输出可直接序列化进提示词的
        bundle item 列表（每项含 unit_id / final_context_level / meta 等）。

        Args:
            diff_context: 运行时 diff 上下文对象
            fused_plan: 融合后的计划 ``{"plan": [...]}``

        Returns:
            bundle item 列表
        """
        ...

    def get_file_context(
        self,
        file_path: str,
        *,
        project_root: str,
        level: ContextLevel = ContextLevel.FUNCTION,
        diff_unit: Optional[DiffUnit] = None,
        line_range: Optional[tuple[int, int]] = None,
    ) -> FileContext:
        """获取单文件上下文
        
        Args:
            file_path: 文件路径
            project_root: 项目根目录
            level: 上下文级别
            diff_unit: 关联的 Diff 单元
            line_range: 行范围限制
        """
        ...
    
    def expand_context(
        self,
        file_context: FileContext,
        *,
        project_root: str,
        include_imports: bool = True,
        include_callers: bool = False,
        max_depth: int = 1,
    ) -> List[FileContext]:
        """扩展上下文
        
        根据文件的导入和引用关系扩展上下文。
        
        Returns:
            扩展后的文件上下文列表（包含原文件）
        """
        ...
    
    def filter_context(
        self,
        result: ContextResult,
        *,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        max_tokens: Optional[int] = None,
    ) -> ContextResult:
        """过滤上下文"""
        ...
    
    def merge_contexts(
        self,
        *results: ContextResult,
    ) -> ContextResult:
        """合并多个上下文结果"""
        ...


@runtime_checkable
class ContextCachePort(Protocol):
    """上下文缓存接口
    
    负责文件内容和上下文的缓存管理。
    """
    
    def get_file_content(
        self,
        file_path: str,
        *,
        project_root: str,
    ) -> Optional[str]:
        """获取缓存的文件内容"""
        ...
    
    def set_file_content(
        self,
        file_path: str,
        content: str,
        *,
        project_root: str,
        ttl: Optional[float] = None,
    ) -> None:
        """缓存文件内容"""
        ...
    
    def get_context(
        self,
        cache_key: str,
    ) -> Optional[ContextResult]:
        """获取缓存的上下文"""
        ...
    
    def set_context(
        self,
        cache_key: str,
        result: ContextResult,
        *,
        ttl: Optional[float] = None,
    ) -> None:
        """缓存上下文"""
        ...
    
    def invalidate_file(
        self,
        file_path: str,
        *,
        project_root: Optional[str] = None,
    ) -> None:
        """失效指定文件的缓存"""
        ...
    
    def invalidate_project(
        self,
        project_root: str,
    ) -> None:
        """失效整个项目的缓存"""
        ...
    
    def clear_all(self) -> None:
        """清空所有缓存"""
        ...
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        ...
