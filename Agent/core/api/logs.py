"""日志访问API模块。

提供历史审查日志的查询、导出功能。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class LogEntry:
    """日志条目。"""
    trace_id: str
    timestamp: str
    event: str
    stage: str
    status: str
    payload: Dict[str, Any]


class LogManager:
    """日志管理器。"""
    
    def __init__(self) -> None:
        self._api_log_dir = Path("log/api_log")
        self._human_log_dir = Path("log/human_log")
        self._pipeline_log_dir = Path("log/pipeline")
    
    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出历史审查会话。
        
        Args:
            limit: 返回条数
            offset: 偏移量
            date_from: 起始日期 (YYYY-MM-DD)
            date_to: 结束日期 (YYYY-MM-DD)
        """
        sessions = []
        
        # 扫描 pipeline 日志目录
        if self._pipeline_log_dir.exists():
            for log_file in sorted(self._pipeline_log_dir.glob("*.jsonl"), reverse=True):
                try:
                    # 从文件名解析时间戳和 trace_id
                    # 格式: 20251130_220524_planning_review_service_async_b89af792a8f7.jsonl
                    name = log_file.stem
                    parts = name.split("_")
                    if len(parts) >= 6:
                        date_str = parts[0]  # 20251130
                        time_str = parts[1]  # 220524
                        trace_id = parts[-1]  # b89af792a8f7
                        
                        # 日期过滤
                        file_date = datetime.strptime(date_str, "%Y%m%d")
                        if date_from:
                            from_date = datetime.strptime(date_from, "%Y-%m-%d")
                            if file_date < from_date:
                                continue
                        if date_to:
                            to_date = datetime.strptime(date_to, "%Y-%m-%d")
                            if file_date > to_date:
                                continue
                        
                        # 读取首条记录获取元数据
                        meta = {}
                        try:
                            with open(log_file, "r", encoding="utf-8") as f:
                                first_line = f.readline()
                                if first_line:
                                    first_entry = json.loads(first_line)
                                    meta = first_entry.get("meta", {})
                        except Exception:
                            pass
                        
                        sessions.append({
                            "trace_id": trace_id,
                            "date": date_str,
                            "time": time_str,
                            "file_path": str(log_file),
                            "file_size": log_file.stat().st_size,
                            "review_provider": meta.get("review_provider"),
                            "planner_provider": meta.get("planner_provider"),
                        })
                except Exception:
                    continue
        
        # 应用分页
        return sessions[offset:offset + limit]
    
    def get_session_log(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """获取单个会话的详细日志。
        
        Args:
            trace_id: 追踪ID
            
        Returns:
            Dict: 会话日志详情
        """
        # 查找 pipeline 日志
        pipeline_log = None
        if self._pipeline_log_dir.exists():
            for log_file in self._pipeline_log_dir.glob(f"*_{trace_id}.jsonl"):
                pipeline_log = log_file
                break
        
        if not pipeline_log or not pipeline_log.exists():
            return None
        
        events = []
        usage_summary = {}
        
        try:
            with open(pipeline_log, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        events.append({
                            "event": entry.get("event"),
                            "stage": entry.get("stage"),
                            "status": entry.get("status"),
                            "ts": entry.get("ts"),
                            "uptime_ms": entry.get("uptime_ms"),
                            "payload_preview": str(entry.get("payload", {}))[:200],
                        })
                        
                        # 提取用量信息
                        if entry.get("event") == "session_end":
                            usage_summary = entry.get("payload", {}).get("session_usage", {})
        except Exception:
            pass
        
        # 查找对应的人类可读日志
        human_log_content = None
        if self._human_log_dir.exists():
            for human_file in self._human_log_dir.glob(f"*_{trace_id}.md"):
                try:
                    human_log_content = human_file.read_text(encoding="utf-8")[:5000]  # 限制大小
                except Exception:
                    pass
                break
        
        return {
            "trace_id": trace_id,
            "pipeline_log_path": str(pipeline_log),
            "events": events,
            "event_count": len(events),
            "usage_summary": usage_summary,
            "human_log_preview": human_log_content,
        }
    
    def get_api_call_log(self, trace_id: str) -> List[Dict[str, Any]]:
        """获取会话的API调用详情。
        
        Args:
            trace_id: 追踪ID
            
        Returns:
            List[Dict]: API调用记录
        """
        calls = []
        
        if self._api_log_dir.exists():
            for log_file in self._api_log_dir.glob(f"*_{trace_id}.jsonl"):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                entry = json.loads(line)
                                calls.append({
                                    "section": entry.get("section"),
                                    "label": entry.get("label"),
                                    "ts": entry.get("ts"),
                                    "payload_preview": str(entry.get("payload", {}))[:300],
                                })
                except Exception:
                    continue
        
        return calls
    
    def delete_old_logs(self, days: int = 30) -> Dict[str, int]:
        """清理过期日志。
        
        Args:
            days: 保留天数
            
        Returns:
            Dict: {"deleted_files": int, "freed_bytes": int}
        """
        deleted_files = 0
        freed_bytes = 0
        cutoff = datetime.now().timestamp() - (days * 24 * 3600)
        
        for log_dir in [self._api_log_dir, self._human_log_dir, self._pipeline_log_dir]:
            if not log_dir.exists():
                continue
            
            for log_file in log_dir.iterdir():
                if log_file.is_file():
                    try:
                        if log_file.stat().st_mtime < cutoff:
                            file_size = log_file.stat().st_size
                            log_file.unlink()
                            deleted_files += 1
                            freed_bytes += file_size
                    except Exception:
                        continue
        
        return {
            "deleted_files": deleted_files,
            "freed_bytes": freed_bytes,
        }
    
    def get_log_stats(self) -> Dict[str, Any]:
        """获取日志统计信息。"""
        stats = {
            "api_log": {"file_count": 0, "total_size": 0},
            "human_log": {"file_count": 0, "total_size": 0},
            "pipeline_log": {"file_count": 0, "total_size": 0},
        }
        
        for name, log_dir in [
            ("api_log", self._api_log_dir),
            ("human_log", self._human_log_dir),
            ("pipeline_log", self._pipeline_log_dir),
        ]:
            if log_dir.exists():
                for f in log_dir.iterdir():
                    if f.is_file():
                        stats[name]["file_count"] += 1
                        stats[name]["total_size"] += f.stat().st_size
        
        return stats


# 全局日志管理器
_log_manager: Optional[LogManager] = None


def get_log_manager() -> LogManager:
    """获取日志管理器单例。"""
    global _log_manager
    if _log_manager is None:
        _log_manager = LogManager()
    return _log_manager


class LogAPI:
    """日志访问API（静态方法接口）。"""
    
    @staticmethod
    def list_sessions(
        limit: int = 50,
        offset: int = 0,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """列出历史审查会话日志。
        
        Args:
            limit: 返回条数
            offset: 偏移量
            date_from: 起始日期 (YYYY-MM-DD)
            date_to: 结束日期 (YYYY-MM-DD)
            
        Returns:
            Dict: {
                "sessions": List[{...}],
                "count": int
            }
        """
        sessions = get_log_manager().list_sessions(limit, offset, date_from, date_to)
        return {
            "sessions": sessions,
            "count": len(sessions),
        }
    
    @staticmethod
    def get_session_log(trace_id: str) -> Optional[Dict[str, Any]]:
        """获取单个会话的详细日志。
        
        Args:
            trace_id: 追踪ID
            
        Returns:
            Dict: 会话日志详情
        """
        return get_log_manager().get_session_log(trace_id)
    
    @staticmethod
    def get_api_calls(trace_id: str) -> Dict[str, Any]:
        """获取会话的API调用详情。
        
        Args:
            trace_id: 追踪ID
            
        Returns:
            Dict: {"calls": List[{...}], "count": int}
        """
        calls = get_log_manager().get_api_call_log(trace_id)
        return {
            "calls": calls,
            "count": len(calls),
        }
    
    @staticmethod
    def delete_old_logs(days: int = 30) -> Dict[str, Any]:
        """清理过期日志。
        
        Args:
            days: 保留天数
            
        Returns:
            Dict: {"deleted_files": int, "freed_bytes": int}
        """
        return get_log_manager().delete_old_logs(days)
    
    @staticmethod
    def get_log_stats() -> Dict[str, Any]:
        """获取日志统计信息。
        
        Returns:
            Dict: {
                "api_log": {"file_count": int, "total_size": int},
                "human_log": {"file_count": int, "total_size": int},
                "pipeline_log": {"file_count": int, "total_size": int}
            }
        """
        return get_log_manager().get_log_stats()


__all__ = [
    "LogAPI",
    "LogManager",
    "get_log_manager",
]
