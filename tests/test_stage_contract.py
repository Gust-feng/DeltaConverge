from __future__ import annotations

import unittest

from kernel.domain.context import (
    FusionStageOutput,
    IntentStageOutput,
    PlannerStageOutput,
    ReviewStageOutput,
)


class StageContractTests(unittest.TestCase):
    def test_intent_stage_output_contract(self) -> None:
        output = IntentStageOutput(
            summary="intent summary",
            project_file_tree={"src": {"main.py": None}},
            cache_hit=False,
            source="agent",
            usage={"total_tokens": 123},
        )
        self.assertEqual(output.summary, "intent summary")
        self.assertIn("src", output.project_file_tree)
        self.assertFalse(output.cache_hit)
        self.assertEqual(output.source, "agent")

    def test_planner_stage_output_contract(self) -> None:
        output = PlannerStageOutput(plan={"plan": [{"unit_id": "u1"}]}, usage={"prompt_tokens": 1})
        self.assertIn("plan", output.plan)
        self.assertEqual(output.plan["plan"][0]["unit_id"], "u1")

    def test_fusion_stage_output_contract(self) -> None:
        output = FusionStageOutput(
            fused_plan={"plan": [{"unit_id": "u1", "final_context_level": "function"}]},
            context_bundle=[{"unit_id": "u1", "context_level": "function"}],
            omitted_items=2,
            approx_chars=100,
        )
        self.assertEqual(output.omitted_items, 2)
        self.assertEqual(output.approx_chars, 100)
        self.assertEqual(output.context_bundle[0]["unit_id"], "u1")

    def test_review_stage_output_contract(self) -> None:
        output = ReviewStageOutput(final_report="# Report", session_title="Session Title")
        self.assertTrue(output.final_report.startswith("#"))
        self.assertEqual(output.session_title, "Session Title")


if __name__ == "__main__":
    unittest.main()

