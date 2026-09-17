"""LLM 客户端接口定义

定义与大语言模型交互的抽象接口，支持多种 LLM 提供商。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """工具调用信息"""
    id: str
    name: str
    arguments: str  # JSON 字符串


@dataclass
class Message:
    """LLM 消息"""
    role: MessageRole
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None  # 用于 tool 角色的响应
    name: Optional[str] = None  # 可选的名称标识


@dataclass
class ToolSpec:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    strict: bool = False


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None  # stop, tool_calls, length, etc.
    usage: Optional[Dict[str, int]] = None  # input_tokens, output_tokens


@dataclass
class StreamChunk:
    """流式响应块"""
    delta_content: Optional[str] = None
    delta_tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None


class StreamObserver(Protocol):
    """流式响应观察者"""
    
    def on_content(self, content: str) -> None:
        """收到内容片段"""
        ...
    
    def on_tool_call_start(self, tool_call_id: str, name: str) -> None:
        """工具调用开始"""
        ...
    
    def on_tool_call_args(self, tool_call_id: str, args_delta: str) -> None:
        """工具调用参数片段"""
        ...
    
    def on_tool_call_end(self, tool_call_id: str) -> None:
        """工具调用结束"""
        ...
    
    def on_complete(self, response: LLMResponse) -> None:
        """响应完成"""
        ...
    
    def on_error(self, error: Exception) -> None:
        """发生错误"""
        ...


@runtime_checkable
class LLMClientPort(Protocol):
    """LLM 客户端接口
    
    定义与 LLM 服务交互的标准接口。
    实现者需要处理：
    - 消息发送和响应接收
    - 流式响应处理
    - 工具调用支持
    - 错误处理和重试
    """
    
    @property
    def model_name(self) -> str:
        """当前使用的模型名称"""
        ...
    
    def send(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[ToolSpec]] = None,
        tool_choice: Optional[str] = None,  # "auto", "none", "required", or specific tool name
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """同步发送消息并获取响应"""
        ...
    
    async def send_async(
        self,
        messages: List[Message],
        *,
        tools: Optional[List[ToolSpec]] = None,
        tool_choice: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """异步发送消息并获取响应"""
        ...
    
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
        """流式发送消息，通过 observer 接收增量更新，返回完整响应"""
        ...
    
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
        """异步流式发送消息"""
        ...
    
    def close(self) -> None:
        """关闭客户端，释放资源"""
        ...
    
    async def aclose(self) -> None:
        """异步关闭客户端"""
        ...


@dataclass
class LLMRuntimeClient:
    """流水线运行期使用的 LLM 客户端三件套。

    审查流水线需要同时持有底层客户端（用于 ``aclose()`` 生命周期管理）、
    provider 名称（用于事件上报）与已装配好的适配器对象（引擎直接消费）。
    这三者的具体类型由基础设施层决定，application 层只负责搬运，
    因此统一以 ``Any`` 透传，不在端口上泄漏 legacy 类型。
    """

    client: Any = None
    provider: Optional[str] = None
    adapter: Any = None


@runtime_checkable
class LLMFactoryPort(Protocol):
    """LLM 客户端工厂接口
    
    负责创建和管理 LLM 客户端实例。
    """

    def create_runtime_client(
        self,
        model: str,
        *,
        trace_id: Optional[str] = None,
    ) -> LLMRuntimeClient:
        """创建流水线运行期所需的客户端三件套。

        Args:
            model: 模型名称
            trace_id: 追踪 ID

        Returns:
            含底层客户端、provider 名称与已装配适配器的对象
        """
        ...

    def resolve_planner_preference(
        self,
        review_model: str,
        planner_model: Optional[str] = None,
    ) -> str:
        """解析 planner 阶段实际使用的模型偏好。

        planner 显式指定时严格使用该值；未指定时应用内核默认策略。
        """
        ...
    
    def create_client(
        self,
        model: str,
        *,
        trace_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> LLMClientPort:
        """创建 LLM 客户端
        
        Args:
            model: 模型名称（如 gpt-4, claude-3-opus）
            trace_id: 追踪 ID，用于日志关联
            api_key: API 密钥，可选，默认从配置读取
            base_url: API 基础 URL，可选
            
        Returns:
            配置好的 LLM 客户端实例
        """
        ...
    
    def list_available_models(self) -> List[str]:
        """列出可用的模型"""
        ...
    
    def get_default_model(self, purpose: str = "review") -> str:
        """获取指定用途的默认模型
        
        Args:
            purpose: 用途，如 "review", "intent", "planner"
        """
        ...
