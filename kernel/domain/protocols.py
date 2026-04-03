"""内核协议定义。

Stage 和 EventEmitter 是流水线的核心抽象：
- Stage：流水线中的一个处理阶段
- EventEmitter：事件发射器，Stage 通过此接口上报事件
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import PipelineContext


class StageErrorMode(str, Enum):
    """Stage 错误处理模式。"""
    ABORT = "abort"      # 中断整个 Pipeline
    DEGRADE = "degrade"  # 降级处理，继续后续 Stage
    RETRY = "retry"      # 重试当前 Stage


class EventEmitter(Protocol):
    """事件发射器协议。

    所有方法均为同步调用（内部通过 create_task 异步广播）。
    Stage 在执行过程中随时调用以上报事件。
    """

    def stage_started(self, stage: str, **payload: Any) -> None: ...

    def stage_finished(self, stage: str, **payload: Any) -> None: ...

    def delta(self, stage: str, **payload: Any) -> None: ...

    def scan_event(self, event_type: str, **payload: Any) -> None: ...

    def tool_event(self, event_type: str, stage: str, **payload: Any) -> None: ...


class Stage(Protocol):
    """流水线阶段协议。

    每个 Stage 从 PipelineContext 中读取输入、写入输出，
    通过 EventEmitter 上报过程事件。
    """

    @property
    def name(self) -> str: ...

    @property
    def error_mode(self) -> StageErrorMode:
        """Stage 的错误处理模式。默认 ABORT。"""
        ...

    @property
    def max_retries(self) -> int:
        """最大重试次数（仅 RETRY 模式有效）。默认 0。"""
        ...

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None: ...

    async def on_error(self, ctx: PipelineContext, error: Exception, emit: EventEmitter) -> bool:
        """错误处理回调。
        
        Args:
            ctx: Pipeline 上下文
            error: 捕获的异常
            emit: 事件发射器
            
        Returns:
            bool: True 表示已处理错误可继续，False 表示需要中断
        """
        ...
