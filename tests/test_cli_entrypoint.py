from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from adapters.cli.__main__ import main
from kernel.domain.models import MessageRecord, QAResponse, SessionSummary, WorkflowEvent


class _FakeFacade:
    async def create_review_run(self, request):
        return {"session": {"id": "sess-1"}, "run": {"id": "run-1", "session_id": "sess-1", "status": "created"}}

    async def stream_review(self, run_id: str):
        yield WorkflowEvent(
            id=1,
            run_id=run_id,
            session_id="sess-1",
            seq=1,
            type="review.started",
            created_at="2026-04-02T00:00:00+00:00",
            payload={},
        )
        yield WorkflowEvent(
            id=2,
            run_id=run_id,
            session_id="sess-1",
            seq=2,
            type="review.completed",
            created_at="2026-04-02T00:00:01+00:00",
            payload={},
        )

    async def ask_review_qa(self, request):
        return QAResponse(
            run_id=request.run_id,
            session_id="sess-1",
            answer="done",
            message=MessageRecord(
                id=1,
                session_id="sess-1",
                run_id=request.run_id,
                role="assistant",
                content="done",
                created_at="2026-04-02T00:00:00+00:00",
                metadata={"channel": "qa"},
            ),
        )

    def list_sessions(self, **_: object):
        return [
            SessionSummary(
                id="sess-1",
                name="Session 1",
                project_root="Z:/repo",
                status="completed",
                created_at="2026-04-02T00:00:00+00:00",
                updated_at="2026-04-02T00:00:00+00:00",
            )
        ]


class CLIEntrypointTests(unittest.TestCase):
    def test_review_command_emits_event_stream_and_result(self) -> None:
        buffer = io.StringIO()
        with mock.patch("adapters.cli.__main__.get_kernel_facade", return_value=_FakeFacade()), redirect_stdout(buffer):
            exit_code = main(
                [
                    "review",
                    "--project-root",
                    "Z:/repo",
                    "--prompt",
                    "请审查当前改动",
                    "--enable-static-scan",
                ]
            )

        self.assertEqual(exit_code, 0)
        lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
        event_1 = json.loads(lines[0])
        event_2 = json.loads(lines[1])
        result = json.loads("\n".join(lines[2:]))
        self.assertEqual(event_1["kind"], "event")
        self.assertEqual(event_2["kind"], "event")
        self.assertEqual(result["kind"], "result")
        self.assertEqual(result["result"]["result"]["run"]["id"], "run-1")

    def test_sessions_command_prints_json(self) -> None:
        buffer = io.StringIO()
        with mock.patch("adapters.cli.__main__.get_kernel_facade", return_value=_FakeFacade()), redirect_stdout(buffer):
            exit_code = main(["sessions", "--limit", "5"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload[0]["id"], "sess-1")


if __name__ == "__main__":
    unittest.main()
