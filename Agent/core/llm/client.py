"""Agent 框架使用的 LLM 客户端抽象。"""

from __future__ import annotations

import abc
import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, List, Optional

try:  # 可选依赖；真正的客户端需要 httpx
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv() -> None:
        return None

from Agent.core.logging.api_logger import APILogger


def _default_timeout() -> float:
    """返回 LLM 调用的 HTTP 超时秒数（环境变量 LLM_HTTP_TIMEOUT，默认 60s）。"""

    raw = os.getenv("LLM_HTTP_TIMEOUT", "")
    try:
        return float(raw)
    except Exception:
        return 120.0


def _httpx_timeout() -> "httpx.Timeout":
    """构建带合理连接/读取默认值的 httpx.Timeout。"""

    if httpx is None:  # pragma: no cover - 仅在缺少 httpx 时触发
        raise RuntimeError("httpx is required but not installed")
    total = _default_timeout()
    # 连接/写入更容易先挂起；缩短连接超时以尽快失败。
    return httpx.Timeout(
        timeout=total,
        connect=min(10.0, total),
        read=total,
        write=min(10.0, total),
        pool=None,
    )


class BaseLLMClient(abc.ABC):
    """面向各厂商的 LLM 客户端抽象基类。"""

    @abc.abstractmethod
    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """按 Moonshot/Kimi 风格流式返回聊天增量。"""

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """可选的非流式请求；子类可覆盖。"""

        raise NotImplementedError("Non-streaming completions not implemented")


class MoonshotLLMClient(BaseLLMClient):
    """面向 Moonshot chat.completions API 的异步 HTTP 客户端。"""

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
        self._client = httpx.AsyncClient(timeout=_httpx_timeout())
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
        """Call Moonshot streaming API and yield normalized chunks.

        日志策略：
        - 仍然按 REPOSNSE_CHUNK 记录原始流式片段，便于底层调试；
        - 额外在会话结束后写入一条 RESPONSE_SUMMARY，包含组装后的 content 与最终 usage，
          方便人工快速查看完整回复，而不用手动拼 token 片段。
        """

        payload = {"model": self.model, "messages": messages, "stream": True}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions"
        log_path = self._logger.start(
            "stream_chat", {"url": url, "payload": payload}
        )
        content_parts: List[str] = []
        final_usage: Dict[str, Any] | None = None
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
                usage = parsed.get("usage") or choice.get("usage")
                if usage:
                    final_usage = usage
                delta = choice.get("delta", {})
                content_delta = delta.get("content")
                if isinstance(content_delta, list):
                    for piece in content_delta:
                        if (
                            isinstance(piece, dict)
                            and piece.get("type") == "text"
                        ):
                            content_parts.append(piece.get("text", ""))
                elif isinstance(content_delta, str):
                    content_parts.append(content_delta)
                yield {
                    "delta": delta,
                    "finish_reason": choice.get("finish_reason"),
                    "usage": usage,
                }

        # 在流式结束后记录汇总内容，便于人工阅读
        try:
            summary = {
                "content": "".join(content_parts),
                "usage": final_usage,
            }
            self._logger.append(log_path, "RESPONSE_SUMMARY", summary)
        except Exception:
            # 日志记录失败不应影响主逻辑
            pass

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """调用 Moonshot 非流式聊天接口。"""

        payload = {"model": self.model, "messages": messages, "stream": False}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
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
    """智谱 GLM API（GLM4.6）的客户端。"""

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
        self._client = httpx.AsyncClient(timeout=_httpx_timeout())
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
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions"
        log_path = self._logger.start(
            "glm_stream_chat", {"url": url, "payload": payload}
        )
        content_parts: List[str] = []
        final_usage: Dict[str, Any] | None = None
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
                usage = parsed.get("usage") or choice.get("usage")
                if usage:
                    final_usage = usage
                delta = choice.get("delta", {})
                content_delta = delta.get("content")
                if isinstance(content_delta, list):
                    for piece in content_delta:
                        if (
                            isinstance(piece, dict)
                            and piece.get("type") == "text"
                        ):
                            content_parts.append(piece.get("text", ""))
                elif isinstance(content_delta, str):
                    content_parts.append(content_delta)
                yield {
                    "delta": delta,
                    "finish_reason": choice.get("finish_reason"),
                    "usage": usage,
                }

        try:
            summary = {
                "content": "".join(content_parts),
                "usage": final_usage,
            }
            self._logger.append(log_path, "RESPONSE_SUMMARY", summary)
        except Exception:
            pass

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        payload = {"model": self.model, "messages": messages, "stream": False}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
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


class BailianLLMClient(BaseLLMClient):
    """Client for Aliyun Bailian (Model Studio) chat API.

    注意：
    - 该实现假定百炼提供 OpenAI 兼容的 /chat/completions 接口；
      具体 base_url 与模型名称需通过环境变量或参数配置。
    - 请在环境中设置：
      - BAILIAN_API_KEY
      - BAILIAN_BASE_URL（完整的 chat.completions 端点 URL）
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        if httpx is None:
            raise RuntimeError("httpx is required for BailianLLMClient")
        load_dotenv()
        self.model = model
        self.api_key = api_key or os.getenv("BAILIAN_API_KEY")
        if not self.api_key:
            raise ValueError("BAILIAN_API_KEY not found in environment or .env")
        self.base_url = base_url or os.getenv("BAILIAN_BASE_URL")
        if not self.base_url:
            raise ValueError("BAILIAN_BASE_URL not found in environment or .env")
        self._client = httpx.AsyncClient(timeout=_httpx_timeout())
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
        """调用百炼流式接口并返回规范化片段。"""

        payload = {"model": self.model, "messages": messages, "stream": True}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
        payload.update(kwargs)
        url = self.base_url
        log_path = self._logger.start(
            "bailian_stream_chat", {"url": url, "payload": payload}
        )
        content_parts: List[str] = []
        final_usage: Dict[str, Any] | None = None
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
                usage = parsed.get("usage") or choice.get("usage")
                if usage:
                    final_usage = usage
                delta = choice.get("delta", {})
                content_delta = delta.get("content")
                if isinstance(content_delta, list):
                    for piece in content_delta:
                        if (
                            isinstance(piece, dict)
                            and piece.get("type") == "text"
                        ):
                            content_parts.append(piece.get("text", ""))
                elif isinstance(content_delta, str):
                    content_parts.append(content_delta)
                yield {
                    "delta": delta,
                    "finish_reason": choice.get("finish_reason"),
                    "usage": usage,
                }

        try:
            summary = {
                "content": "".join(content_parts),
                "usage": final_usage,
            }
            self._logger.append(log_path, "RESPONSE_SUMMARY", summary)
        except Exception:
            pass

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """调用百炼非流式聊天接口。"""

        payload = {"model": self.model, "messages": messages, "stream": False}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
        payload.update(kwargs)
        url = self.base_url
        log_path = self._logger.start(
            "bailian_chat_completion", {"url": url, "payload": payload}
        )
        try:
            response = await self._client.post(
                url, headers=self._headers(), json=payload
            )
        except Exception as exc:  # pragma: no cover - 网络错误兜底
            err_msg = repr(exc)
            self._logger.append(
                log_path, "ERROR", {"error": err_msg, "type": str(type(exc))}
            )
            raise RuntimeError(err_msg) from exc
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
    """最小化的模拟客户端，复现 Moonshot 的流式语义。"""

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """输出确定性片段以演练适配器链路。"""

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
        """返回一个伪造的非流式响应。"""

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
