from __future__ import annotations

import unittest

from Agent.core.api.api import resolve_planner_preference


class PlannerPreferencePolicyTests(unittest.TestCase):
    def test_explicit_planner_preference_is_preserved(self) -> None:
        self.assertEqual(
            resolve_planner_preference("deepseek-reasoner", "glm:glm-4.6"),
            "glm:glm-4.6",
        )

    def test_reasoner_review_defaults_to_chat_planner(self) -> None:
        self.assertEqual(
            resolve_planner_preference("deepseek-reasoner", None),
            "deepseek-chat",
        )

    def test_provider_model_syntax_keeps_provider_when_overridden(self) -> None:
        self.assertEqual(
            resolve_planner_preference("deepseek:deepseek-reasoner", None),
            "deepseek:deepseek-chat",
        )

    def test_non_reasoner_review_keeps_same_preference(self) -> None:
        self.assertEqual(
            resolve_planner_preference("glm:glm-4.6", None),
            "glm:glm-4.6",
        )


if __name__ == "__main__":
    unittest.main()
