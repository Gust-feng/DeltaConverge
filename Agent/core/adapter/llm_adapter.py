"""LLM adapter normalizing responses across providers."""

from __future__ import annotations

import abc
import json
from typing import Any, Dict, List, Optional, TypedDict

from Agent.core.llm.client import BaseLLMClient
from Agent.core.stream.stream_processor import (
    NormalizedMessage,
    NormalizedToolCall,
    StreamProcessor,
)


class ToolDefinition(TypedDict):
    type: str
    function: Dict[str, Any]


class LLMAdapter(abc.ABC):
    """Abstract adapter bridging vendor-specific payloads to normalized format."""

    def __init__(
        self,
        client: BaseLLMClient,
        stream_processor: StreamProcessor,
        provider_name: str = "unknown",
    ) -> None:
        self.client = client
        self.stream_processor = stream_processor
        self.provider_name = provider_name

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[ToolDefinition]] = None,
        observer=None,
        **kwargs: Any,
    ) -> NormalizedMessage:
        """Default streaming-first completion."""

        stream = self.client.stream_chat(messages, tools=tools, **kwargs)
        normalized = await self.stream_processor.collect(stream, observer=observer)
        normalized["provider"] = self.provider_name
        normalized["tool_schemas"] = tools
        return normalized


class KimiAdapter(LLMAdapter):
    """Adapter that understands Moonshot/Kimi semantics (streaming + non-stream)."""

    async def complete(
        self,
        messages: List[Dict[str, Any]],
        stream: bool = True,
        tools: Optional[List[ToolDefinition]] = None,
        observer=None,
        **kwargs: Any,
    ) -> NormalizedMessage:
        if stream:
            normalized = await super().complete(
                messages, tools=tools, observer=observer, **kwargs
            )
            normalized["raw"]["provider"] = f"{self.provider_name}_stream"
            return normalized

        response = await self.client.create_chat_completion(
            messages, tools=tools, **kwargs
        )
        normalized = self._normalize_non_stream_response(response)
        normalized["raw"] = response
        normalized["provider"] = self.provider_name
        normalized["tool_schemas"] = tools
        return normalized

    def _normalize_non_stream_response(
        self,
        response: Dict[str, Any],
    ) -> NormalizedMessage:
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")
        content = message.get("content") or None

        tool_calls: List[NormalizedToolCall] = []
        tool_calls_field = message.get("tool_calls") or []
        if isinstance(tool_calls_field, dict):
            tool_calls_iter = [tool_calls_field]
        elif isinstance(tool_calls_field, list):
            tool_calls_iter = tool_calls_field
        else:
            tool_calls_iter = []
        for call in tool_calls_iter:
            if not isinstance(call, dict):
                continue
            index = call.get("index", len(tool_calls))
            fn = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
            tool_calls.append(
                {
                    "id": call.get("id") or f"call_{index}",
                    "name": fn.get("name") or "unknown_tool",
                    "index": index,
                    "arguments": self._safe_parse_arguments(fn.get("arguments")),
                }
            )

        return {
            "type": "assistant",
            "role": message.get("role", "assistant"),
            "content": content,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "raw": response,
        }

    @staticmethod
    def _safe_parse_arguments(arguments_text: Any) -> Dict[str, Any]:
        if not arguments_text or not isinstance(arguments_text, str):
            return {}
        try:
            return json.loads(arguments_text)
        except json.JSONDecodeError:
            return {"_raw": arguments_text, "_error": "invalid_json"}
