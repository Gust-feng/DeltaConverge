"""Agent 框架使用的 LLM 客户端抽象。"""

from __future__ import annotations

import abc
import asyncio
import os
import ssl
from typing import Any, AsyncIterator, Dict, List

try:  # 可选依赖；真正的客户端需要 httpx
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from Agent.core.logging.api_logger import APILogger


def _default_timeout() -> float:
    """返回 LLM 调用的 HTTP 超时秒数。
    
    优先从 ConfigAPI 读取 call_timeout，fallback 到环境变量 LLM_HTTP_TIMEOUT，最后使用默认值 300s。
    """
    # 优先从 ConfigAPI 读取
    try:
        from Agent.core.api.config import get_llm_call_timeout
        return get_llm_call_timeout(default=300.0)
    except Exception:
        pass
    
    # Fallback 到环境变量
    raw = os.getenv("LLM_HTTP_TIMEOUT", "")
    try:
        return float(raw)
    except Exception:
        return 300.0


def _httpx_verify() -> Any:
    """构建 httpx 的 TLS 校验配置。

    httpx 默认只信任 certifi 的 Mozilla 根证书；在启用 TLS 拦截代理的机器上
    （企业代理/本地安全软件），代理根证书通常装在操作系统信任库里，certifi
    里没有，表现为 ``CERTIFICATE_VERIFY_FAILED: self-signed certificate``。
    这里优先使用系统默认信任库，系统库为空时再回退到 certifi。
    """
    try:
        context = ssl.create_default_context()
        if not context.get_ca_certs():
            import certifi

            context.load_verify_locations(certifi.where())
        return context
    except Exception:
        # 极端环境下退回 httpx 默认行为（certifi）
        return True


def default_httpx_verify() -> Any:
    """供模型发现等非 LLM 请求复用的 TLS 校验配置（系统信任库优先）。"""
    return _httpx_verify()


def _httpx_timeout() -> Any:
    """构建带合理连接/读取默认值的 httpx.Timeout。"""

    if httpx is None:  # pragma: no cover - 仅在缺少 httpx 时触发
        raise RuntimeError("httpx is required but not installed")
    total = _default_timeout()
    # 连接/写入更容易先挂起；缩短连接超时以尽快失败。
    return httpx.Timeout(
        timeout=total,
        connect=min(60.0, total),
        read=total,
        write=min(60.0, total),
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
        # 假设上层已完成环境加载，此处不再重复调用 load_dotenv()
        
        self.model = model
        self.api_key = api_key or (os.getenv(api_key_env) if api_key_env else None)
        if not self.api_key:
            raise ValueError(f"{api_key_env or 'api_key'} not found in environment or .env")
        base_url_final = base_url or os.getenv("BASE_URL") or default_base_url or ""
        if not base_url_final:
            raise ValueError("Base URL not found. Please check your configuration.")
        self.base_url = base_url_final.rstrip("/").removesuffix("/chat/completions")
        self._client = httpx.AsyncClient(timeout=_httpx_timeout(), verify=_httpx_verify())
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

        if getattr(self, "protocol", "chat_completions") == "responses":
            from Agent.core.llm.responses import stream
            async for chunk in stream(self, messages, kwargs):
                yield chunk
            return

        from openai import AsyncOpenAI
        sdk = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
                          http_client=self._client, max_retries=0)
        options = self._chat_options(kwargs)
        messages = self._chat_messages(messages)
        log_path = self._logger.start("chat_stream", {"model": self.model, "messages": messages, "options": options})
        from Agent.core.llm.request_compat import create_with_compat
        try:
            stream = await create_with_compat(self, sdk.chat.completions.create, {
                "model": self.model, "messages": messages, "stream": True, **options,
            }, log_path)
        except Exception as exc:
            self._logger.append(log_path, "ERROR", {"type": type(exc).__name__, "error": str(exc)})
            raise
        finished = False
        try:
            async for item in stream:
                parsed = item.model_dump(exclude_none=True)
                self._logger.append(log_path, "RESPONSE_CHUNK", parsed)
                choices = parsed.get("choices") or []
                if not choices:
                    if parsed.get("usage"):
                        yield {"delta": {}, "usage": parsed["usage"], "finish_reason": None}
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning_details")
                if isinstance(reasoning, list):
                    reasoning = "".join(part.get("text", "") for part in reasoning if isinstance(part, dict))
                finished = finished or bool(choice.get("finish_reason"))
                yield {"delta": delta, "reasoning_content": reasoning,
                       "finish_reason": choice.get("finish_reason"), "usage": parsed.get("usage")}
            if not finished:
                raise RuntimeError("LLM stream ended without a finish reason")
            self._logger.append(log_path, "RESPONSE_SUMMARY", {"finished": True})
        except Exception as exc:
            self._logger.append(log_path, "ERROR", {"type": type(exc).__name__, "error": str(exc)})
            raise
        finally:
            await stream.close()

    def _chat_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        provider = getattr(self, "provider_name", "")
        result = []
        for message in messages:
            item = {k: v for k, v in message.items() if k not in {"_response_items", "error"}}
            if provider == "minimax":
                item.pop("reasoning_content", None)
            elif provider in {"deepseek", "glm"}:
                item.pop("reasoning_details", None)
            else:
                item.pop("reasoning_content", None)
                item.pop("reasoning_details", None)
            if message.get("role") == "tool" and message.get("error"):
                item["content"] = str(message["error"])
            result.append(item)
        return result

    @staticmethod
    def _chat_options(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        from Agent.core.llm.request_compat import normalize_options
        options = normalize_options(kwargs)
        options.pop("enable_reasoning", None)
        options.pop("include_reasoning_content", None)
        if not options.get("tools"):
            options.pop("tools", None)
            options.pop("tool_choice", None)
            options.pop("parallel_tool_calls", None)
        options.pop("response_format", None) if not options.get("response_format") else None
        if "max_output_tokens" in options:
            options["max_tokens"] = options.pop("max_output_tokens")
        standard = {"tools", "response_format", "temperature", "top_p", "max_tokens", "max_completion_tokens",
                    "tool_choice", "parallel_tool_calls", "timeout", "seed", "stop", "stream_options",
                    "frequency_penalty", "presence_penalty"}
        extra = dict(options.pop("extra_body", {}) or {})
        extra.update({key: options.pop(key) for key in list(options) if key not in standard})
        if extra:
            options["extra_body"] = extra
        return options

    async def create_chat_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        from openai import AsyncOpenAI
        if getattr(self, "protocol", "chat_completions") == "responses":
            from Agent.core.llm.responses import complete
            return await complete(self, messages, kwargs)
        sdk = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url,
                          http_client=self._client, max_retries=0)
        messages = self._chat_messages(messages)
        options = self._chat_options(kwargs)
        log_path = self._logger.start("chat_completion", {"model": self.model, "messages": messages, "options": options})
        from Agent.core.llm.request_compat import create_with_compat
        try:
            result = await create_with_compat(self, sdk.chat.completions.create, {
                "model": self.model, "messages": messages, "stream": False, **options,
            }, log_path)
            response = result.model_dump(exclude_none=True)
            self._logger.append(log_path, "RESPONSE", response)
            return response
        except Exception as exc:
            self._logger.append(log_path, "ERROR", {"type": type(exc).__name__, "error": str(exc)})
            raise


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
    """智谱 GLM API的客户端，支持 GLM-4.7 深度思考模式。
    
    GLM-4.7 特性：
    - 默认开启 Thinking 模式
    - 使用 thinking: {type: "enabled", clear_thinking: false} 启用"保留式思考"
    - 思考内容在 reasoning_content 字段（与 DeepSeek 相同）
    - 多轮对话需要将 reasoning_content 传回历史
    """

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

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        thinking = kwargs.pop("thinking", None)
        enable_reasoning = bool(kwargs.pop("enable_reasoning", None))
        include_reasoning_content = bool(kwargs.pop("include_reasoning_content", None))
        
        # 如果没有显式指定 thinking 参数，根据模型和 enable_reasoning 决定
        if thinking is None:
            if enable_reasoning or include_reasoning_content:
                # 启用保留式思考：clear_thinking=false 保留思考链
                kwargs["thinking"] = {"type": "enabled", "clear_thinking": False}
        else:
            kwargs["thinking"] = thinking
        return super().stream_chat(messages, **kwargs)

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        thinking = kwargs.pop("thinking", None)
        enable_reasoning = bool(kwargs.pop("enable_reasoning", None))
        include_reasoning_content = bool(kwargs.pop("include_reasoning_content", None))
        
        if thinking is None:
            if enable_reasoning or include_reasoning_content:
                kwargs["thinking"] = {"type": "enabled", "clear_thinking": False}
        else:
            kwargs["thinking"] = thinking
        return await super().create_chat_completion(messages, **kwargs)


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


class SiliconFlowLLMClient(OpenAIClientBase):
    """SiliconFlow (硅基流动) 的客户端"""

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
            api_key_env="SILICONFLOW_API_KEY",
            default_base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            logger=logger,
        )
class DeepSeekLLMClient(OpenAIClientBase):
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
            api_key_env="DEEPSEEK_API_KEY",
            default_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            logger=logger,
        )

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        thinking = kwargs.pop("thinking", None)
        enable_reasoning = bool(kwargs.pop("enable_reasoning", None))
        include_reasoning_content = bool(kwargs.pop("include_reasoning_content", None))
        if thinking is None:
            if enable_reasoning or include_reasoning_content:
                kwargs["thinking"] = {"type": "enabled"}
        else:
            kwargs["thinking"] = thinking
        return super().stream_chat(messages, **kwargs)

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        thinking = kwargs.pop("thinking", None)
        enable_reasoning = bool(kwargs.pop("enable_reasoning", None))
        include_reasoning_content = bool(kwargs.pop("include_reasoning_content", None))
        if thinking is None:
            if enable_reasoning or include_reasoning_content:
                kwargs["thinking"] = {"type": "enabled"}
        else:
            kwargs["thinking"] = thinking
        return await super().create_chat_completion(messages, **kwargs)


class MiniMaxLLMClient(OpenAIClientBase):
    """MiniMax API 客户端，支持 M2 系列模型的 Interleaved Thinking。
    
    MiniMax 特殊性：
    - 使用 reasoning_details 字段（而非 reasoning_content）
    - 需要 reasoning_split: True 来分离思考内容
    - 否则思考内容会以 <think>...</think> 标签混入 content
    """

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
            api_key_env="MINIMAX_API_KEY",
            default_base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
            logger=logger,
        )

    def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        # 自动启用 reasoning_split 以分离思考内容
        # 这样 reasoning 会进入 reasoning_details 字段，而不是混入 content
        if "reasoning_split" not in kwargs:
            kwargs["reasoning_split"] = True
        # 启用流式响应中的 usage 信息返回（OpenAI 兼容的 stream_options）
        # 这样 API 会在最后一个 chunk 中返回 token 使用统计
        if "stream_options" not in kwargs:
            kwargs["stream_options"] = {"include_usage": True}
        return super().stream_chat(messages, **kwargs)

    async def create_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if "reasoning_split" not in kwargs:
            kwargs["reasoning_split"] = True
        return await super().create_chat_completion(messages, **kwargs)


# 测试用的模拟客户端
class MockMoonshotClient(BaseLLMClient):
    """最小化的模拟客户端，复现流式语义。"""

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[Dict[str, Any]]:
        """输出确定性片段以演练适配器链路。"""

        last_msg = messages[-1] if messages else {}
        last_role = last_msg.get("role")
        last_content = last_msg.get("content", "") or ""
        tools = kwargs.get("tools", [])

        await asyncio.sleep(0.01)
        
        # Simulate reasoning process
        yield {
            "delta": {
                "role": "assistant",
                "reasoning_content": "Mock reasoning process: analyzing the user request...",
            },
            "finish_reason": None,
        }
        await asyncio.sleep(0.01)
        
        # 1. 如果上一条是工具结果，说明已经调用过工具，直接返回总结
        if last_role == "tool":
            yield {
                "delta": {
                    "role": "assistant",
                    "reasoning_content": " tool execution completed. Generating final report.",
                },
                "finish_reason": None,
            }
            await asyncio.sleep(0.01)
            yield {
                "delta": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "All checks look normal"}],
                    "tool_calls": [],
                },
                "finish_reason": "stop",
            }
            return

        # 2. 如果有可用工具，且不是在工具结果后（即第一轮），尝试调用第一个工具
        # 优先匹配 list_directory 以模拟真实场景
        target_tool = None
        if tools:
            for t in tools:
                fname = t.get("function", {}).get("name")
                if fname == "list_directory":
                    target_tool = ("list_directory", '{"path": "."}')
                    break
                if fname == "echo_tool":
                    target_tool = ("echo_tool", '{"text": "hello from mock"}')
                    break
            
            # 如果没找到特定工具但列表不为空，随便拿第一个
            if not target_tool and tools:
                first = tools[0]
                fname = first.get("function", {}).get("name")
                target_tool = (fname, '{}')

        # 触发工具调用
        if target_tool or "tool:" in str(last_content):
            tool_name, tool_args = target_tool or ("echo_tool", '{"text": "hello"}')
            tool_id = f"call_{tool_name}_mock"
            
            yield {
                "delta": {
                    "role": "assistant",
                    "reasoning_content": f" deciding to call tool: {tool_name}",
                },
                "finish_reason": None,
            }
            
            yield {
                "delta": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": f"Calling tool {tool_name}..."}],
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": tool_args[: len(tool_args) // 2], # Split for streaming simulation
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
                                "name": tool_name,
                                "arguments": tool_args[len(tool_args) // 2 :],
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
            return

        # 3. 兜底：没有工具或不想调用，直接返回
        yield {
            "delta": {
                "role": "assistant",
                "reasoning_content": " no tools needed or available.",
            },
            "finish_reason": None,
        }
        await asyncio.sleep(0.01)
        yield {
            "delta": {
                "role": "assistant",
                "content": [{"type": "text", "text": "No issues, normal output"}],
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
