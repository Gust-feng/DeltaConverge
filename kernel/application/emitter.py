"""事件发射器实现。

WorkflowEventEmitter 将流水线事件持久化到 Store 并通过 EventBus 广播。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from kernel.domain.models import WorkflowEvent
from kernel.ports.stores import SessionStore

from .event_bus import RunEventBus

logger = logging.getLogger(__name__)


class _EventPublishQueue:
    """事件发布队列,确保事件按seq顺序发布。
    
    解决P0问题: 并发create_task导致事件乱序。
    使用单一后台任务串行发布,保证顺序性。
    """
    
    def __init__(self, event_bus: RunEventBus) -> None:
        self.event_bus = event_bus
        self._queue: asyncio.Queue[Optional[WorkflowEvent]] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        
    def start(self) -> None:
        """启动后台发布任务。"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._publish_worker())
    
    async def _publish_worker(self) -> None:
        """后台任务:串行发布事件。"""
        while True:
            event = await self._queue.get()
            if event is None:  # 停止信号
                break
            try:
                await self.event_bus.publish(event)
            except Exception:
                # 发布失败不应中断队列,记录日志但继续
                logger.warning(
                    "事件发布失败,已跳过该事件 (seq=%s, type=%s)",
                    getattr(event, "seq", None),
                    getattr(event, "type", None),
                    exc_info=True,
                )
            finally:
                self._queue.task_done()
    
    def enqueue(self, event: WorkflowEvent) -> None:
        """将事件加入发布队列。"""
        self._queue.put_nowait(event)
    
    async def stop(self) -> None:
        """停止发布队列并等待所有事件发布完成。"""
        await self._queue.join()  # 等待所有已排队事件发布完成
        self._queue.put_nowait(None)  # 发送停止信号
        if self._worker_task:
            await self._worker_task


def sanitize_payload(value: Any) -> Any:
    """递归清洗 payload 值，确保可 JSON 序列化。

    用于内核边界处（如 Legacy 桥接层）清洗外部数据。
    内核内部数据流可信，不需要经过此函数。
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): sanitize_payload(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return str(value)


class WorkflowEventEmitter:
    """将流水线事件持久化到 Store 并通过 EventBus 广播。

    每次调用 emit 方法都会：
    1. 通过 SessionStore.append_event 持久化到 SQLite
    2. 通过 RunEventBus.publish 广播给 SSE 订阅者 (串行发布,保证顺序)
    3. 记录到 raw_log 供后续保存事件日志制品
    """

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str,
        store: SessionStore,
        event_bus: RunEventBus,
    ) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.store = store
        self.event_bus = event_bus
        self.raw_log: List[Dict[str, Any]] = []
        # 使用发布队列保证事件顺序 (修复P0问题)
        self._publish_queue = _EventPublishQueue(event_bus)
        self._publish_queue.start()

    def _emit(self, event_type: str, stage: Optional[str], payload: Dict[str, Any]) -> WorkflowEvent:
        """核心发射方法。持久化 + 广播 + 记录日志。
        
        事件发布通过串行队列执行,保证按seq顺序到达订阅者。
        """
        event = self.store.append_event(
            run_id=self.run_id,
            session_id=self.session_id,
            event_type=event_type,
            stage=stage,
            payload=payload,
        )
        self.raw_log.append(asdict(event))
        # 使用发布队列确保事件按seq顺序发布 (修复P0问题: 事件发布不保序)
        self._publish_queue.enqueue(event)
        return event
    
    async def flush(self) -> None:
        """等待所有已排队的事件发布完成。
        
        在审查结束时调用,确保所有事件都已发送。
        """
        await self._publish_queue.stop()

    def stage_started(self, stage: str, **payload: Any) -> None:
        self._emit("stage.started", stage, payload)

    def stage_finished(self, stage: str, **payload: Any) -> None:
        self._emit("stage.finished", stage, payload)

    def delta(self, stage: str, **payload: Any) -> None:
        self._emit("review.delta", stage, payload)

    def scan_event(self, event_type: str, **payload: Any) -> None:
        self._emit(event_type, "scan", payload)

    def tool_event(self, event_type: str, stage: str, **payload: Any) -> None:
        self._emit(event_type, stage, payload)
