"""Legacy Diff 上下文处理适配器

包装旧内核的 diff_provider 模块，实现新的 DiffPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from kernel.ports.diff import (
    ContextBundle,
    ContextLevel,
    DiffContext,
    DiffPort,
    DiffUnit,
)
from kernel.ports.git import DiffMode, DiffResult

logger = logging.getLogger(__name__)


class LegacyDiffAdapter(DiffPort):
    """包装旧 Diff 处理的适配器"""
    
    def __init__(self, git_adapter: Any = None) -> None:
        self._git_adapter = git_adapter
    
    def build_diff_context(
        self,
        diff_text: str,
        *,
        project_root: Optional[str] = None,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> DiffContext:
        """从 Diff 文本构建 Diff 上下文"""
        from Agent.core.context.diff_provider import build_diff_context_from_text

        # 保持旧链路对象形态，避免 Stage 访问字段失配（review_index/files/units 等）
        legacy_ctx = build_diff_context_from_text(diff_text, cwd=project_root)
        return legacy_ctx  # type: ignore[return-value]
    
    def build_diff_context_from_result(
        self,
        diff_result: DiffResult,
        *,
        project_root: Optional[str] = None,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> DiffContext:
        """从 DiffResult 构建 Diff 上下文"""
        if diff_result.raw_diff:
            return self.build_diff_context(
                diff_result.raw_diff,
                project_root=project_root,
                context_level=context_level,
            )

        return DiffContext(
            diff_mode=diff_result.mode,
            base_ref=diff_result.base_ref,
            head_ref=diff_result.head_ref,
            project_root=project_root,
        )
    
    def collect_diff_context(
        self,
        mode: DiffMode,
        *,
        project_root: str,
        base_ref: Optional[str] = None,
        head_ref: Optional[str] = None,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> DiffContext:
        """收集指定模式的 Diff 上下文"""
        from Agent.core.context.diff_provider import collect_diff_context
        from Agent.DIFF.git_operations import DiffMode as LegacyDiffMode
        
        # 转换 DiffMode
        legacy_mode_map = {
            DiffMode.STAGED: LegacyDiffMode.STAGED,
            # 旧实现无 UNSTAGED，回退到 WORKING
            DiffMode.UNSTAGED: getattr(LegacyDiffMode, "UNSTAGED", LegacyDiffMode.WORKING),
            # 旧实现用 PR 表示分支对比
            DiffMode.BRANCH: getattr(LegacyDiffMode, "BRANCH", getattr(LegacyDiffMode, "PR", LegacyDiffMode.WORKING)),
            DiffMode.COMMIT: LegacyDiffMode.COMMIT,
            DiffMode.WORKING: LegacyDiffMode.WORKING,
        }
        legacy_mode = legacy_mode_map.get(mode, LegacyDiffMode.WORKING)
        
        legacy_ctx = collect_diff_context(
            mode=legacy_mode,
            cwd=project_root,
        )

        # 保持旧链路对象形态，避免 Stage 访问字段失配
        return legacy_ctx  # type: ignore[return-value]
    
    def build_context_bundle(
        self,
        diff_context: DiffContext,
        *,
        include_json: bool = True,
        include_planner_index: bool = True,
        max_tokens: Optional[int] = None,
    ) -> ContextBundle:
        """构建完整的上下文包"""
        bundle = ContextBundle(diff_context=diff_context)
        
        # 构建 Markdown 上下文
        bundle.markdown_context = self.build_markdown_context(diff_context)
        
        # 构建 JSON 上下文
        if include_json:
            bundle.json_context = self.build_json_context(diff_context)
        
        # 构建 Planner 索引
        if include_planner_index:
            bundle.planner_index = self.build_planner_index(diff_context)
        
        # 估算 tokens
        bundle.estimated_tokens = self.estimate_tokens(diff_context)
        
        return bundle
    
    def build_markdown_context(
        self,
        diff_context: DiffContext,
        *,
        include_line_numbers: bool = True,
        include_syntax_hints: bool = True,
    ) -> str:
        """生成 Markdown 格式的上下文"""
        from Agent.core.context.diff_provider import build_markdown_and_json_context
        
        # 调用旧函数
        if diff_context.raw_diff:
            markdown, _ = build_markdown_and_json_context(
                diff_context.raw_diff,
                cwd=diff_context.project_root,
            )
            return markdown
        
        return ""
    
    def build_json_context(
        self,
        diff_context: DiffContext,
    ) -> Dict[str, Any]:
        """生成 JSON 格式的上下文"""
        from Agent.core.context.diff_provider import build_markdown_and_json_context
        
        # 调用旧函数
        if diff_context.raw_diff:
            _, json_ctx = build_markdown_and_json_context(
                diff_context.raw_diff,
                cwd=diff_context.project_root,
            )
            return json_ctx
        
        return {}
    
    def build_planner_index(
        self,
        diff_context: Any,
    ) -> Dict[str, Any]:
        """生成用于 Planner 的索引结构。

        旧函数签名为 ``build_planner_index(units, actual_mode, base)``，
        此前本适配器误按单参数 ``raw_diff`` 调用，属实现缺陷，已修正为
        从上下文对象上读取 units / mode / base 三要素。
        """
        from Agent.DIFF.output_formatting import build_planner_index

        units = getattr(diff_context, "units", None) or []
        if not units:
            return {}
        # 兼容新旧上下文字段命名：legacy 用 mode/base_branch，端口模型用 diff_mode/base_ref
        mode = getattr(diff_context, "mode", None) or getattr(diff_context, "diff_mode", None)
        base = getattr(diff_context, "base_branch", None) or getattr(diff_context, "base_ref", None)
        return build_planner_index(units, mode, base)
    
    def estimate_tokens(
        self,
        diff_context: DiffContext,
        context_level: ContextLevel = ContextLevel.FUNCTION,
    ) -> int:
        """估算上下文的 Token 数量"""
        # 简化估算：每4个字符约1个token
        total_chars = 0
        
        for unit in diff_context.units:
            total_chars += len(unit.diff_text)
            if unit.context_before:
                total_chars += len(unit.context_before)
            if unit.context_after:
                total_chars += len(unit.context_after)
        
        return total_chars // 4
    
    def truncate_context(
        self,
        diff_context: DiffContext,
        max_tokens: int,
        *,
        priority: str = "recent",
    ) -> DiffContext:
        """截断上下文以适应 Token 限制"""
        # 简化实现：返回原上下文
        logger.warning("truncate_context not fully implemented in legacy adapter")
        return diff_context
    
    def _convert_legacy_context(
        self,
        legacy_ctx: Any,
        project_root: Optional[str],
    ) -> DiffContext:
        """将旧格式的上下文转换为新格式"""
        ctx = DiffContext(project_root=project_root)
        
        # 提取 diff_units
        if hasattr(legacy_ctx, "diff_units"):
            for unit in legacy_ctx.diff_units:
                ctx.units.append(
                    DiffUnit(
                        file_path=getattr(unit, "file_path", ""),
                        language=getattr(unit, "language", ""),
                        old_path=getattr(unit, "old_path", None),
                        status=getattr(unit, "status", "modified"),
                        diff_text=getattr(unit, "diff_text", ""),
                        additions=getattr(unit, "additions", 0),
                        deletions=getattr(unit, "deletions", 0),
                        is_binary=getattr(unit, "is_binary", False),
                    )
                )
        
        # 提取统计信息
        ctx.total_files = len(ctx.units)
        ctx.total_additions = sum(u.additions for u in ctx.units)
        ctx.total_deletions = sum(u.deletions for u in ctx.units)
        
        # 提取原始 diff
        if hasattr(legacy_ctx, "raw_diff"):
            ctx.raw_diff = legacy_ctx.raw_diff
        
        return ctx
