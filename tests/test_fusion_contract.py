from __future__ import annotations

import unittest

from Agent.agents.fusion import FusionContractError, fuse_plan


def _unit(
    unit_id: str,
    *,
    file_path: str,
    rule_confidence: float,
    tags: list[str] | None = None,
    rule_notes: str = "",
) -> dict:
    return {
        "unit_id": unit_id,
        "file_path": file_path,
        "rule_context_level": "function",
        "rule_confidence": rule_confidence,
        "rule_notes": rule_notes,
        "rule_extra_requests": [],
        "tags": tags or [],
        "metrics": {"added_lines": 8, "removed_lines": 2, "hunk_count": 1},
    }


class FusionContractTests(unittest.TestCase):
    def test_fusion_keeps_rule_mandatory_high_risk_unit_when_planner_omits_it(self) -> None:
        review_index = {
            "units": [
                _unit(
                    "high-1",
                    file_path="Agent/core/review_kernel.py",
                    rule_confidence=0.92,
                    tags=["security_sensitive"],
                ),
                _unit(
                    "low-1",
                    file_path="frontend/react/src/App.tsx",
                    rule_confidence=0.2,
                ),
            ]
        }

        result = fuse_plan(
            review_index,
            {
                "plan": [
                    {
                        "unit_id": "low-1",
                        "llm_context_level": "diff_only",
                        "skip_review": False,
                    }
                ]
            },
        )
        by_id = {item["unit_id"]: item for item in result["plan"]}

        self.assertFalse(by_id["high-1"]["skip_review"])
        self.assertEqual(by_id["high-1"]["final_context_level"], "function")
        self.assertEqual(by_id["high-1"]["reason"], "mandatory_by_rule")

    def test_fusion_keeps_rule_mandatory_high_risk_unit_when_planner_tries_to_skip(self) -> None:
        review_index = {
            "units": [
                _unit(
                    "high-1",
                    file_path="Agent/core/review_kernel.py",
                    rule_confidence=0.92,
                    tags=["security_sensitive"],
                ),
            ]
        }

        result = fuse_plan(
            review_index,
            {
                "plan": [
                    {
                        "unit_id": "high-1",
                        "llm_context_level": "diff_only",
                        "skip_review": True,
                    }
                ]
            },
        )
        by_id = {item["unit_id"]: item for item in result["plan"]}

        self.assertFalse(by_id["high-1"]["skip_review"])
        self.assertEqual(by_id["high-1"]["reason"], "mandatory_by_rule")

    def test_fusion_derives_config_search_target_from_file_name(self) -> None:
        review_index = {
            "units": [
                {
                    **_unit(
                        "cfg-1",
                        file_path="frontend/react/tsconfig.json",
                        rule_confidence=0.82,
                        tags=["config_file"],
                    ),
                    "rule_extra_requests": [{"type": "search_config_usage"}],
                }
            ]
        }

        result = fuse_plan(review_index, {"plan": []})
        item = result["plan"][0]

        self.assertEqual(item["reason"], "mandatory_by_rule")
        self.assertEqual(item["extra_requests"][0]["type"], "search_config_usage")
        self.assertEqual(item["extra_requests"][0]["keyword"], "tsconfig")

    def test_fusion_raises_on_targetless_non_derivable_rule_request(self) -> None:
        review_index = {
            "units": [
                {
                    **_unit(
                        "bad-1",
                        file_path="src/app.py",
                        rule_confidence=0.2,
                    ),
                    "rule_extra_requests": [{"type": "search"}],
                }
            ]
        }

        with self.assertRaisesRegex(FusionContractError, "rule extra_request missing target"):
            fuse_plan(review_index, {"plan": []})

    def test_fusion_does_not_supplement_medium_risk_units(self) -> None:
        review_index = {
            "units": [
                _unit(
                    "medium-1",
                    file_path="Agent/core/context/provider.py",
                    rule_confidence=0.72,
                    tags=["complete_function"],
                ),
                _unit(
                    "low-1",
                    file_path="frontend/react/src/App.tsx",
                    rule_confidence=0.2,
                ),
            ]
        }

        result = fuse_plan(
            review_index,
            {
                "plan": [
                    {
                        "unit_id": "low-1",
                        "llm_context_level": "diff_only",
                        "skip_review": False,
                    }
                ]
            },
        )
        by_id = {item["unit_id"]: item for item in result["plan"]}

        self.assertFalse(by_id["low-1"]["skip_review"])
        self.assertTrue(by_id["medium-1"]["skip_review"])
        self.assertEqual(by_id["medium-1"]["reason"], "not_selected_by_planner")


if __name__ == "__main__":
    unittest.main()
