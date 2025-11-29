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
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

from Agent.core.logging.api_logger import APILogger


def _default_timeout() -> float:
    """返回 LLM 调用的 HTTP 超时秒数（环境变量 LLM_HTTP_TIMEOUT，默认 60s）。"""

    raw = os.getenv("LLM_HTTP_TIMEOUT", "")
    try:
        return float(raw)
    except Exception:
        return 120.0


def _httpx_timeout() -> Any:
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

    async def aclose(self) -> None:
        """清理资源。"""
        pass


class OpenAIClientBase(BaseLLMClient):
    """兼容 OpenAI 格式的客户端基类，提取公共逻辑。"""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        default_base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        if httpx is None:
            raise RuntimeError(f"httpx is required for {self.__class__.__name__}")
        load_dotenv()
        self.model = model
        self.api_key = api_key or (os.getenv(api_key_env) if api_key_env else None)
        if not self.api_key:
            raise ValueError(f"{api_key_env or 'api_key'} not found in environment or .env")
        base_url_final = base_url or os.getenv("BASE_URL") or default_base_url or ""
        if not base_url_final:
            raise ValueError(f"Base URL not found. Please check your configuration.")
        self.base_url = base_url_final
        self._client = httpx.AsyncClient(timeout=_httpx_timeout())
        self._logger = logger or APILogger()

    async def aclose(self) -> None:
        """关闭 HTTP 客户端连接。"""
        if hasattr(self, '_client') and self._client:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

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
        """Call OpenAI-compatible streaming API and yield normalized chunks."""

        payload = {"model": self.model, "messages": messages, "stream": True}
        # 如果是智谱或百炼，可能需要显式开启 reasoning/search 等参数
        # 但 OpenAI 标准接口无 reasoning 参数，通常是模型自带行为。
        # 针对一些魔改 API，我们尝试透传 enable_reasoning (如果 kwargs 有)
        # 或者在这里强制注入特定厂商参数。
        # 目前为了兼容 部分模型，我们尝试注入 reasoning_format 或类似参数（如果需要）。
        # 另外，Moonshot/Kimi 不需要额外参数。
        # 都是后话
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
            
        # 强制透传 kwargs 里的剩余参数（比如 temperature, top_p, 以及可能的 vendor specific params）
        payload.update(kwargs)
        
        url = f"{self.base_url}/chat/completions" if "/chat/completions" not in self.base_url else self.base_url
        log_path = self._logger.start(
            f"{self.__class__.__name__.lower().replace('llmclient', '')}_stream_chat", 
            {"url": url, "payload": payload}
        )
        content_parts: List[str] = []
        final_usage: Dict[str, Any] | None = None
        chunk_count = 0
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
                chunk_count += 1
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
                "chunk_count": chunk_count,
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
        """调用 OpenAI 兼容的非流式聊天接口。"""

        payload = {"model": self.model, "messages": messages, "stream": False}
        tools = kwargs.pop("tools", None)
        if tools:
            payload["tools"] = tools
        response_format = kwargs.pop("response_format", None)
        if response_format:
            payload["response_format"] = response_format
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions" if "/chat/completions" not in self.base_url else self.base_url
        log_path = self._logger.start(
            f"{self.__class__.__name__.lower().replace('llmclient', '')}_chat_completion", 
            {"url": url, "payload": payload}
        )
        try:
            response = await self._client.post(url, headers=self._headers(), json=payload)
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


class MoonshotLLMClient(OpenAIClientBase):
    """面向 Moonshot chat.completions API 的异步 HTTP 客户端。"""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_key_env="MOONSHOT_API_KEY",
            default_base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
            logger=logger,
        )


class GLMLLMClient(OpenAIClientBase):
    """智谱 GLM API的客户端。"""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_key_env="GLM_API_KEY",
            default_base_url=os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
            logger=logger,
        )


class BailianLLMClient(OpenAIClientBase):
    # 百炼的客户端

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_key_env="BAILIAN_API_KEY",
            default_base_url=os.getenv("BAILIAN_BASE_URL"),
            logger=logger,
        )


class ModelScopeLLMClient(OpenAIClientBase):
    # 魔搭的客户端
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_key_env="MODELSCOPE_API_KEY",
            default_base_url=os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"),
            logger=logger,
        )

class OpenRouterLLMClient(OpenAIClientBase):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        logger: APILogger | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            api_key_env="OPENROUTER_API_KEY",
            default_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            logger=logger,
        )
# 测试用的模拟客户端
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
