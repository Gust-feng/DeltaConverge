"""Legacy LLM 适配器

包装旧内核的 LLMFactory 和 OpenAIAdapter，实现新的 LLMClientPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from kernel.ports.llm import (
    LLMClientPort,
    LLMFactoryPort,
    LLMResponse,
    Message,
    StreamObserver,
    ToolCall,
    ToolSpec,
)

logger = logging.getLogger(__name__)


class LegacyLLMClient(LLMClientPort):
    """包装旧 LLM 客户端的适配器"""
    
    def __init__(
        self,
        legacy_adapter: Any,
        model: str,
        trace_id: Optional[str] = None,
    ) -> None:
        self._adapter = legacy_adapter
        self._model = model
        self._trace_id = trace_id
        self._closed = False
    
    @property
    def model_name(self) -> str:
        return self._model
    
    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """将 Message 列表转换为旧 API 格式"""
        result = []
        for msg in messages:
            item: Dict[str, Any] = {"role": msg.role.value}
            if msg.content is not None:
                item["content"] = msg.content
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            if msg.name:
                item["name"] = msg.name
            result.append(item)
        return result
    
    def _convert_tools(self, tools: List[ToolSpec]) -> List[Dict[str, Any]]:
        """将 ToolSpec 列表转换为旧 API 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                    "strict": t.strict,
                },
            }
            for t in tools
        ]
    
    def _parse_response(self, raw_response: Any) -> LLMResponse:
        """解析旧 API 响应"""
        content = None
        tool_calls = None
        finish_reason = None
        usage = None
        
        if hasattr(raw_response, "choices") and raw_response.choices:
            choice = raw_response.choices[0]
            if hasattr(choice, "message"):
                msg = choice.message
                content = getattr(msg, "content", None)
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_calls = [
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=tc.function.arguments,
                        )
                        for tc in msg.tool_calls
                    ]
            finish_reason = getattr(choice, "finish_reason", None)
        
        if hasattr(raw_response, "usage") and raw_response.usage:
            usage = {
                "input_tokens": getattr(raw_response.usage, "prompt_tokens", 0),
                "output_tokens": getattr(raw_response.usage, "completion_tokens", 0),
            }
        
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )
    
    def send(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[ToolSpec]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        converted_msgs = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools) if tools else None
        
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": converted_msgs,
        }
        if converted_tools:
            kwargs["tools"] = converted_tools
            kwargs["tool_choice"] = tool_choice or "auto"
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        
        raw_response = self._adapter.client.chat.completions.create(**kwargs)
        return self._parse_response(raw_response)
    
    async def send_async(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[ToolSpec]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        return self.send(messages, tools=tools, tool_choice=tool_choice, temperature=temperature, max_tokens=max_tokens)
    
    def stream(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[ToolSpec]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        observer: Optional[StreamObserver] = None,
    ) -> LLMResponse:
        converted_msgs = self._convert_messages(messages)
        converted_tools = self._convert_tools(tools) if tools else None
        
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": converted_msgs,
            "stream": True,
        }
        if converted_tools:
            kwargs["tools"] = converted_tools
            kwargs["tool_choice"] = tool_choice or "auto"
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        
        content_buffer = ""
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}
        finish_reason = None
        usage = None
        
        try:
            stream = self._adapter.client.chat.completions.create(**kwargs)
            for chunk in stream:
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                if hasattr(delta, "content") and delta.content:
                    content_buffer += delta.content
                    if observer:
                        observer.on_content(delta.content)
                
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_buffer:
                            tool_calls_buffer[idx] = {"id": tc_delta.id or "", "name": "", "arguments": ""}
                            if observer and tc_delta.id:
                                name = tc_delta.function.name if tc_delta.function else ""
                                observer.on_tool_call_start(tc_delta.id, name)
                        
                        if tc_delta.id:
                            tool_calls_buffer[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_buffer[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_buffer[idx]["arguments"] += tc_delta.function.arguments
                                if observer:
                                    observer.on_tool_call_args(tool_calls_buffer[idx]["id"], tc_delta.function.arguments)
                
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
                
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {
                        "input_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                        "output_tokens": getattr(chunk.usage, "completion_tokens", 0),
                    }
        except Exception as e:
            if observer:
                observer.on_error(e)
            raise
        
        tool_calls = None
        if tool_calls_buffer:
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in sorted(tool_calls_buffer.values(), key=lambda x: x["id"])
            ]
            if observer:
                for tc in tool_calls:
                    observer.on_tool_call_end(tc.id)
        
        response = LLMResponse(
            content=content_buffer if content_buffer else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )
        
        if observer:
            observer.on_complete(response)
        
        return response
    
    async def stream_async(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[ToolSpec]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        observer: Optional[StreamObserver] = None,
    ) -> LLMResponse:
        return self.stream(messages, tools=tools, tool_choice=tool_choice, temperature=temperature, max_tokens=max_tokens, observer=observer)
    
    def close(self) -> None:
        self._closed = True
    
    async def aclose(self) -> None:
        self.close()


class LegacyLLMFactory(LLMFactoryPort):
    """包装旧 LLMFactory 的适配器"""
    
    def __init__(self, legacy_factory: Any = None) -> None:
        self._factory = legacy_factory
    
    def _get_factory(self) -> Any:
        if self._factory is None:
            from Agent.core.api.factory import LLMFactory
            self._factory = LLMFactory
        return self._factory
    
    def create_client(
        self,
        model: str,
        *,
        trace_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> LLMClientPort:
        from Agent.core.adapter.llm_adapter import OpenAIAdapter
        
        factory = self._get_factory()
        
        if hasattr(factory, "create_review_client"):
            legacy_client = factory.create_review_client(model_override=model)
        else:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            legacy_client = OpenAIAdapter(client)
        
        return LegacyLLMClient(legacy_client, model, trace_id)
    
    def list_available_models(self) -> List[str]:
        try:
            from Agent.core.api.config import ConfigAPI
            config = ConfigAPI.get_config()
            models = config.get("models", {})
            return list(models.keys()) if models else ["gpt-4"]
        except Exception:
            return ["gpt-4"]
    
    def get_default_model(self, purpose: str = "review") -> str:
        try:
            from Agent.core.api.config import ConfigAPI
            config = ConfigAPI.get_config()
            
            if purpose == "review":
                return config.get("review", {}).get("model", "gpt-4")
            elif purpose == "intent":
                return config.get("intent", {}).get("model", "gpt-4")
            elif purpose == "planner":
                return config.get("planner", {}).get("model", "gpt-4")
            return "gpt-4"
        except Exception:
            return "gpt-4"
