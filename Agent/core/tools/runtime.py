"""工具运行时：负责注册与并发执行工具。"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

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

        try:
            result = func(call.get("arguments", {}))
            if asyncio.iscoroutine(result):
                result = await result
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": result if isinstance(result, str) else str(result),
            }
        except Exception as exc:  # pragma: no cover - 异常直接反馈给 LLM
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
