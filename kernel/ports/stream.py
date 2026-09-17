"""流处理接口定义

定义 LLM 流式响应处理的抽象接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Iterator, List, Optional, Protocol, runtime_checkable

from kernel.ports.llm import LLMResponse, StreamObserver, ToolCall


class StreamEventType(str, Enum):
    """流事件类型"""
    CONTENT = "content"           # 文本内容
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_ARGS = "tool_call_args"
    TOOL_CALL_END = "tool_call_end"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class StreamEvent:
    """流事件"""
    type: StreamEventType
    data: Any = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    timestamp: Optional[float] = None


@dataclass
class StreamState:
    """流处理状态"""
    content_buffer: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    current_tool_call_id: Optional[str] = None
    current_tool_args_buffer: str = ""
    is_complete: bool = False
    error: Optional[Exception] = None
    
    # 统计信息
    chunk_count: int = 0
    total_content_length: int = 0
    
    def to_response(self) -> LLMResponse:
        """转换为 LLM 响应"""
        return LLMResponse(
            content=self.content_buffer if self.content_buffer else None,
            tool_calls=self.tool_calls if self.tool_calls else None,
            finish_reason="stop" if self.is_complete else None,
        )


@runtime_checkable
class StreamPort(Protocol):
    """流处理接口
    
    负责处理 LLM 的流式响应。
    """
    
    def process_stream(
        self,
        raw_stream: Iterator[Any],
        *,
        observer: Optional[StreamObserver] = None,
    ) -> LLMResponse:
        """处理同步流
        
        Args:
            raw_stream: 原始流迭代器（来自 LLM API）
            observer: 可选的观察者，用于实时接收更新
            
        Returns:
            完整的 LLM 响应
        """
        ...
    
    async def process_stream_async(
        self,
        raw_stream: AsyncIterator[Any],
        *,
        observer: Optional[StreamObserver] = None,
    ) -> LLMResponse:
        """处理异步流"""
        ...
    
    def create_event_stream(
        self,
        raw_stream: Iterator[Any],
    ) -> Iterator[StreamEvent]:
        """创建事件流
        
        将原始流转换为事件流，便于自定义处理。
        """
        ...
    
    async def create_event_stream_async(
        self,
        raw_stream: AsyncIterator[Any],
    ) -> AsyncIterator[StreamEvent]:
        """创建异步事件流"""
        ...


class StreamBuffer:
    """流缓冲区
    
    用于管理流处理过程中的状态。
    """
    
    def __init__(self) -> None:
        self._state = StreamState()
        self._observers: List[StreamObserver] = []
    
    @property
    def state(self) -> StreamState:
        return self._state
    
    def add_observer(self, observer: StreamObserver) -> None:
        """添加观察者"""
        self._observers.append(observer)
    
    def remove_observer(self, observer: StreamObserver) -> None:
        """移除观察者"""
        self._observers.remove(observer)
    
    def on_content(self, content: str) -> None:
        """处理内容"""
        self._state.content_buffer += content
        self._state.total_content_length += len(content)
        for obs in self._observers:
            obs.on_content(content)
    
    def on_tool_call_start(self, tool_call_id: str, name: str) -> None:
        """处理工具调用开始"""
        self._state.current_tool_call_id = tool_call_id
        self._state.current_tool_args_buffer = ""
        for obs in self._observers:
            obs.on_tool_call_start(tool_call_id, name)
    
    def on_tool_call_args(self, tool_call_id: str, args_delta: str) -> None:
        """处理工具调用参数"""
        self._state.current_tool_args_buffer += args_delta
        for obs in self._observers:
            obs.on_tool_call_args(tool_call_id, args_delta)
    
    def on_tool_call_end(self, tool_call_id: str, name: str) -> None:
        """处理工具调用结束"""
        tool_call = ToolCall(
            id=tool_call_id,
            name=name,
            arguments=self._state.current_tool_args_buffer,
        )
        self._state.tool_calls.append(tool_call)
        self._state.current_tool_call_id = None
        self._state.current_tool_args_buffer = ""
        for obs in self._observers:
            obs.on_tool_call_end(tool_call_id)
    
    def on_complete(self, response: LLMResponse) -> None:
        """处理完成"""
        self._state.is_complete = True
        for obs in self._observers:
            obs.on_complete(response)
    
    def on_error(self, error: Exception) -> None:
        """处理错误"""
        self._state.error = error
        for obs in self._observers:
            obs.on_error(error)
    
    def get_response(self) -> LLMResponse:
        """获取当前响应"""
        return self._state.to_response()
    
    def reset(self) -> None:
        """重置状态"""
        self._state = StreamState()
