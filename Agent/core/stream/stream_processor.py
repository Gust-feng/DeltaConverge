"""处理 Moonshot 风格响应的流式增量。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, TypedDict, Union


class NormalizedToolCall(TypedDict):
    id: str
    name: str
    index: int
    arguments: Dict[str, Any]


class NormalizedMessage(TypedDict, total=False):
    type: str
    role: str
    content: str | None
    reasoning: str | None
    tool_calls: List[NormalizedToolCall]
    finish_reason: str | None
    raw: Dict[str, Any]
    provider: str
    tool_schemas: List[Union[Dict[str, Any], Any]] | None
    usage: Dict[str, Any] | None


class StreamProcessor:
    """聚合流式增量，生成规范化的助手消息。"""

    _REASONING_KEYS = ("reasoning_content", "analysis", "thoughts")

    @staticmethod
    def _extract_text(delta_val: Any) -> str:
        """规范化提取文本，无论是 list[dict] 还是直接 str。"""

        if isinstance(delta_val, list):
            return "".join(
                piece.get("text", "")
                for piece in delta_val
                if isinstance(piece, dict) and piece.get("type") == "text"
            )
        if isinstance(delta_val, str):
            return delta_val
        return ""

    async def collect(
        self,
        stream: AsyncIterator[Dict[str, Any]],
        observer: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> NormalizedMessage:
        """消费流式迭代器并返回一条规范化消息。"""

        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        role = "assistant"
        finish_reason: str | None = None
        tool_call_buffer: Dict[int, Dict[str, Any]] = {}
        raw_chunks: List[Dict[str, Any]] = []
        last_usage: Dict[str, Any] | None = None

        async for chunk in stream:
            raw_chunks.append(chunk)
            delta = chunk.get("delta", {})
            finish_reason = chunk.get("finish_reason") or finish_reason
            role = delta.get("role") or role
            if chunk.get("usage"):
                last_usage = chunk["usage"]

            content_delta = delta.get("content")
            content_text = self._extract_text(content_delta)
            if content_text:
                content_parts.append(content_text)

            reasoning_text = ""
            for key in self._REASONING_KEYS:
                if key in delta:
                    reasoning_text = self._extract_text(delta.get(key))
                    break
            if reasoning_text:
                reasoning_parts.append(reasoning_text)

            tool_call_entries: List[Any]
            calls_raw = delta.get("tool_calls") or []
            if isinstance(calls_raw, dict):
                tool_call_entries = [calls_raw]
            elif isinstance(calls_raw, list):
                tool_call_entries = calls_raw
            else:
                tool_call_entries = []

            for call in tool_call_entries:
                if not isinstance(call, dict):
                    continue
                index = call.get("index")
                if index is None:
                    continue
                buffer = tool_call_buffer.setdefault(
                    index,
                    {
                        "id": call.get("id"),
                        "name": None,
                        "arguments_chunks": [],
                    },
                )
                if call.get("id"):
                    buffer["id"] = call["id"]
                fn = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
                if fn.get("name"):
                    buffer["name"] = fn["name"]
                if fn.get("arguments"):
                    buffer["arguments_chunks"].append(fn["arguments"])

            if observer:
                observer(
                    {
                        "type": "delta",
                        "content_delta": content_text,
                        "reasoning_delta": reasoning_text,
                        "tool_calls_delta": tool_call_entries,
                        "chunk": chunk,
                        "usage": chunk.get("usage"),
                    }
                )

        tool_calls: List[NormalizedToolCall] = []
        for index in sorted(tool_call_buffer.keys()):
            buf = tool_call_buffer[index]
            args_text = "".join(buf["arguments_chunks"])
            try:
                arguments = json.loads(args_text) if args_text else {}
            except json.JSONDecodeError:
                arguments = {"_raw": args_text, "_error": "invalid_json"}
            tool_calls.append(
                {
                    "id": buf.get("id") or f"call_{index}",
                    "name": buf.get("name") or "unknown_tool",
                    "index": index,
                    "arguments": arguments,
                }
            )

        content = "".join(content_parts).strip()
        reasoning = "".join(reasoning_parts).strip()
        return {
            "type": "assistant",
            "role": role,
            "content": content or None,
            "reasoning": reasoning or None,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "raw": {"chunks": raw_chunks},
            "usage": last_usage,
        }
