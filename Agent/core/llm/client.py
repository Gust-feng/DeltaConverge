"""LLM client abstractions for the agent framework."""

from __future__ import annotations

import abc
import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, List, Optional

try:  # Optional dependency; real client requires httpx
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv() -> None:
        return None


class BaseLLMClient(abc.ABC):
    """Abstract base class for vendor-specific LLM clients."""

    @abc.abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat completion deltas as dictated by Moonshot/Kimi style APIs."""

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Optional non-streaming request; subclasses may override."""

        raise NotImplementedError("Non-streaming completions not implemented")


from Agent.core.logging.api_logger import APILogger


class MoonshotLLMClient(BaseLLMClient):
    """Async HTTP client that talks to Moonshot's chat.completions API."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        if httpx is None:
            raise RuntimeError("httpx is required for MoonshotLLMClient")
        load_dotenv()
        self.model = model
        self.api_key = api_key or os.getenv("MOONSHOT_API_KEY")
        if not self.api_key:
            raise ValueError("MOONSHOT_API_KEY not found in environment or .env")
        self.base_url = base_url or os.getenv(
            "MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(None))
        self._logger = logger or APILogger()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Call Moonshot streaming API and yield normalized chunks."""

        payload = {"model": self.model, "messages": messages, "stream": True}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions"
        log_path = self._logger.start(
            "stream_chat", {"url": url, "payload": payload}
        )
        async with self._client.stream(
            "POST", url, headers=self._headers(), json=payload
        ) as response:
            self._logger.append(
                log_path,
                "RESPONSE_HEADERS",
                {"status_code": response.status_code, "headers": dict(response.headers)},
            )
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                parsed = json.loads(data)
                self._logger.append(
                    log_path, "RESPONSE_CHUNK", {"raw": line, "parsed": parsed}
                )
                choice = parsed.get("choices", [{}])[0]
                yield {
                    "delta": choice.get("delta", {}),
                    "finish_reason": choice.get("finish_reason"),
                }

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Invoke Moonshot chat completion without streaming."""

        payload = {"model": self.model, "messages": messages, "stream": False}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions"
        log_path = self._logger.start(
            "chat_completion", {"url": url, "payload": payload}
        )
        response = await self._client.post(url, headers=self._headers(), json=payload)
        self._logger.append(
            log_path,
            "RESPONSE_HEADERS",
            {"status_code": response.status_code, "headers": dict(response.headers)},
        )
        response.raise_for_status()
        data = response.json()
        self._logger.append(log_path, "RESPONSE", data)
        return data


class GLMLLMClient(BaseLLMClient):
    """Client for Zhipu GLM API (GLM4.6)."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        if httpx is None:
            raise RuntimeError("httpx is required for GLMLLMClient")
        load_dotenv()
        self.model = model
        self.api_key = api_key or os.getenv("GLM_API_KEY")
        if not self.api_key:
            raise ValueError("GLM_API_KEY not found in environment or .env")
        self.base_url = base_url or os.getenv(
            "GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        )
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(None))
        self._logger = logger or APILogger()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions"
        log_path = self._logger.start(
            "glm_stream_chat", {"url": url, "payload": payload}
        )
        async with self._client.stream(
            "POST", url, headers=self._headers(), json=payload
        ) as response:
            self._logger.append(
                log_path,
                "RESPONSE_HEADERS",
                {"status_code": response.status_code, "headers": dict(response.headers)},
            )
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                parsed = json.loads(data)
                self._logger.append(
                    log_path, "RESPONSE_CHUNK", {"raw": line, "parsed": parsed}
                )
                choice = parsed.get("choices", [{}])[0]
                yield {
                    "delta": choice.get("delta", {}),
                    "finish_reason": choice.get("finish_reason"),
                }

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = {"model": self.model, "messages": messages, "stream": False}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions"
        log_path = self._logger.start(
            "glm_chat_completion", {"url": url, "payload": payload}
        )
        response = await self._client.post(url, headers=self._headers(), json=payload)
        self._logger.append(
            log_path,
            "RESPONSE_HEADERS",
            {"status_code": response.status_code, "headers": dict(response.headers)},
        )
        response.raise_for_status()
        data = response.json()
        self._logger.append(log_path, "RESPONSE", data)
        return data


class MockMoonshotClient(BaseLLMClient):
    """Minimal mock client that emulates Moonshot streaming semantics."""

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Yield deterministic chunks to exercise the adapter stack."""

        last_content = messages[-1]["content"] if messages else ""
        await asyncio.sleep(0.01)
        if "tool:" in last_content:
            tool_id = "ToolName:0"
            yield {
                "delta": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "调用工具 echo_tool"}],
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": "echo_tool",
                                "arguments": '{"text": "hel',
                            },
                        }
                    ],
                },
                "finish_reason": None,
            }
            await asyncio.sleep(0.01)
            yield {
                "delta": {
                    "role": "assistant",
                    "content": [],
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": "echo_tool",
                                "arguments": 'lo from tool"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
            return

        yield {
            "delta": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Review complete."}],
                "tool_calls": [],
            },
            "finish_reason": None,
        }
        await asyncio.sleep(0.01)
        yield {
            "delta": {
                "role": "assistant",
                "content": [{"type": "text", "text": " No issues found."}],
                "tool_calls": [],
            },
            "finish_reason": "stop",
        }

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Return a fake non-streaming response."""

        await asyncio.sleep(0.01)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Mock non-stream response",
                        "tool_calls": [],
                    },
                    "finish_reason": "stop",
                }
            ]
        }
