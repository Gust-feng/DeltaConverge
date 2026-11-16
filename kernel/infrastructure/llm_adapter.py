"""Legacy LLM 适配器

包装旧内核的 LLMFactory 和 OpenAIAdapter，实现新的 LLMClientPort 接口。
"""
from __future__ import annotations

import logging
import asyncio
import json
from typing import Any, Dict, List, Optional

from kernel.ports.llm import (
    LLMClientPort,
    LLMFactoryPort,
    LLMResponse,
    LLMRuntimeClient,
    Message,
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
    
    @staticmethod
    def _parse_response(raw: Dict[str, Any]) -> LLMResponse:
        calls = raw.get("tool_calls") or []
        usage = raw.get("usage")
        return LLMResponse(
            content=raw.get("content"),
            tool_calls=[ToolCall(id=c["id"], name=c["name"], arguments=json.dumps(c["arguments"], ensure_ascii=False)) for c in calls] or None,
            finish_reason=raw.get("finish_reason"),
            usage={"input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                   "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0))} if usage else None,
        )

    async def _complete(self, messages, *, tools=None, tool_choice=None, temperature=None,
                        max_tokens=None, observer=None, stream=True):
        options = {k: v for k, v in {"tool_choice": tool_choice, "temperature": temperature,
                                      "max_tokens": max_tokens}.items() if v is not None}
        started = set()
        def on_delta(event):
            if not observer:
                return
            if event.get("content_delta"):
                observer.on_content(event["content_delta"])
            for call in event.get("tool_calls_delta", []):
                call_id = call.get("id")
                fn = call.get("function") or {}
                index = call.get("index", 0)
                if call_id:
                    started.add((index, call_id))
                    observer.on_tool_call_start(call_id, fn.get("name") or "")
                current_id = next((i for n, i in started if n == index), call_id or "")
                if fn.get("arguments"):
                    observer.on_tool_call_args(current_id, fn["arguments"])
        try:
            raw = await self._adapter.complete(self._convert_messages(messages),
                tools=self._convert_tools(tools) if tools else None, stream=stream,
                observer=on_delta if observer else None, **options)
            response = self._parse_response(raw)
            if observer:
                for call in response.tool_calls or []:
                    observer.on_tool_call_end(call.id)
                observer.on_complete(response)
            return response
        except Exception as exc:
            if observer:
                observer.on_error(exc)
            raise

    @staticmethod
    def _ensure_sync_context():
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError("Use the async LLM methods inside an event loop")

    def send(self, messages, **kwargs):
        self._ensure_sync_context()
        return asyncio.run(self.send_async(messages, **kwargs))

    async def send_async(self, messages, **kwargs):
        return await self._complete(messages, stream=False, **kwargs)

    def stream(self, messages, **kwargs):
        self._ensure_sync_context()
        return asyncio.run(self.stream_async(messages, **kwargs))

    async def stream_async(self, messages, **kwargs):
        return await self._complete(messages, stream=True, **kwargs)

    def close(self) -> None:
        if not self._closed:
            self._ensure_sync_context()
            asyncio.run(self.aclose())

    async def aclose(self) -> None:
        if self._closed:
            return
        await self._adapter.client.aclose()
        self._closed = True


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
        if api_key is not None or base_url is not None:
            raise ValueError("Configure API key and base URL through the provider configuration")
        runtime = self.create_runtime_client(model, trace_id=trace_id)
        return LegacyLLMClient(runtime.adapter, model, trace_id)

    def create_runtime_client(
        self,
        model: str,
        *,
        trace_id: Optional[str] = None,
    ) -> LLMRuntimeClient:
        """创建流水线运行期所需的客户端三件套（client / provider / adapter）。"""
        from Agent.core.adapter.llm_adapter import OpenAIAdapter
        from Agent.core.stream.stream_processor import StreamProcessor

        factory = self._get_factory()

        # 统一走旧工厂 create，确保 provider 与 client 对齐
        client, provider = factory.create(model, trace_id=trace_id)
        adapter = OpenAIAdapter(client, StreamProcessor(), provider_name=provider)
        return LLMRuntimeClient(client=client, provider=provider, adapter=adapter)

    def resolve_planner_preference(
        self,
        review_model: str,
        planner_model: Optional[str] = None,
    ) -> str:
        """解析 planner 阶段实际使用的模型偏好。"""
        from Agent.core.api.api import resolve_planner_preference

        return resolve_planner_preference(review_model, planner_model)
    
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
