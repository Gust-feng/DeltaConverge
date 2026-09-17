from __future__ import annotations

import unittest
from unittest.mock import patch

from kernel.application.stages.planner_stage import PlannerStage
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


class _FakePlanner:
    def __init__(self, *args, **kwargs):
        self.last_usage = {"total_tokens": 10}

    async def run(self, planner_index, *, stream, observer, intent_md, user_prompt):
        return {"plan": [{"unit_id": "u1", "llm_context_level": "function"}]}


class PlannerStageContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_planner_stage_sets_typed_output_and_emits_usage(self) -> None:
        run = ReviewRun(
            id="run-1",
            session_id="sess-1",
            status="running",
            created_at="now",
            updated_at="now",
            prompt="p",
            model="auto",
        )
        req = ReviewCreateRequest(prompt="please review")
        ctx = PipelineContext(
            request=req,
            run=run,
            session_id="sess-1",
            project_root=".",
            trace_id="t",
        )
        ctx.diff_ctx = type("D", (), {"units": [], "mode": "working", "base_branch": None})()
        emitter = _Emitter()
        stage = PlannerStage()

        with patch("Agent.agents.planning_agent.PlanningAgent", _FakePlanner), patch(
            "Agent.DIFF.output_formatting.build_planner_index",
            return_value={"units": []},
        ):
            await stage.execute(ctx, emitter)

        self.assertIsNotNone(ctx.planner_output)
        assert ctx.planner_output is not None
        self.assertIn("plan", ctx.planner_output.plan)
        self.assertTrue(any(evt[0] == "delta" and evt[1] == "planner" for evt in emitter.events))


if __name__ == "__main__":
    unittest.main()

