"""Legacy 流处理适配器

包装旧内核的 StreamProcessor，实现新的 StreamPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Iterator, Optional

from kernel.ports.llm import LLMResponse, StreamObserver, ToolCall
from kernel.ports.stream import StreamBuffer, StreamEvent, StreamEventType, StreamPort

logger = logging.getLogger(__name__)


class LegacyStreamAdapter(StreamPort):
    """包装旧 StreamProcessor 的适配器"""
    
    def process_stream(
        self,
        raw_stream: Iterator[Any],
        *,
        observer: Optional[StreamObserver] = None,
    ) -> LLMResponse:
        """处理同步流"""
        buffer = StreamBuffer()
        if observer:
            buffer.add_observer(observer)
        
        try:
            for chunk in raw_stream:
                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue
                
                choice = chunk.choices[0]
                delta = choice.delta
                
                # 处理内容
                if hasattr(delta, "content") and delta.content:
                    buffer.on_content(delta.content)
                
                # 处理工具调用
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        tc_id = getattr(tc_delta, "id", None)
                        
                        if tc_id and not buffer.state.current_tool_call_id:
                            # 新工具调用开始
                            func = getattr(tc_delta, "function", None)
                            name = func.name if func and hasattr(func, "name") else ""
                            buffer.on_tool_call_start(tc_id, name)
                        
                        # 处理参数增量
                        if hasattr(tc_delta, "function") and tc_delta.function:
                            func = tc_delta.function
                            if hasattr(func, "arguments") and func.arguments:
                                current_id = buffer.state.current_tool_call_id or tc_id or ""
                                buffer.on_tool_call_args(current_id, func.arguments)
                
                # 处理完成
                if hasattr(choice, "finish_reason") and choice.finish_reason:
                    # 如果有未完成的工具调用，结束它
                    if buffer.state.current_tool_call_id:
                        # 找到工具名称
                        name = ""
                        for tc in buffer.state.tool_calls:
                            if tc.id == buffer.state.current_tool_call_id:
                                name = tc.name
                                break
                        buffer.on_tool_call_end(buffer.state.current_tool_call_id, name or "unknown")
        
        except Exception as e:
            buffer.on_error(e)
            raise
        
        # 获取最终响应
        response = buffer.get_response()
        buffer.on_complete(response)
        
        return response
    
    async def process_stream_async(
        self,
        raw_stream: AsyncIterator[Any],
        *,
        observer: Optional[StreamObserver] = None,
    ) -> LLMResponse:
        """处理异步流"""
        buffer = StreamBuffer()
        if observer:
            buffer.add_observer(observer)
        
        try:
            async for chunk in raw_stream:
                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue
                
                choice = chunk.choices[0]
                delta = choice.delta
                
                if hasattr(delta, "content") and delta.content:
                    buffer.on_content(delta.content)
                
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        tc_id = getattr(tc_delta, "id", None)
                        
                        if tc_id and not buffer.state.current_tool_call_id:
                            func = getattr(tc_delta, "function", None)
                            name = func.name if func and hasattr(func, "name") else ""
                            buffer.on_tool_call_start(tc_id, name)
                        
                        if hasattr(tc_delta, "function") and tc_delta.function:
                            func = tc_delta.function
                            if hasattr(func, "arguments") and func.arguments:
                                current_id = buffer.state.current_tool_call_id or tc_id or ""
                                buffer.on_tool_call_args(current_id, func.arguments)
                
                if hasattr(choice, "finish_reason") and choice.finish_reason:
                    if buffer.state.current_tool_call_id:
                        name = ""
                        for tc in buffer.state.tool_calls:
                            if tc.id == buffer.state.current_tool_call_id:
                                name = tc.name
                                break
                        buffer.on_tool_call_end(buffer.state.current_tool_call_id, name or "unknown")
        
        except Exception as e:
            buffer.on_error(e)
            raise
        
        response = buffer.get_response()
        buffer.on_complete(response)
        
        return response
    
    def create_event_stream(
        self,
        raw_stream: Iterator[Any],
    ) -> Iterator[StreamEvent]:
        """创建事件流"""
        for chunk in raw_stream:
            if not hasattr(chunk, "choices") or not chunk.choices:
                continue
            
            choice = chunk.choices[0]
            delta = choice.delta
            
            if hasattr(delta, "content") and delta.content:
                yield StreamEvent(
                    type=StreamEventType.CONTENT,
                    data=delta.content,
                )
            
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    tc_id = getattr(tc_delta, "id", None)
                    if tc_id:
                        func = getattr(tc_delta, "function", None)
                        name = func.name if func and hasattr(func, "name") else ""
                        yield StreamEvent(
                            type=StreamEventType.TOOL_CALL_START,
                            tool_call_id=tc_id,
                            tool_name=name,
                        )
                    
                    if hasattr(tc_delta, "function") and tc_delta.function:
                        func = tc_delta.function
                        if hasattr(func, "arguments") and func.arguments:
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_ARGS,
                                data=func.arguments,
                                tool_call_id=tc_id or "",
                            )
            
            if hasattr(choice, "finish_reason") and choice.finish_reason:
                yield StreamEvent(
                    type=StreamEventType.COMPLETE,
                    data=choice.finish_reason,
                )
    
    async def create_event_stream_async(
        self,
        raw_stream: AsyncIterator[Any],
    ) -> AsyncIterator[StreamEvent]:
        """创建异步事件流"""
        async for chunk in raw_stream:
            if not hasattr(chunk, "choices") or not chunk.choices:
                continue
            
            choice = chunk.choices[0]
            delta = choice.delta
            
            if hasattr(delta, "content") and delta.content:
                yield StreamEvent(
                    type=StreamEventType.CONTENT,
                    data=delta.content,
                )
            
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    tc_id = getattr(tc_delta, "id", None)
                    if tc_id:
                        func = getattr(tc_delta, "function", None)
                        name = func.name if func and hasattr(func, "name") else ""
                        yield StreamEvent(
                            type=StreamEventType.TOOL_CALL_START,
                            tool_call_id=tc_id,
                            tool_name=name,
                        )
                    
                    if hasattr(tc_delta, "function") and tc_delta.function:
                        func = tc_delta.function
                        if hasattr(func, "arguments") and func.arguments:
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_ARGS,
                                data=func.arguments,
                                tool_call_id=tc_id or "",
                            )
            
            if hasattr(choice, "finish_reason") and choice.finish_reason:
                yield StreamEvent(
                    type=StreamEventType.COMPLETE,
                    data=choice.finish_reason,
                )
