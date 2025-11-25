"""Tool runtime with registry and concurrent execution."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

ToolFunc = Callable[[Dict[str, Any]], Awaitable[Any] | Any]


class ToolRuntime:
    """Registers and executes tools referenced by tool_calls."""

    def __init__(self) -> None:
        self._registry: Dict[str, ToolFunc] = {}

    def register(self, name: str, func: ToolFunc) -> None:
        """Register a tool by function name."""

        self._registry[name] = func

    async def execute(
        self,
        tool_calls: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Execute all requested tools concurrently."""

        tasks = [
            asyncio.create_task(self._run_single_call(call))
            for call in tool_calls
        ]
        return await asyncio.gather(*tasks)

    async def _run_single_call(self, call: Dict[str, Any]) -> Dict[str, Any]:
        """Run one tool call and wrap the response for conversation state."""

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
        except Exception as exc:  # pragma: no cover - surfaced to LLM
            return {
                "role": "tool",
                "tool_call_id": tool_id,
                "name": name,
                "content": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
