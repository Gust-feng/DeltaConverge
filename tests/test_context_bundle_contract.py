from __future__ import annotations

import unittest
from unittest.mock import patch

from Agent.DIFF.diff_collector import DiffMode
from Agent.agents.context_scheduler import (
    ContextBundleContractError,
    build_context_bundle,
)
from Agent.core.context.diff_provider import DiffContext


def _diff_unit() -> dict:
    return {
        "unit_id": "unit-1",
        "file_path": "src/app.py",
        "language": "python",
        "tags": [],
        "symbol": "run_review",
        "hunk_range": {
            "new_start": 10,
            "new_lines": 3,
            "old_start": 8,
            "old_lines": 2,
        },
        "line_numbers": {"new_compact": "L10-12", "old_compact": "L8-9"},
        "unified_diff": "@@ -8,2 +10,3 @@",
        "unified_diff_with_lines": "@@ -8,2 +10,3 @@\n+line",
        "rule_context_level": "diff_only",
        "rule_confidence": 0.8,
        "metrics": {"added_lines": 3, "removed_lines": 1},
    }


class ContextBundleContractTests(unittest.TestCase):
    def test_context_bundle_uses_detail_based_search_requests(self) -> None:
        diff_ctx = DiffContext(
            summary="summary",
            files=["src/app.py"],
            units=[_diff_unit()],
            mode=DiffMode.STAGED,
            base_branch="main",
            review_index={},
        )
        fused_plan = {
            "plan": [
                {
                    "unit_id": "unit-1",
                    "final_context_level": "diff_only",
                    "extra_requests": [
                        {"type": "callers", "details": "run_review"},
                        {"type": "search_config_usage", "details": "APP_MODE"},
                        {"type": "search_implementations", "details": "KernelFacade"},
                    ],
                }
            ]
        }
        seen_terms: list[str] = []

        def _fake_search(term: str, max_hits: int = 5):
            seen_terms.append(term)
            return [{"file_path": "src/caller.py", "snippet": "1: invoke()"}]

        with patch("Agent.agents.context_scheduler._read_file_cached", return_value=["line"] * 20), patch(
            "Agent.agents.context_scheduler._search_callers",
            side_effect=_fake_search,
        ):
            bundle = build_context_bundle(diff_ctx, fused_plan)

        self.assertEqual(seen_terms, ["run_review", "APP_MODE", "KernelFacade"])
        self.assertEqual(bundle[0]["meta"]["location"], "src/app.py:L10-12")

    def test_context_bundle_raises_on_invalid_context_level(self) -> None:
        diff_ctx = DiffContext(
            summary="summary",
            files=["src/app.py"],
            units=[_diff_unit()],
            mode=DiffMode.STAGED,
            base_branch="main",
            review_index={},
        )

        with self.assertRaises(ContextBundleContractError):
            build_context_bundle(
                diff_ctx,
                {
                    "plan": [
                        {
                            "unit_id": "unit-1",
                            "final_context_level": "invalid-level",
                            "extra_requests": [],
                        }
                    ]
                },
            )


if __name__ == "__main__":
    unittest.main()
