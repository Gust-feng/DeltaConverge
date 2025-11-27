"""工具运行时：负责注册与并发执行工具。"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional
import time
try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

ToolFunc = Callable[[Dict[str, Any]], Awaitable[Any] | Any]


class ToolRuntime:
    """注册并执行 tool_calls 中引用的工具。"""

    def __init__(self) -> None:
        self._registry: Dict[str, ToolFunc] = {}

    def register(self, name: str, func: ToolFunc) -> None:
        """按函数名注册工具。"""

        self._registry[name] = func

    async def execute(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """并发执行所有请求的工具。"""

        tasks = [
            asyncio.create_task(self._run_single_call(call))
            for call in tool_calls
        ]
        return await asyncio.gather(*tasks)

    async def _run_single_call(self, call: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个工具调用，并包装为会话状态所需的响应。"""

        tool_id = call.get("id", "unknown_call")
        name = call.get("name")
        func = self._registry.get(name or "")
        if func is None:
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": "",
                "error": f"Tool '{name}' not registered.",
            }

        start_perf = time.perf_counter()
        proc = psutil.Process() if psutil else None
        start_mem = proc.memory_info().rss if proc else None
        start_cpu = proc.cpu_times().user + proc.cpu_times().system if proc else None
        try:
            result = func(call.get("arguments", {}))
            if asyncio.iscoroutine(result):
                result = await result
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            end_mem = proc.memory_info().rss if proc else None
            end_cpu = proc.cpu_times().user + proc.cpu_times().system if proc else None
            mem_delta = (end_mem - start_mem) if (proc and start_mem is not None and end_mem is not None) else None
            cpu_time = (end_cpu - start_cpu) if (proc and start_cpu is not None and end_cpu is not None) else None
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": result if isinstance(result, str) else str(result),
                "duration_ms": duration_ms,
                "cpu_time": cpu_time,
                "mem_delta": mem_delta,
            }
        except Exception as exc:  # pragma: no cover - 异常直接反馈给 LLM
            duration_ms = int((time.perf_counter() - start_perf) * 1000)
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": "",
                "error": f"{type(exc).__name__}: {exc}",
                "duration_ms": duration_ms,
            }
