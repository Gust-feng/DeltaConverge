"""LLM 适配器：规范化不同提供商的响应。"""

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
    """抽象适配器，将厂商特定负载转换为规范格式。"""

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
        """默认以流式优先的方式获取补全。"""

        # stream_chat 是异步生成器，这里先等待获取迭代器再交给收集器
        stream = await self.client.stream_chat(messages, tools=tools, **kwargs)
        normalized = await self.stream_processor.collect(stream, observer=observer)
        normalized["provider"] = self.provider_name
        normalized["tool_schemas"] = tools
        return normalized


class KimiAdapter(LLMAdapter):
    """兼容 Moonshot/Kimi 语义的适配器（流式 + 非流式）。"""

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
            raw_field = normalized.get("raw") or {}
            raw_field["provider"] = f"{self.provider_name}_stream"
            normalized["raw"] = raw_field
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
        usage = response.get("usage")

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
            "usage": usage,
        }

    @staticmethod
    def _safe_parse_arguments(arguments_text: Any) -> Dict[str, Any]:
        if not arguments_text or not isinstance(arguments_text, str):
            return {}
        try:
            return json.loads(arguments_text)
        except json.JSONDecodeError:
            return {"_raw": arguments_text, "_error": "invalid_json"}
