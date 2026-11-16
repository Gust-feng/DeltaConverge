from __future__ import annotations

import asyncio
import unittest

from Agent.core.stream.stream_processor import StreamProcessor
from kernel.application.emitter import WorkflowEventEmitter
from kernel.application.event_bus import RunEventBus
from kernel.domain.models import WorkflowEvent


class _MemoryEventStore:
    def __init__(self) -> None:
        self.events: list[WorkflowEvent] = []

    def append_event(self, *, run_id, session_id, event_type, stage, payload):
        event = WorkflowEvent(
            id=len(self.events) + 1,
            seq=len(self.events) + 1,
            run_id=run_id,
            session_id=session_id,
            type=event_type,
            stage=stage,
            created_at="",
            payload=payload,
        )
        self.events.append(event)
        return event


class StreamResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_buffered_chunks_reach_subscriber_before_collection_finishes(self) -> None:
        bus = RunEventBus()
        queue = bus.subscribe("run-stream")
        store = _MemoryEventStore()
        emitter = WorkflowEventEmitter(
            run_id="run-stream", session_id="session-stream", store=store, event_bus=bus
        )
        received: list[WorkflowEvent] = []

        async def consume() -> None:
            while (event := await queue.get()) is not None:
                received.append(event)

        consumer = asyncio.create_task(consume())

        async def buffered_stream():
            for index in range(300):
                if index == 100:
                    self.assertGreater(len(received), 0, "buffered input starved live event delivery")
                yield {"delta": {"content": f"{index} "}}
            yield {"delta": {}, "finish_reason": "stop"}

        try:
            result = await StreamProcessor().collect(
                buffered_stream(), observer=lambda event: emitter.delta("review", **event)
            )
        finally:
            await emitter.flush()
            await bus.close("run-stream")
            await consumer

        self.assertEqual(result["content"], " ".join(str(index) for index in range(300)))
        self.assertEqual([event.seq for event in received], list(range(1, 302)))
        self.assertEqual(
            "".join(event.payload["content_delta"] for event in received).strip(), result["content"]
        )


if __name__ == "__main__":
    unittest.main()
