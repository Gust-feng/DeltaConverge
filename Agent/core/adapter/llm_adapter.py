"""LLM 适配器：规范化不同提供商的响应。"""

from __future__ import annotations

import abc
import json
from typing import Any, Dict, List, Optional, TypedDict, AsyncIterator, cast

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
        response_format: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> NormalizedMessage:
        """默认以流式优先的方式获取补全。"""

        # 按能力决定是否透传结构化输出参数
        # 支持 response_format 的提供商：openrouter, minimax（OpenAI兼容）
        if response_format and self.provider_name not in {"openrouter", "minimax"}:
            response_format = None

        # stream_chat 返回异步生成器，直接交给收集器消费
        extra_kwargs: Dict[str, Any] = dict(kwargs)
        if response_format:
            extra_kwargs["response_format"] = response_format
        stream = cast(AsyncIterator[Dict[str, Any]], self.client.stream_chat(messages, tools=tools, **extra_kwargs))
        normalized = await self.stream_processor.collect(stream, observer=observer)
        normalized["provider"] = self.provider_name
        normalized["tool_schemas"] = tools
        return normalized


class OpenAIAdapter(LLMAdapter):
    """兼容 OpenAI 语义的适配器（流式 + 非流式），支持所有 OpenAI 兼容的 API。"""

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
            raw_field["source"] = "stream"
            normalized["raw"] = raw_field
            return normalized

        response = await self.client.create_chat_completion(
            messages, tools=tools, **kwargs
        )
        normalized = self._normalize_non_stream_response(response)
        normalized["provider"] = self.provider_name
        normalized["tool_schemas"] = tools
        return normalized

    @staticmethod
    def _safe_json_loads(s: str, max_nesting: int = 50) -> Any:
        """安全加载JSON并校验最大嵌套深度。"""
        obj = json.loads(s)
        def _depth(x: Any, d: int = 0) -> int:
            if isinstance(x, dict):
                if not x:
                    return d + 1
                return max(_depth(v, d + 1) for v in x.values())
            if isinstance(x, list):
                if not x:
                    return d + 1
                return max(_depth(v, d + 1) for v in x)
            return d
        if _depth(obj) > max_nesting:
            raise json.JSONDecodeError("JSON nesting too deep", s, 0)
        return obj
    
    def _normalize_non_stream_response(
        self,
        response: Dict[str, Any],
    ) -> NormalizedMessage:
        """将非流式响应转换为规范化消息格式。"""
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")
        content = message.get("content") or None
        
        # 支持多种 reasoning 字段格式
        reasoning = message.get("reasoning_content")
        if not reasoning:
            # MiniMax 使用 reasoning_details，可能是列表格式
            rd = message.get("reasoning_details")
            if rd:
                if isinstance(rd, list):
                    # MiniMax 格式: [{"text": "...", "type": "text" | "reasoning.text"}, ...]
                    reasoning = "".join(
                        item.get("text", "") for item in rd 
                        if isinstance(item, dict) and item.get("type") in ("text", "reasoning.text")
                    )
                elif isinstance(rd, str):
                    reasoning = rd
        
        # 清理 content 中可能混入的 <think> 标签（复用 StreamProcessor 的方法）
        if isinstance(content, str) and ('<think>' in content or '</think>' in content):
            content, extra_reasoning = StreamProcessor._strip_think_tags(content, [])
            if extra_reasoning:
                if reasoning:
                    reasoning = reasoning + "\n\n" + "\n\n".join(extra_reasoning)
                else:
                    reasoning = "\n\n".join(extra_reasoning)
            content = content or None
        
        usage = response.get("usage")
        
        # 尝试解析 JSON 内容
        content_json: Dict[str, Any] | List[Any] | None = None
        if isinstance(content, str) and content and len(content) < 1024 * 1024:  # 1MB 限制
            try:
                parsed = self._safe_json_loads(content)
                if isinstance(parsed, (dict, list)):
                    content_json = parsed
            except json.JSONDecodeError:
                content_json = None

        # 处理工具调用
        tool_calls: List[NormalizedToolCall] = []
        tool_calls_field = message.get("tool_calls", [])
        tool_calls_iter = [tool_calls_field] if isinstance(tool_calls_field, dict) else tool_calls_field if isinstance(tool_calls_field, list) else []
        
        for call in tool_calls_iter:
            if not isinstance(call, dict):
                continue
            index = call.get("index", len(tool_calls))
            fn = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
            
            tool_calls.append({
                "id": call.get("id") or f"call_{index}",
                "name": fn.get("name") or "unknown_tool",
                "index": index,
                "arguments": self._safe_parse_arguments(fn.get("arguments")),
            })

        return {
            "type": "assistant",
            "role": message.get("role", "assistant"),
            "content": content,
            "content_json": content_json,
            "reasoning": reasoning,
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "raw": {"response": response, "source": "non_stream"},
            "usage": usage,
        }

    @staticmethod
    def _safe_parse_arguments(arguments_text: Any) -> Dict[str, Any]:
        """安全解析工具调用参数，处理无效 JSON 情况。"""
        if not arguments_text or not isinstance(arguments_text, str):
            return {}
        try:
            return OpenAIAdapter._safe_json_loads(arguments_text)
        except json.JSONDecodeError:
            return {"_raw": arguments_text, "_error": "invalid_json"}


# 保持向后兼容，KimiAdapter 作为 OpenAIAdapter 的别名
KimiAdapter = OpenAIAdapter
