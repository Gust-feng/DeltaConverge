from __future__ import annotations

import unittest
from unittest.mock import patch

from kernel.application.stages.fusion_stage import FusionStage
from kernel.application.stages.review_stage import ReviewStage
from kernel.domain.context import PipelineContext
from kernel.domain.models import ReviewCreateRequest, ReviewRun


class _Emitter:
    def __init__(self) -> None:
        self.events = []

    def stage_started(self, stage: str, **payload):
        self.events.append(("stage_started", stage, payload))

    def stage_finished(self, stage: str, **payload):
        self.events.append(("stage_finished", stage, payload))

    def delta(self, stage: str, **payload):
        self.events.append(("delta", stage, payload))

    def scan_event(self, event_type: str, **payload):
        self.events.append(("scan_event", event_type, payload))

    def tool_event(self, event_type: str, stage: str, **payload):
        self.events.append(("tool_event", stage, payload))


class _FakeReviewAgent:
    def __init__(self, *args, **kwargs):
        pass

    async def run(self, *args, **kwargs):
        return "# 会话标题\n\n审查内容"


class FusionReviewStageContractTests(unittest.IsolatedAsyncioTestCase):
    def _ctx(self) -> PipelineContext:
        run = ReviewRun(
            id="run-1",
            session_id="sess-1",
            status="running",
            created_at="now",
            updated_at="now",
            prompt="p",
            model="auto",
        )
        req = ReviewCreateRequest(prompt="please review", tools=[])
        ctx = PipelineContext(
            request=req,
            run=run,
            session_id="sess-1",
            project_root=".",
            trace_id="t",
        )
        ctx.diff_ctx = type(
            "D",
            (),
            {
                "files": ["a.py"],
                "review_index": {"units": [{"unit_id": "u1"}]},
                "units": [{"unit_id": "u1"}],
            },
        )()
        return ctx

    async def test_fusion_stage_sets_typed_output(self) -> None:
        ctx = self._ctx()
        emitter = _Emitter()
        stage = FusionStage()

        with patch("Agent.agents.fusion.fuse_plan", return_value={"plan": [{"unit_id": "u1"}]}), patch(
            "Agent.agents.context_scheduler.build_context_bundle",
            return_value=[{"unit_id": "u1", "meta": {"location": "L1-1"}, "final_context_level": "function"}],
        ):
            await stage.execute(ctx, emitter)

        self.assertIsNotNone(ctx.fusion_output)
        assert ctx.fusion_output is not None
        self.assertEqual(ctx.fusion_output.context_bundle[0]["unit_id"], "u1")
        self.assertTrue(any(evt[0] == "stage_finished" and evt[1] == "fusion" for evt in emitter.events))

    async def test_review_stage_sets_typed_output(self) -> None:
        ctx = self._ctx()
        ctx.context_bundle = []
        emitter = _Emitter()
        stage = ReviewStage()

        with patch("Agent.agents.code_reviewer.CodeReviewAgent", _FakeReviewAgent):
            await stage.execute(ctx, emitter)

        self.assertIsNotNone(ctx.review_output)
        assert ctx.review_output is not None
        self.assertTrue(ctx.review_output.final_report.startswith("#"))
        self.assertTrue(any(evt[0] == "stage_started" and evt[1] == "reviewer" for evt in emitter.events))
        self.assertTrue(any(evt[0] == "stage_finished" and evt[1] == "reviewer" for evt in emitter.events))


if __name__ == "__main__":
    unittest.main()

