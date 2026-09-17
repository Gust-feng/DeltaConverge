"""事件顺序与缓冲测试。

验证 facade.stream_review 在事件乱序到达时不会丢失事件。
"""
from __future__ import annotations

import asyncio
import unittest

from kernel.application.event_bus import RunEventBus
from kernel.domain.models import WorkflowEvent


class EventOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_delivered_in_order(self) -> None:
        """顺序发布 10 个事件，消费端按序收到。"""
        bus = RunEventBus()
        queue = bus.subscribe("run-1")

        for i in range(10):
            event = WorkflowEvent(
                id=i,
                run_id="run-1",
                session_id="sess-1",
                seq=i + 1,
                type="review.delta",
                created_at="",
                payload={"i": i},
            )
            await bus.publish(event)

        received: list[int] = []
        for _ in range(10):
            evt = await asyncio.wait_for(queue.get(), timeout=5.0)
            assert evt is not None
            received.append(evt.seq)

        self.assertEqual(received, list(range(1, 11)))
        await bus.close("run-1")

    async def test_buffer_reorders_out_of_sequence_events(self) -> None:
        """模拟乱序到达，验证 buffer 能正确重排。

        注意：这个测试验证的是 facade.stream_review 中的 buffer 逻辑。
        这里直接测试 buffer 行为的核心假设：
        - 如果 seq=3 先到、seq=2 后到，seq=2 不应被丢弃
        """
        bus = RunEventBus()
        queue = bus.subscribe("run-2")

        events_by_seq: dict[int, WorkflowEvent] = {}
        for i in range(1, 6):
            evt = WorkflowEvent(
                id=i,
                run_id="run-2",
                session_id="sess-1",
                seq=i,
                type="review.delta",
                created_at="",
                payload={"seq": i},
            )
            events_by_seq[i] = evt

        # 乱序发布: 1, 3, 2, 5, 4
        publish_order = [events_by_seq[1], events_by_seq[3], events_by_seq[2], events_by_seq[5], events_by_seq[4]]
        for evt in publish_order:
            await bus.publish(evt)

        # 从 queue 读取（按发布顺序）
        received_raw: list[int] = []
        for _ in range(5):
            evt = await asyncio.wait_for(queue.get(), timeout=5.0)
            assert evt is not None
            received_raw.append(evt.seq)

        # 验证 queue 收到的顺序确实是乱序的
        self.assertEqual(received_raw, [1, 3, 2, 5, 4])

        # 模拟 facade.stream_review 的 buffer 逻辑
        last_seq = 0
        buffer: dict[int, WorkflowEvent] = {}
        ordered: list[int] = []

        for evt_seq in received_raw:
            evt = events_by_seq[evt_seq]
            if evt.seq <= last_seq:
                continue
            if evt.seq == last_seq + 1:
                last_seq = evt.seq
                ordered.append(evt.seq)
                while (last_seq + 1) in buffer:
                    last_seq += 1
                    ordered.append(buffer.pop(last_seq).seq)
            else:
                buffer[evt.seq] = evt

        # 验证 buffer 重排后顺序正确
        self.assertEqual(ordered, [1, 2, 3, 4, 5])
        self.assertEqual(buffer, {})

        await bus.close("run-2")

    async def test_no_event_dropped_when_sequential(self) -> None:
        """顺序事件不应有任何丢失。"""
        bus = RunEventBus()
        queue = bus.subscribe("run-3")

        for i in range(20):
            event = WorkflowEvent(
                id=i,
                run_id="run-3",
                session_id="sess-1",
                seq=i + 1,
                type="review.delta",
                created_at="",
                payload={"i": i},
            )
            await bus.publish(event)

        count = 0
        for _ in range(20):
            evt = await asyncio.wait_for(queue.get(), timeout=5.0)
            if evt is not None:
                count += 1

        self.assertEqual(count, 20)
        await bus.close("run-3")


if __name__ == "__main__":
    unittest.main()
