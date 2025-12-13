"""缓存管理模块。

提供意图缓存、文件缓存的清理和统计功能。
缓存是内核性能优化的关键组成部分，但需要提供可控的管理接口。
"""

from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CacheStats:
    """缓存统计信息。"""
    intent_cache_count: int
    intent_cache_size_bytes: int
    oldest_intent_cache: Optional[str]  # ISO格式时间戳
    newest_intent_cache: Optional[str]
    projects_cached: List[str]


@dataclass
class CacheEntry:
    """单个缓存条目信息。"""
    project_name: str
    file_path: str
    size_bytes: int
    created_at: str
    age_days: int


class CacheManager:
    """缓存管理器。"""
    
    def __init__(self) -> None:
        # 意图缓存目录（与 ReviewKernel 保持一致）
        current_dir = Path(__file__).parent
        # Primary location: Agent/data/Analysis
        agent_root = current_dir.parents[2]
        primary = (agent_root / "data" / "Analysis").resolve()

        self._intent_cache_dir = primary
        self._intent_cache_dirs = [primary]
    
    def get_intent_cache_dir(self) -> Path:
        """获取意图缓存目录路径。"""
        # 返回首选目录（不存在也返回，用于后续 mkdir）
        return self._intent_cache_dir
    
    def list_intent_caches(self) -> List[CacheEntry]:
        """列出所有意图缓存条目。"""
        entries: List[CacheEntry] = []
        seen = set()
        for d in self._intent_cache_dirs:
            if not d.exists():
                continue

            current_time = datetime.now()

            for file_path in d.glob("*.json"):
                try:
                    stem = file_path.stem
                    if stem in seen:
                        continue
                    seen.add(stem)
                    stat = file_path.stat()
                    mtime = datetime.fromtimestamp(stat.st_mtime)
                    age_days = (current_time - mtime).days

                    entries.append(CacheEntry(
                        project_name=stem,
                        file_path=str(file_path),
                        size_bytes=stat.st_size,
                        created_at=mtime.isoformat(),
                        age_days=age_days,
                    ))
                except Exception:
                    continue
        
        return sorted(entries, key=lambda x: x.created_at, reverse=True)
    
    def get_cache_stats(self) -> CacheStats:
        """获取缓存统计信息。"""
        entries = self.list_intent_caches()
        
        if not entries:
            return CacheStats(
                intent_cache_count=0,
                intent_cache_size_bytes=0,
                oldest_intent_cache=None,
                newest_intent_cache=None,
                projects_cached=[],
            )
        
        total_size = sum(e.size_bytes for e in entries)
        oldest = min(entries, key=lambda x: x.created_at)
        newest = max(entries, key=lambda x: x.created_at)
        
        return CacheStats(
            intent_cache_count=len(entries),
            intent_cache_size_bytes=total_size,
            oldest_intent_cache=oldest.created_at,
            newest_intent_cache=newest.created_at,
            projects_cached=[e.project_name for e in entries],
        )
    
    def clear_intent_cache(self, project_name: Optional[str] = None) -> Dict[str, int]:
        """清除意图分析缓存。
        
        Args:
            project_name: 指定项目名称，None则清除所有
            
        Returns:
            int: 清除的缓存文件数量
        """
        cleared = 0
        failed = 0
        if project_name:
            for d in self._intent_cache_dirs:
                file_path = d / f"{project_name}.json"
                if file_path.exists():
                    try:
                        file_path.unlink()
                        cleared += 1
                    except Exception:
                        failed += 1
        else:
            for d in self._intent_cache_dirs:
                if not d.exists():
                    continue
                for file_path in d.glob("*.json"):
                    try:
                        file_path.unlink()
                        cleared += 1
                    except Exception:
                        failed += 1

        return {"cleared": cleared, "failed": failed}
    
    def clear_expired_caches(self, max_age_days: int | None = None) -> int:
        """清除过期的缓存文件。
        
        Args:
            max_age_days: 最大保留天数，None则从配置读取
            
        Returns:
            int: 清除的文件数量
        """
        # 从配置读取默认值
        if max_age_days is None:
            try:
                from Agent.core.api.config import get_intent_cache_ttl_days
                max_age_days = get_intent_cache_ttl_days()
            except Exception:
                max_age_days = 30
        
        cleared = 0
        current_time = datetime.now()
        for d in self._intent_cache_dirs:
            if not d.exists():
                continue
            for file_path in d.glob("*.json"):
                try:
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    age_days = (current_time - mtime).days
                    if age_days > max_age_days:
                        file_path.unlink()
                        cleared += 1
                except Exception:
                    continue

        return cleared
    
    def get_intent_cache_content(self, project_name: str) -> Optional[Dict[str, Any]]:
        """获取指定项目的意图缓存内容。
        
        Args:
            project_name: 项目名称
            
        Returns:
            缓存内容字典，不存在返回 None
        """
        # 尝试在所有候选目录中查找
        for d in self._intent_cache_dirs:
            file_path = d / f"{project_name}.json"
            if not file_path.exists():
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue

        return None
    
    def refresh_intent_cache(self, project_name: str) -> bool:
        """标记指定项目的缓存需要刷新（删除缓存文件）。
        
        下次审查时将重新生成意图分析。
        
        Args:
            project_name: 项目名称
            
        Returns:
            bool: 是否成功删除
        """
        success = True
        for d in self._intent_cache_dirs:
            file_path = d / f"{project_name}.json"
            if not file_path.exists():
                continue
            try:
                file_path.unlink()
            except Exception:
                success = False

        return success


# 全局缓存管理器实例
_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """获取缓存管理器单例。"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager


class CacheAPI:
    """缓存管理API（静态方法接口）。"""
    
    @staticmethod
    def get_cache_stats() -> Dict[str, Any]:
        """获取缓存统计信息。
        
        Returns:
            Dict: {
                "intent_cache_count": int,
                "intent_cache_size_bytes": int,
                "oldest_intent_cache": Optional[str],
                "newest_intent_cache": Optional[str],
                "projects_cached": List[str],
                # 兼容前端 debug.js 字段
                "intent_cache_size": int,
                "diff_cache_size": int,
            }
        """
        stats = get_cache_manager().get_cache_stats()
        return {
            "intent_cache_count": stats.intent_cache_count,
            "intent_cache_size_bytes": stats.intent_cache_size_bytes,
            "oldest_intent_cache": stats.oldest_intent_cache,
            "newest_intent_cache": stats.newest_intent_cache,
            "projects_cached": stats.projects_cached,
            # 前端 debug.js 读取 intent_cache_size/diff_cache_size；后者暂无实现，先返回 0
            "intent_cache_size": stats.intent_cache_count,
            "diff_cache_size": 0,
        }
    
    @staticmethod
    def list_intent_caches() -> List[Dict[str, Any]]:
        """列出所有意图缓存条目。
        
        Returns:
            List[Dict]: 缓存条目列表，每个包含 project_name, file_path, size_bytes, created_at, age_days
        """
        entries = get_cache_manager().list_intent_caches()
        return [
            {
                "project_name": e.project_name,
                "file_path": e.file_path,
                "size_bytes": e.size_bytes,
                "created_at": e.created_at,
                "age_days": e.age_days,
            }
            for e in entries
        ]
    
    @staticmethod
    def clear_intent_cache(project_name: Optional[str] = None) -> Dict[str, Any]:
        """清除意图分析缓存。
        
        Args:
            project_name: 指定项目名称，None则清除所有
            
        Returns:
            Dict: {"cleared_count": int, "project": Optional[str]}
        """
        result = get_cache_manager().clear_intent_cache(project_name)
        cleared = result["cleared"] if isinstance(result, dict) else int(result)
        failed = result.get("failed", 0) if isinstance(result, dict) else 0
        return {
            "cleared_count": cleared,
            "failed_count": failed,
            "project": project_name,
        }
    
    @staticmethod
    def clear_expired_caches(max_age_days: int | None = None) -> Dict[str, Any]:
        """清除过期的缓存文件。
        
        Args:
            max_age_days: 最大保留天数，None则从配置读取
            
        Returns:
            Dict: {"cleared_count": int, "max_age_days": int}
        """
        # 从配置读取默认值
        if max_age_days is None:
            try:
                from Agent.core.api.config import get_intent_cache_ttl_days
                max_age_days = get_intent_cache_ttl_days()
            except Exception:
                max_age_days = 30
        
        cleared = get_cache_manager().clear_expired_caches(max_age_days)
        return {
            "cleared_count": cleared,
            "max_age_days": max_age_days,
        }
    
    @staticmethod
    def get_intent_cache(project_name: str) -> Optional[Dict[str, Any]]:
        """获取指定项目的意图缓存内容。
        
        Args:
            project_name: 项目名称
            
        Returns:
            缓存内容字典，不存在返回 None
        """
        return get_cache_manager().get_intent_cache_content(project_name)
    
    @staticmethod
    def refresh_intent_cache(project_name: str) -> Dict[str, Any]:
        """刷新指定项目的缓存（删除旧缓存，下次审查时重新生成）。
        
        Args:
            project_name: 项目名称
            
        Returns:
            Dict: {"success": bool, "project": str}
        """
        success = get_cache_manager().refresh_intent_cache(project_name)
        return {
            "success": success,
            "project": project_name,
        }


__all__ = [
    "CacheAPI",
    "CacheManager",
    "CacheStats",
    "CacheEntry",
    "get_cache_manager",
]
