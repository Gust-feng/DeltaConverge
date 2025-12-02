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
        self._intent_cache_dir = current_dir / ".." / "DIFF" / "rule" / "data"
        self._intent_cache_dir = self._intent_cache_dir.resolve()
    
    def get_intent_cache_dir(self) -> Path:
        """获取意图缓存目录路径。"""
        return self._intent_cache_dir
    
    def list_intent_caches(self) -> List[CacheEntry]:
        """列出所有意图缓存条目。"""
        entries: List[CacheEntry] = []
        
        if not self._intent_cache_dir.exists():
            return entries
        
        current_time = datetime.now()
        
        for file_path in self._intent_cache_dir.glob("*.json"):
            try:
                stat = file_path.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime)
                age_days = (current_time - mtime).days
                
                entries.append(CacheEntry(
                    project_name=file_path.stem,
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
    
    def clear_intent_cache(self, project_name: Optional[str] = None) -> int:
        """清除意图分析缓存。
        
        Args:
            project_name: 指定项目名称，None则清除所有
            
        Returns:
            int: 清除的缓存文件数量
        """
        if not self._intent_cache_dir.exists():
            return 0
        
        cleared = 0
        
        if project_name:
            # 清除指定项目
            file_path = self._intent_cache_dir / f"{project_name}.json"
            if file_path.exists():
                try:
                    file_path.unlink()
                    cleared = 1
                except Exception:
                    pass
        else:
            # 清除所有
            for file_path in self._intent_cache_dir.glob("*.json"):
                try:
                    file_path.unlink()
                    cleared += 1
                except Exception:
                    continue
        
        return cleared
    
    def clear_expired_caches(self, max_age_days: int = 30) -> int:
        """清除过期的缓存文件。
        
        Args:
            max_age_days: 最大保留天数
            
        Returns:
            int: 清除的文件数量
        """
        if not self._intent_cache_dir.exists():
            return 0
        
        cleared = 0
        current_time = datetime.now()
        
        for file_path in self._intent_cache_dir.glob("*.json"):
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
        file_path = self._intent_cache_dir / f"{project_name}.json"
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    
    def refresh_intent_cache(self, project_name: str) -> bool:
        """标记指定项目的缓存需要刷新（删除缓存文件）。
        
        下次审查时将重新生成意图分析。
        
        Args:
            project_name: 项目名称
            
        Returns:
            bool: 是否成功删除
        """
        file_path = self._intent_cache_dir / f"{project_name}.json"
        
        if not file_path.exists():
            return True  # 不存在也算成功
        
        try:
            file_path.unlink()
            return True
        except Exception:
            return False


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
                "projects_cached": List[str]
            }
        """
        stats = get_cache_manager().get_cache_stats()
        return {
            "intent_cache_count": stats.intent_cache_count,
            "intent_cache_size_bytes": stats.intent_cache_size_bytes,
            "oldest_intent_cache": stats.oldest_intent_cache,
            "newest_intent_cache": stats.newest_intent_cache,
            "projects_cached": stats.projects_cached,
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
        cleared = get_cache_manager().clear_intent_cache(project_name)
        return {
            "cleared_count": cleared,
            "project": project_name,
        }
    
    @staticmethod
    def clear_expired_caches(max_age_days: int = 30) -> Dict[str, Any]:
        """清除过期的缓存文件。
        
        Args:
            max_age_days: 最大保留天数
            
        Returns:
            Dict: {"cleared_count": int, "max_age_days": int}
        """
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
