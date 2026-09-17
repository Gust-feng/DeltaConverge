"""Diff 上下文处理接口定义

定义将 Git Diff 转换为结构化上下文的抽象接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from kernel.ports.git import DiffMode, DiffResult


class ContextLevel(str, Enum):
    """上下文级别"""
    DIFF_ONLY = "diff_only"           # 仅 diff 内容
    FUNCTION = "function"             # 函数级上下文
    FILE_CONTEXT = "file_context"     # 文件上下文（含周围代码）
    FULL_FILE = "full_file"           # 完整文件内容


@dataclass
class DiffUnit:
    """Diff 单元 - 代表一个可审查的代码变更单元"""
    file_path: str
    language: str
    old_path: Optional[str] = None
    status: str = "modified"  # added, modified, deleted, renamed
    
    # 原始 diff
    diff_text: str = ""
    
    # 结构化信息
    hunks: List[Dict[str, Any]] = field(default_factory=list)
    
    # 上下文信息
    context_before: Optional[str] = None
    context_after: Optional[str] = None
    full_content: Optional[str] = None
    old_content: Optional[str] = None
    
    # 元信息
    additions: int = 0
    deletions: int = 0
    is_binary: bool = False
    
    # 关联的函数/类
    affected_symbols: List[str] = field(default_factory=list)


@dataclass
class DiffContext:
    """Diff 上下文 - 包含所有变更单元及汇总信息"""
    units: List[DiffUnit] = field(default_factory=list)
    
    # 汇总统计
    total_files: int = 0
    total_additions: int = 0
    total_deletions: int = 0
    
    # 变更摘要
    summary: Optional[str] = None
    
    # 原始信息
    raw_diff: Optional[str] = None
    diff_mode: Optional[DiffMode] = None
    base_ref: Optional[str] = None
    head_ref: Optional[str] = None
    
    # 项目信息
    project_root: Optional[str] = None
    
    # 文件类型分布
    file_types: Dict[str, int] = field(default_factory=dict)
    
    # 受影响的目录
    affected_dirs: List[str] = field(default_factory=list)


@dataclass
class ContextBundle:
    """上下文包 - 用于审查的完整上下文"""
    # 核心内容
    markdown_context: str = ""  # Markdown 格式的上下文
    json_context: Optional[Dict[str, Any]] = None  # 结构化 JSON 上下文
    
    # Diff 信息
    diff_context: Optional[DiffContext] = None
    
    # 索引信息（用于 Planner），结构由 build_planner_index 定义
    planner_index: Optional[Dict[str, Any]] = None
    
    # 规则匹配结果
    rule_findings: List[Dict[str, Any]] = field(default_factory=list)
    
    # 上下文配置
    context_level: ContextLevel = ContextLevel.FUNCTION
    
    # Token 估算
    estimated_tokens: int = 0


@runtime_checkable
class DiffPort(Protocol):
    """Diff 上下文处理接口
    
    负责将 Git Diff 转换为可用于代码审查的结构化上下文。
    """
    
    def build_diff_context(
        self,
        diff_text: str,
        *,
        project_root: Optional[str] = None,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> DiffContext:
        """从 Diff 文本构建 Diff 上下文
        
        Args:
            diff_text: 原始 Git diff 文本
            project_root: 项目根目录
            context_level: 上下文级别
            
        Returns:
            结构化的 Diff 上下文
        """
        ...
    
    def build_diff_context_from_result(
        self,
        diff_result: DiffResult,
        *,
        project_root: Optional[str] = None,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> DiffContext:
        """从 DiffResult 构建 Diff 上下文"""
        ...
    
    def collect_diff_context(
        self,
        mode: DiffMode,
        *,
        project_root: str,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> DiffContext:
        """收集指定模式的 Diff 上下文
        
        整合 Git 操作和上下文构建。
        """
        ...
    
    def build_context_bundle(
        self,
        diff_context: DiffContext,
        *,
        include_json: bool = True,
        include_planner_index: bool = True,
        max_tokens: Optional[int] = None,
    ) -> ContextBundle:
        """构建完整的上下文包
        
        Args:
            diff_context: Diff 上下文
            include_json: 是否包含 JSON 上下文
            include_planner_index: 是否生成 Planner 索引
            max_tokens: Token 限制，超过则截断
            
        Returns:
            完整的上下文包
        """
        ...
    
    def build_markdown_context(
        self,
        diff_context: DiffContext,
        *,
        include_line_numbers: bool = True,
        include_syntax_hints: bool = True,
    ) -> str:
        """生成 Markdown 格式的上下文"""
        ...
    
    def build_json_context(
        self,
        diff_context: DiffContext,
    ) -> Dict[str, Any]:
        """生成 JSON 格式的上下文"""
        ...

    def build_review_index_context(
        self,
        diff_context: Any,
        *,
        max_files: int = 5,
        max_changes_per_file: int = 3,
    ) -> tuple[str, Dict[str, Any]]:
        """基于审查单元索引构建轻量 Markdown + JSON 上下文。

        与 ``build_markdown_context`` 的区别：本方法面向"审查索引"，
        只描述有哪些审查单元及其规模/标签/规则决策，不携带 diff 正文，
        用于压缩首轮提示词体积。

        Args:
            diff_context: 运行时 diff 上下文对象
            max_files: 最多列出的文件数
            max_changes_per_file: 每个文件最多列出的变更数

        Returns:
            (markdown 文本, JSON 上下文)
        """
        ...
    
    def build_planner_index(
        self,
        diff_context: Any,
    ) -> Dict[str, Any]:
        """生成用于 Planner 的索引结构（units / mode / base 三要素驱动）"""
        ...
    
    def estimate_tokens(
        self,
        diff_context: DiffContext,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> int:
        """估算上下文的 Token 数量"""
        ...
    
    def truncate_context(
        self,
        diff_context: DiffContext,
        max_tokens: int,
        *,
        priority: str = "recent",  # recent, large_first, balanced
    ) -> DiffContext:
        """截断上下文以适应 Token 限制
        
        Args:
            diff_context: 原始上下文
            max_tokens: Token 上限
            priority: 截断策略
            
        Returns:
            截断后的上下文
        """
        ...
