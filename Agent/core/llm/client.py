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
            
        # Extract timeout if present
        timeout = kwargs.pop("timeout", None)
            
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
            "POST", url, headers=self._headers(), json=payload, timeout=timeout
        ) as response:
            self._logger.append(
                log_path,
                "RESPONSE_HEADERS",
                {"status_code": response.status_code, "headers": dict(response.headers)},
            )
            
            if response.is_error:
                error_content = await response.aread()
                error_text = error_content.decode("utf-8", errors="replace")
                self._logger.append(
                    log_path,
                    "ERROR_RESPONSE_BODY",
                    {"status_code": response.status_code, "body": error_text}
                )
                raise RuntimeError(f"API Request Failed ({response.status_code}): {error_text}")

            # response.raise_for_status() # Handled above
            async for line in response.aiter_lines():
                if not line:
                    continue
                
                # 处理 SSE 注释/心跳 (如 OpenRouter 的 ": OPENROUTER PROCESSING")
                if line.startswith(":"):
                    continue

                # 兼容有些非标 API 可能直接返回 JSON 而不是 data: 前缀
                # 或者有些错误信息直接在 body 里
                if line.startswith("data:"):
                    data = line.removeprefix("data:").strip()
                else:
                    # 尝试直接解析，或者是心跳/注释
                    data = line.strip()
                
                if not data or data == "[DONE]":
                    continue
                    
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    # 忽略无法解析的行（可能是注释或心跳），但记录日志
                    self._logger.append(log_path, "WARN_PARSE_FAIL", {"line": line})
                    continue

                chunk_count += 1
                self._logger.append(
                    log_path, "RESPONSE_CHUNK", {"raw": line, "parsed": parsed}
                )
                
                # 某些 API 返回错误结构不同，尝试检测
                if "error" in parsed:
                     raise RuntimeError(f"API Error: {parsed['error']}")

                # 处理可能为空的 choices - MiniMax/某些 API 可能返回空列表
                choices = parsed.get("choices", [])
                if not choices:
                    # 只处理 usage 信息（最后一个 chunk 可能只有 usage）
                    if parsed.get("usage"):
                        final_usage = parsed["usage"]
                    continue
                choice = choices[0]
                usage = parsed.get("usage") or choice.get("usage")
                if usage:
                    final_usage = usage
                delta = choice.get("delta", {})
                content_delta = delta.get("content")
                reasoning_delta = delta.get("reasoning_content")  # Support for DeepSeek reasoning
                # Support MiniMax reasoning_details (可能是列表格式)
                if not reasoning_delta:
                    rd = delta.get("reasoning_details")
                    if rd:
                        if isinstance(rd, list):
                            # MiniMax 格式: [{"text": "...", "type": "text" | "reasoning.text"}, ...]
                            reasoning_delta = "".join(
                                item.get("text", "") for item in rd 
                                if isinstance(item, dict) and item.get("type") in ("text", "reasoning.text")
                            )
                        elif isinstance(rd, str):
                            reasoning_delta = rd
                
                if isinstance(content_delta, list):
                    for piece in content_delta:
                        if (
                            isinstance(piece, dict)
                            and piece.get("type") == "text"
                        ):
                            content_parts.append(piece.get("text", ""))
                elif isinstance(content_delta, str):
                    content_parts.append(content_delta)
                
                # Note: We don't append reasoning to content_parts (which is used for final summary)
                # as reasoning is usually auxiliary.
                
                yield {
                    "delta": delta,
                    "reasoning_content": reasoning_delta, # Explicitly yield reasoning
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
        
        # Extract timeout
        timeout = kwargs.pop("timeout", None)
        
        payload.update(kwargs)
        url = f"{self.base_url}/chat/completions" if "/chat/completions" not in self.base_url else self.base_url
        log_path = self._logger.start(
            f"{self.__class__.__name__.lower().replace('llmclient', '')}_chat_completion", 
            {"url": url, "payload": payload}
        )
        try:
            response = await self._client.post(url, headers=self._headers(), json=payload, timeout=timeout)
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
        
        if response.is_error:
            error_text = response.text
            self._logger.append(
                log_path, "ERROR_RESPONSE_BODY", {"status_code": response.status_code, "body": error_text}
            )
            raise RuntimeError(f"API Request Failed ({response.status_code}): {error_text}")

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
