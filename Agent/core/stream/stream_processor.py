"""Streaming delta processor for Moonshot-style responses."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, TypedDict


class NormalizedToolCall(TypedDict):
    id: str
    name: str
    index: int
    arguments: Dict[str, Any]


class NormalizedMessage(TypedDict, total=False):
    type: str
    role: str
    content: str | None
    tool_calls: List[NormalizedToolCall]
    finish_reason: str | None
    raw: Dict[str, Any]
    provider: str
    tool_schemas: List[Dict[str, Any]] | None
    usage: Dict[str, Any] | None


class StreamProcessor:
    """Aggregates streaming deltas into a normalized assistant message."""

    async def collect(
        self,
        stream: AsyncIterator[Dict[str, Any]],
        observer: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> NormalizedMessage:
        """Consume a streaming iterator and return a single normalized message."""

        content_parts: List[str] = []
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
            if isinstance(content_delta, list):
                for piece in content_delta:
                    if isinstance(piece, dict) and piece.get("type") == "text":
                        content_parts.append(piece.get("text", ""))
            elif isinstance(content_delta, str):
                content_parts.append(content_delta)

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
                text_delta = ""
                if isinstance(content_delta, list):
                    text_delta = "".join(
                        piece.get("text", "")
                        for piece in content_delta
                        if isinstance(piece, dict) and piece.get("type") == "text"
                    )
                elif isinstance(content_delta, str):
                    text_delta = content_delta
                observer(
                    {
                        "type": "delta",
                        "content_delta": text_delta,
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
        return {
            "type": "assistant",
            "role": role,
            "content": content or None,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "raw": {"chunks": raw_chunks},
            "usage": last_usage,
        }
