"""Legacy 上下文管理适配器

包装旧内核的 context_scheduler 和 ContextProvider，实现新的 ContextPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from kernel.ports.context import (
    CacheStrategy,
    ContextCachePort,
    ContextPort,
    ContextRequest,
    ContextResult,
    FileContext,
)
from kernel.ports.diff import ContextLevel, DiffUnit

logger = logging.getLogger(__name__)


class LegacyContextAdapter(ContextPort):
    """包装旧上下文管理器的适配器"""
    
    def build_context(
        self,
        request: ContextRequest,
        *,
        project_root: str,
    ) -> ContextResult:
        """构建上下文"""
        from Agent.agents.context_scheduler import build_context_bundle
        
        try:
            # 调用旧函数
            context_bundle = build_context_bundle(
                diff_context=request.diff_context,
                project_root=project_root,
            )
            
            # 转换为新格式
            result = ContextResult()
            result.request = request
            
            # 从 bundle 中提取文件上下文
            # 简化实现：从 diff_context 提取
            for unit in request.diff_context.units:
                file_ctx = FileContext(
                    path=unit.file_path,
                    language=unit.language,
                    diff_unit=unit,
                )
                result.files.append(file_ctx)
            
            result.total_files = len(result.files)
            result.total_tokens = request.diff_context.total_additions + request.diff_context.total_deletions
            
            return result
        except Exception as e:
            logger.error(f"Failed to build context: {e}")
            # 回退：返回基础上下文
            result = ContextResult()
            result.request = request
            for unit in request.diff_context.units:
                result.files.append(
                    FileContext(
                        path=unit.file_path,
                        language=unit.language,
                        diff_unit=unit,
                    )
                )
            return result
    
    def get_file_context(
        self,
        file_path: str,
        *,
        project_root: str,
        level: ContextLevel = ContextLevel.FUNCTION,
        diff_unit: Optional[DiffUnit] = None,
        line_range: Optional[tuple[int, int]] = None,
    ) -> FileContext:
        """获取单文件上下文"""
        # 简化实现：读取文件内容
        import os
        
        full_path = os.path.join(project_root, file_path)
        content = None
        
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
        
        # 检测语言
        ext = os.path.splitext(file_path)[1]
        language_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }
        language = language_map.get(ext, "text")
        
        return FileContext(
            path=file_path,
            language=language,
            content=content,
            diff_unit=diff_unit,
            estimated_tokens=len(content) // 4 if content else 0,
        )
    
    def expand_context(
        self,
        file_context: FileContext,
        *,
        project_root: str,
        include_imports: bool = True,
        include_callers: bool = False,
        max_depth: int = 1,
    ) -> List[FileContext]:
        """扩展上下文"""
        # 简化实现：仅返回原文件
        logger.warning("expand_context not fully implemented in legacy adapter")
        return [file_context]
    
    def filter_context(
        self,
        result: ContextResult,
        *,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        max_tokens: Optional[int] = None,
    ) -> ContextResult:
        """过滤上下文"""
        import fnmatch
        
        filtered = ContextResult()
        filtered.request = result.request
        
        for file_ctx in result.files:
            # 检查 include patterns
            if include_patterns:
                if not any(fnmatch.fnmatch(file_ctx.path, p) for p in include_patterns):
                    continue
            
            # 检查 exclude patterns
            if exclude_patterns:
                if any(fnmatch.fnmatch(file_ctx.path, p) for p in exclude_patterns):
                    continue
            
            filtered.files.append(file_ctx)
        
        # 处理 token 限制
        if max_tokens:
            total_tokens = 0
            truncated_files = []
            for file_ctx in filtered.files:
                if total_tokens + file_ctx.estimated_tokens > max_tokens:
                    filtered.truncated = True
                    break
                truncated_files.append(file_ctx)
                total_tokens += file_ctx.estimated_tokens
            filtered.files = truncated_files
        
        filtered.total_files = len(filtered.files)
        filtered.total_tokens = sum(f.estimated_tokens for f in filtered.files)
        
        return filtered
    
    def merge_contexts(
        self,
        *results: ContextResult,
    ) -> ContextResult:
        """合并多个上下文结果"""
        merged = ContextResult()
        
        seen_paths = set()
        for result in results:
            for file_ctx in result.files:
                if file_ctx.path not in seen_paths:
                    merged.files.append(file_ctx)
                    seen_paths.add(file_ctx.path)
        
        merged.total_files = len(merged.files)
        merged.total_tokens = sum(f.estimated_tokens for f in merged.files)
        
        return merged


class LegacyContextCache(ContextCachePort):
    """包装旧上下文缓存的适配器"""
    
    def __init__(self) -> None:
        self._file_cache: Dict[str, str] = {}
        self._context_cache: Dict[str, ContextResult] = {}
    
    def get_file_content(
        self,
        file_path: str,
        *,
        project_root: str,
    ) -> Optional[str]:
        """获取缓存的文件内容"""
        cache_key = f"{project_root}:{file_path}"
        return self._file_cache.get(cache_key)
    
    def set_file_content(
        self,
        file_path: str,
        content: str,
        *,
        project_root: str,
        ttl: Optional[float] = None,
    ) -> None:
        """缓存文件内容"""
        cache_key = f"{project_root}:{file_path}"
        self._file_cache[cache_key] = content
    
    def get_context(
        self,
        cache_key: str,
    ) -> Optional[ContextResult]:
        """获取缓存的上下文"""
        return self._context_cache.get(cache_key)
    
    def set_context(
        self,
        cache_key: str,
        result: ContextResult,
        *,
        ttl: Optional[float] = None,
    ) -> None:
        """缓存上下文"""
        self._context_cache[cache_key] = result
    
    def invalidate_file(
        self,
        file_path: str,
        *,
        project_root: Optional[str] = None,
    ) -> None:
        """失效指定文件的缓存"""
        if project_root:
            cache_key = f"{project_root}:{file_path}"
            self._file_cache.pop(cache_key, None)
        else:
            # 清除所有匹配的文件
            keys_to_remove = [k for k in self._file_cache if k.endswith(f":{file_path}")]
            for key in keys_to_remove:
                self._file_cache.pop(key, None)
    
    def invalidate_project(
        self,
        project_root: str,
    ) -> None:
        """失效整个项目的缓存"""
        # 清除文件缓存
        keys_to_remove = [k for k in self._file_cache if k.startswith(f"{project_root}:")]
        for key in keys_to_remove:
            self._file_cache.pop(key, None)
        
        # 清除上下文缓存
        # 简化：清除所有
        self._context_cache.clear()
    
    def clear_all(self) -> None:
        """清空所有缓存"""
        self._file_cache.clear()
        self._context_cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "file_cache_size": len(self._file_cache),
            "context_cache_size": len(self._context_cache),
        }
