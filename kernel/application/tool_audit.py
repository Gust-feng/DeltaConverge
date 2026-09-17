"""工具调用审计与重放模块。

记录每次工具调用的完整信息，支持：
- 调用输入/输出记录
- 触发上下文追踪
- 执行耗时统计
- 会话回放
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ToolCallRecord:
    """单次工具调用记录。"""
    call_id: str
    tool_name: str
    args: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    trigger_context: Optional[str] = None  # 触发工具调用的上下文
    stage_name: Optional[str] = None
    trace_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "args": self.args,
            "result": _safe_serialize(self.result),
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "trigger_context": self.trigger_context,
            "stage_name": self.stage_name,
            "trace_id": self.trace_id,
        }


class ToolAuditLog:
    """工具调用审计日志。
    
    维护一个会话内所有工具调用的记录，支持：
    - 添加新调用记录
    - 按工具名称/阶段查询
    - 导出完整日志供回放
    """
    
    def __init__(self, trace_id: Optional[str] = None) -> None:
        self.trace_id = trace_id
        self._records: List[ToolCallRecord] = []
        self._call_counter = 0
    
    def start_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        trigger_context: Optional[str] = None,
        stage_name: Optional[str] = None,
    ) -> str:
        """开始一次工具调用，返回 call_id。"""
        self._call_counter += 1
        call_id = f"{self.trace_id or 'local'}-{self._call_counter:04d}"
        
        record = ToolCallRecord(
            call_id=call_id,
            tool_name=tool_name,
            args=args,
            start_time=time.time(),
            trigger_context=trigger_context,
            stage_name=stage_name,
            trace_id=self.trace_id,
        )
        self._records.append(record)
        return call_id
    
    def complete_call(
        self,
        call_id: str,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        """完成一次工具调用。"""
        for record in reversed(self._records):
            if record.call_id == call_id:
                record.end_time = time.time()
                record.duration_ms = (record.end_time - record.start_time) * 1000
                record.result = result
                record.error = error
                break
    
    def get_records(
        self,
        tool_name: Optional[str] = None,
        stage_name: Optional[str] = None,
    ) -> List[ToolCallRecord]:
        """按条件查询调用记录。"""
        result = self._records
        if tool_name:
            result = [r for r in result if r.tool_name == tool_name]
        if stage_name:
            result = [r for r in result if r.stage_name == stage_name]
        return result
    
    def get_summary(self) -> Dict[str, Any]:
        """获取调用统计摘要。"""
        by_tool: Dict[str, int] = {}
        by_stage: Dict[str, int] = {}
        total_duration = 0.0
        errors = 0
        
        for record in self._records:
            by_tool[record.tool_name] = by_tool.get(record.tool_name, 0) + 1
            if record.stage_name:
                by_stage[record.stage_name] = by_stage.get(record.stage_name, 0) + 1
            total_duration += record.duration_ms
            if record.error:
                errors += 1
        
        return {
            "trace_id": self.trace_id,
            "total_calls": len(self._records),
            "total_duration_ms": round(total_duration, 2),
            "errors": errors,
            "by_tool": by_tool,
            "by_stage": by_stage,
        }
    
    def export_for_replay(self) -> List[Dict[str, Any]]:
        """导出完整日志供会话回放。"""
        return [r.to_dict() for r in self._records]
    
    def clear(self) -> None:
        """清空记录。"""
        self._records.clear()
        self._call_counter = 0


def _safe_serialize(value: Any, max_length: int = 1000) -> Any:
    """安全序列化值，截断过长内容。"""
    if value is None:
        return None
    
    if isinstance(value, (str, bytes)):
        s = str(value)
        if len(s) > max_length:
            return s[:max_length] + f"...(truncated, total {len(s)} chars)"
        return s
    
    if isinstance(value, (int, float, bool)):
        return value
    
    if isinstance(value, (list, tuple)):
        if len(value) > 10:
            return [_safe_serialize(v, max_length // 2) for v in value[:10]] + [f"...(truncated, total {len(value)} items)"]
        return [_safe_serialize(v, max_length // 2) for v in value]
    
    if isinstance(value, dict):
        if len(value) > 10:
            truncated = {k: _safe_serialize(v, max_length // 2) for k, v in list(value.items())[:10]}
            truncated["__truncated__"] = f"total {len(value)} keys"
            return truncated
        return {k: _safe_serialize(v, max_length // 2) for k, v in value.items()}
    
    # 其他类型转字符串
    s = str(value)
    if len(s) > max_length:
        return s[:max_length] + "...(truncated)"
    return s


# 全局审计日志（每个 trace_id 一个）
_AUDIT_LOGS: Dict[str, ToolAuditLog] = {}


def get_audit_log(trace_id: str) -> ToolAuditLog:
    """获取或创建指定 trace_id 的审计日志。"""
    if trace_id not in _AUDIT_LOGS:
        _AUDIT_LOGS[trace_id] = ToolAuditLog(trace_id)
    return _AUDIT_LOGS[trace_id]


def clear_audit_log(trace_id: str) -> None:
    """清除指定 trace_id 的审计日志。"""
    if trace_id in _AUDIT_LOGS:
        del _AUDIT_LOGS[trace_id]


def get_all_audit_summaries() -> Dict[str, Dict[str, Any]]:
    """获取所有审计日志的摘要。"""
    return {tid: log.get_summary() for tid, log in _AUDIT_LOGS.items()}
