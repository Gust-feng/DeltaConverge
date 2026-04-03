from __future__ import annotations

import json
import unittest

from Agent.core.context.diff_provider import DiffContext, build_markdown_and_json_context
from Agent.core.review_kernel import (
    REVIEW_PROMPT_MAX_CONTEXT_BUNDLE_CHARS,
    REVIEW_PROMPT_MAX_CONTEXT_BUNDLE_ITEMS,
    compact_prompt_context_bundle,
)
from Agent.DIFF.diff_collector import DiffMode


class PromptBudgetingTests(unittest.TestCase):
    def test_review_index_markdown_does_not_embed_json_block(self) -> None:
        diff_ctx = DiffContext(
            summary="summary",
            files=["src/app.py"],
            units=[],
            mode=DiffMode.STAGED,
            base_branch=None,
            review_index={
                "review_metadata": {
                    "mode": "staged",
                    "base_branch": None,
                    "total_files": 1,
                    "total_changes": 1,
                },
                "summary": {
                    "total_lines": {"added": 12, "removed": 3},
                    "files_changed": ["src/app.py"],
                },
                "files": [
                    {
                        "path": "src/app.py",
                        "language": "python",
                        "change_type": "modify",
                        "metrics": {"added_lines": 12, "removed_lines": 3, "changes": 1},
                        "tags": ["security_sensitive"],
                        "changes": [
                            {
                                "unit_id": "unit-1",
                                "hunk_range": {"new_start": 10, "new_lines": 5},
                                "line_numbers": {"new_compact": "L10-14", "old_compact": "L8-11"},
                                "metrics": {"added_lines": 12, "removed_lines": 3},
                                "tags": ["security_sensitive"],
                                "agent_decision": {"context_level": "function", "priority": "high"},
                            }
                        ],
                    }
                ],
            },
        )

        markdown, compact_json = build_markdown_and_json_context(diff_ctx)

        self.assertNotIn("```json", markdown)
        self.assertNotIn("## 审查索引 JSON", markdown)
        self.assertEqual(compact_json["files"][0]["path"], "src/app.py")

    def test_context_bundle_compaction_applies_budget(self) -> None:
        bundle = []
        for index in range(30):
            bundle.append(
                {
                    "unit_id": f"unit-{index}",
                    "meta": {
                        "file_path": f"src/module_{index}.py",
                        "location": f"L{index + 1}-{index + 20}",
                        "tags": ["config_file"] if index == 0 else [],
                    },
                    "final_context_level": "file_context" if index < 5 else "function",
                    "diff": "diff\n" * 500,
                    "file_context": "context\n" * 500,
                    "callers": [{"file_path": "src/caller.py", "snippet": "call\n" * 200}],
                }
            )

        compact = compact_prompt_context_bundle(bundle)
        compact_json = json.dumps(compact, ensure_ascii=False)

        self.assertLessEqual(compact["kept_items"], REVIEW_PROMPT_MAX_CONTEXT_BUNDLE_ITEMS)
        self.assertGreater(compact["omitted_items"], 0)
        self.assertLessEqual(len(compact_json), REVIEW_PROMPT_MAX_CONTEXT_BUNDLE_CHARS + 5_000)


if __name__ == "__main__":
    unittest.main()
