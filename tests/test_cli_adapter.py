from __future__ import annotations

import unittest

from adapters.cli import CLIAdapter
from kernel.domain.models import MessageRecord, QAResponse, ReviewCreateRequest, SessionSummary, WorkflowEvent


class _FakeFacade:
    def __init__(self) -> None:
        self.last_review_request: ReviewCreateRequest | None = None
        self.last_qa_request = None

    async def create_review_run(self, request: ReviewCreateRequest):
        self.last_review_request = request
        return {"session": {"id": "sess-1"}, "run": {"id": "run-1"}}

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
        self.last_qa_request = request
        return QAResponse(
            run_id=request.run_id,
            session_id="sess-1",
            answer="answer",
            message=MessageRecord(
                id=1,
                session_id="sess-1",
                run_id=request.run_id,
                role="assistant",
                content="answer",
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


class CLIAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_command_streams_events(self) -> None:
        adapter = CLIAdapter(_FakeFacade())
        result = await adapter.execute(
            "review",
            prompt="请审查",
            model="auto",
            project_root="Z:/repo",
            enable_static_scan=True,
            stream=True,
        )

        self.assertEqual(result["result"]["run"]["id"], "run-1")
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["events"][1].type, "review.completed")

    async def test_qa_and_sessions_commands(self) -> None:
        facade = _FakeFacade()
        adapter = CLIAdapter(facade)

        qa = await adapter.execute("qa", run_id="run-1", question="结论是什么？", model="auto")
        sessions = await adapter.execute("sessions", limit=10)

        self.assertEqual(qa.answer, "answer")
        self.assertEqual(facade.last_qa_request.run_id, "run-1")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(adapter.to_output(sessions)[0]["id"], "sess-1")


if __name__ == "__main__":
    unittest.main()
