"""工具管理API模块。

提供工具注册、查询、统计等功能。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from Agent.tool.registry import (
    ToolSpec,
    register_tool,
    unregister_tool,
    list_tool_names,
    get_tool_spec,
    get_tool_schemas,
    get_tool_functions,
    default_tool_names,
)


@dataclass
class ToolExecution:
    """工具执行记录。"""
    tool_name: str
    arguments: Dict[str, Any]
    result: Any
    success: bool
    error: Optional[str]
    duration_ms: float
    timestamp: float


class ToolStatsCollector:
    """工具使用统计收集器（单例）。"""
    
    _instance: Optional["ToolStatsCollector"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "ToolStatsCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        
        self._stats_lock = threading.RLock()
        self._call_counts: Dict[str, int] = {}
        self._success_counts: Dict[str, int] = {}
        self._failure_counts: Dict[str, int] = {}
        self._total_duration_ms: Dict[str, float] = {}
        self._recent_executions: List[ToolExecution] = []
        self._max_recent = 100
        
        self._initialized = True
    
    def record_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        success: bool,
        error: Optional[str],
        duration_ms: float,
    ) -> None:
        """记录一次工具执行。"""
        with self._stats_lock:
            self._call_counts[tool_name] = self._call_counts.get(tool_name, 0) + 1
            
            if success:
                self._success_counts[tool_name] = self._success_counts.get(tool_name, 0) + 1
            else:
                self._failure_counts[tool_name] = self._failure_counts.get(tool_name, 0) + 1
            
            self._total_duration_ms[tool_name] = (
                self._total_duration_ms.get(tool_name, 0) + duration_ms
            )
            
            execution = ToolExecution(
                tool_name=tool_name,
                arguments=arguments,
                result=str(result)[:500] if result else None,  # 截断结果
                success=success,
                error=error,
                duration_ms=duration_ms,
                timestamp=time.time(),
            )
            
            self._recent_executions.append(execution)
            if len(self._recent_executions) > self._max_recent:
                self._recent_executions.pop(0)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息。"""
        with self._stats_lock:
            stats = {}
            all_tools = set(self._call_counts.keys())
            
            for tool_name in all_tools:
                calls = self._call_counts.get(tool_name, 0)
                successes = self._success_counts.get(tool_name, 0)
                failures = self._failure_counts.get(tool_name, 0)
                total_ms = self._total_duration_ms.get(tool_name, 0)
                
                stats[tool_name] = {
                    "call_count": calls,
                    "success_count": successes,
                    "failure_count": failures,
                    "success_rate": successes / calls if calls > 0 else 0,
                    "avg_duration_ms": total_ms / calls if calls > 0 else 0,
                    "total_duration_ms": total_ms,
                }
            
            return stats
    
    def get_recent_executions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的执行记录。"""
        with self._stats_lock:
            executions = self._recent_executions[-limit:]
            return [
                {
                    "tool_name": e.tool_name,
                    "arguments": e.arguments,
                    "success": e.success,
                    "error": e.error,
                    "duration_ms": e.duration_ms,
                    "timestamp": e.timestamp,
                }
                for e in reversed(executions)
            ]
    
    def reset(self) -> None:
        """重置所有统计。"""
        with self._stats_lock:
            self._call_counts.clear()
            self._success_counts.clear()
            self._failure_counts.clear()
            self._total_duration_ms.clear()
            self._recent_executions.clear()


# 全局统计收集器
_stats_collector: Optional[ToolStatsCollector] = None


def get_stats_collector() -> ToolStatsCollector:
    """获取统计收集器单例。"""
    global _stats_collector
    if _stats_collector is None:
        _stats_collector = ToolStatsCollector()
    return _stats_collector


# 自定义工具注册表（与内置工具分开）
_CUSTOM_TOOLS: Dict[str, ToolSpec] = {}


class ToolAPI:
    """工具管理API（静态方法接口）。"""
    
    @staticmethod
    def list_tools(include_builtin: bool = True, include_custom: bool = True) -> List[Dict[str, Any]]:
        """列出所有已注册的工具。
        
        Args:
            include_builtin: 是否包含内置工具
            include_custom: 是否包含自定义工具
            
        Returns:
            List[Dict]: [{
                "name": str,
                "description": str,
                "is_builtin": bool,
                "is_default": bool,
                "parameters": Dict
            }]
        """
        tools = []
        defaults = set(default_tool_names())
        
        if include_builtin:
            for name in list_tool_names():
                if name in _CUSTOM_TOOLS:
                    continue  # 跳过自定义工具（在下面单独处理）
                try:
                    spec = get_tool_spec(name)
                    tools.append({
                        "name": spec.name,
                        "description": spec.description,
                        "is_builtin": True,
                        "is_default": name in defaults,
                        "parameters": spec.parameters,
                    })
                except Exception:
                    continue
        
        if include_custom:
            for name, spec in _CUSTOM_TOOLS.items():
                tools.append({
                    "name": spec.name,
                    "description": spec.description,
                    "is_builtin": False,
                    "is_default": False,
                    "parameters": spec.parameters,
                })
        
        return tools
    
    @staticmethod
    def get_tool_detail(name: str) -> Optional[Dict[str, Any]]:
        """获取工具详细信息。
        
        Args:
            name: 工具名称
            
        Returns:
            Dict: 工具详情，不存在返回None
        """
        try:
            spec = get_tool_spec(name)
            defaults = set(default_tool_names())
            
            return {
                "name": spec.name,
                "description": spec.description,
                "is_builtin": name not in _CUSTOM_TOOLS,
                "is_default": name in defaults,
                "parameters": spec.parameters,
                "schema": get_tool_schemas([name])[0] if get_tool_schemas([name]) else None,
            }
        except Exception:
            return None
    
    @staticmethod
    def get_tool_schemas(names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """获取工具的OpenAI格式Schema。
        
        Args:
            names: 工具名称列表，None则返回所有
            
        Returns:
            List[Dict]: OpenAI function calling格式的schema列表
        """
        return get_tool_schemas(names)
    
    @staticmethod
    def get_default_tools() -> List[str]:
        """获取默认启用的工具列表。"""
        return default_tool_names()
    
    @staticmethod
    def register_custom_tool(
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Any],
    ) -> Dict[str, Any]:
        """注册自定义工具。
        
        Args:
            name: 工具名称（需唯一）
            description: 工具描述
            parameters: 参数JSON Schema
            handler: 处理函数
            
        Returns:
            Dict: {"success": bool, "message": str}
        """
        if name in list_tool_names():
            return {
                "success": False,
                "message": f"Tool '{name}' already exists",
            }
        
        try:
            spec = ToolSpec(
                name=name,
                description=description,
                parameters=parameters,
                func=handler,
            )
            
            register_tool(spec)
            _CUSTOM_TOOLS[name] = spec
            
            return {
                "success": True,
                "message": f"Tool '{name}' registered successfully",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to register tool: {e}",
            }
    
    @staticmethod
    def unregister_custom_tool(name: str) -> Dict[str, Any]:
        """注销自定义工具。
        
        Args:
            name: 工具名称
            
        Returns:
            Dict: {"success": bool, "message": str}
        """
        if name not in _CUSTOM_TOOLS:
            return {
                "success": False,
                "message": f"Tool '{name}' is not a custom tool or does not exist",
            }
        
        try:
            # 从自定义工具映射中删除
            del _CUSTOM_TOOLS[name]
            # 同时从全局注册表中删除
            unregister_tool(name)
            return {
                "success": True,
                "message": f"Tool '{name}' unregistered successfully",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to unregister tool: {e}",
            }
    
    @staticmethod
    def get_tool_stats() -> Dict[str, Any]:
        """获取工具使用统计。
        
        Returns:
            Dict: {
                "by_tool": {
                    "tool_name": {
                        "call_count": int,
                        "success_count": int,
                        "failure_count": int,
                        "success_rate": float,
                        "avg_duration_ms": float
                    }
                },
                "summary": {
                    "total_calls": int,
                    "total_successes": int,
                    "total_failures": int
                }
            }
        """
        stats = get_stats_collector().get_stats()
        
        total_calls = sum(s["call_count"] for s in stats.values())
        total_successes = sum(s["success_count"] for s in stats.values())
        total_failures = sum(s["failure_count"] for s in stats.values())
        
        return {
            "by_tool": stats,
            "summary": {
                "total_calls": total_calls,
                "total_successes": total_successes,
                "total_failures": total_failures,
                "overall_success_rate": total_successes / total_calls if total_calls > 0 else 0,
            },
        }
    
    @staticmethod
    def get_recent_executions(limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的工具执行记录。
        
        Args:
            limit: 返回条数
            
        Returns:
            List[Dict]: 执行记录列表
        """
        return get_stats_collector().get_recent_executions(limit)
    
    @staticmethod
    def reset_tool_stats() -> Dict[str, str]:
        """重置工具统计。"""
        get_stats_collector().reset()
        return {"status": "ok", "message": "Tool stats reset successfully"}


__all__ = [
    "ToolAPI",
    "ToolStatsCollector",
    "get_stats_collector",
]
