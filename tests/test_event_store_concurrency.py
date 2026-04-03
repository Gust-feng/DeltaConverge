"""事件存储并发写入一致性测试。

验证同一 run 并发 append 事件时 seq 不冲突、不跳号。
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.infrastructure.persistence import SQLiteKernelStore


class EventStoreConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_appends_no_conflict(self) -> None:
        """同一 run 并发写入 50 个事件，无唯一索引冲突，seq 连续。"""
        db_path = Path(tempfile.mktemp(suffix=".db"))
        store = SQLiteKernelStore(db_path)

        store.create_session(session_id="sess-1", name="test-concurrent", project_root="/tmp")
        store.create_run(run_id="run-1", session_id="sess-1", prompt="test prompt", model="auto", enable_static_scan=False, diff_mode=None, commit_from=None, commit_to=None)

        num_events = 50
        tasks = []
        for i in range(num_events):
            task = asyncio.create_task(self._append_event(store, i))
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        events = store.list_events("run-1")
        self.assertEqual(len(events), num_events)

        seqs = sorted(e.seq for e in events)
        expected = list(range(1, num_events + 1))
        self.assertEqual(seqs, expected, f"seq 不连续: 期望 {expected}, 实际 {seqs}")

        db_path.unlink(missing_ok=True)

    async def _append_event(self, store: SQLiteKernelStore, i: int):
        return store.append_event(
            run_id="run-1",
            session_id="sess-1",
            event_type="review.delta",
            stage="test",
            payload={"i": i},
        )

    async def test_sequential_appends_correct_order(self) -> None:
        """顺序写入 10 个事件，验证 seq 和 payload 对应。"""
        db_path = Path(tempfile.mktemp(suffix=".db"))
        store = SQLiteKernelStore(db_path)

        store.create_session(session_id="sess-2", name="test-sequential", project_root="/tmp")
        store.create_run(run_id="run-2", session_id="sess-2", prompt="test prompt", model="auto", enable_static_scan=False, diff_mode=None, commit_from=None, commit_to=None)

        for i in range(10):
            store.append_event(
                run_id="run-2",
                session_id="sess-2",
                event_type="review.delta",
                stage="test",
                payload={"value": i},
            )

        events = store.list_events("run-2")
        self.assertEqual(len(events), 10)

        for i, evt in enumerate(events):
            self.assertEqual(evt.seq, i + 1)
            self.assertEqual(evt.payload["value"], i)

        db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
