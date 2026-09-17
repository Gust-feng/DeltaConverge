from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional

from kernel.domain.models import WorkflowEvent


class RunEventBus:
    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, List[asyncio.Queue[Optional[WorkflowEvent]]]] = defaultdict(list)
        self._closed: Dict[str, bool] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue[Optional[WorkflowEvent]]:
        queue: asyncio.Queue[Optional[WorkflowEvent]] = asyncio.Queue()
        if self._closed.get(run_id):
            queue.put_nowait(None)
        else:
            self._subscribers[run_id].append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[Optional[WorkflowEvent]]) -> None:
        subscribers = self._subscribers.get(run_id)
        if not subscribers:
            return
        self._subscribers[run_id] = [item for item in subscribers if item is not queue]
        if not self._subscribers[run_id]:
            self._subscribers.pop(run_id, None)

    async def publish(self, event: WorkflowEvent) -> None:
        for queue in list(self._subscribers.get(event.run_id, [])):
            await queue.put(event)

    async def close(self, run_id: str) -> None:
        self._closed[run_id] = True
        subscribers = self._subscribers.pop(run_id, [])
        for queue in subscribers:
            await queue.put(None)

    def is_closed(self, run_id: str) -> bool:
        return bool(self._closed.get(run_id))
