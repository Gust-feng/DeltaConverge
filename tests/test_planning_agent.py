from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from Agent.agents.planning_agent import PlanningAgent, PlannerContractError


class _StructuredPlannerAdapter:
    def __init__(self, payload, provider_name: str = "openrouter"):
        self.payload = payload
        self.calls = []
        self.messages = []
        self.client = type("Client", (), {"model": "deepseek-reasoner"})()
        self.provider_name = provider_name

    async def complete(self, messages, **kwargs):
        self.calls.append(kwargs)
        self.messages.append(messages)
        return {
            "type": "assistant",
            "role": "assistant",
            "content": None,
            "content_json": self.payload,
            "usage": None,
        }


class _InvalidPlannerAdapter:
    def __init__(self, content: str):
        self.content = content
        self.client = type("Client", (), {"model": "deepseek-reasoner"})()
        self.provider_name = "deepseek"

    async def complete(self, messages, **kwargs):
        return {
            "type": "assistant",
            "role": "assistant",
            "content": self.content,
            "usage": None,
        }


class _SlowPlannerAdapter:
    def __init__(self):
        self.client = type("Client", (), {"model": "deepseek-reasoner"})()
        self.provider_name = "deepseek"

    async def complete(self, messages, **kwargs):
        import asyncio

        await asyncio.sleep(0.05)
        return {
            "type": "assistant",
            "role": "assistant",
            "content": '{"plan":[{"unit_id":"unit-1"}]}',
            "usage": None,
        }


class _Logger:
    def __init__(self) -> None:
        self.entries = []

    def log(self, event, payload) -> None:
        self.entries.append((event, payload))


class PlanningAgentContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_planner_normalizes_supported_extra_request_types(self) -> None:
        adapter = _StructuredPlannerAdapter(
            {
                "plan": [
                    {
                        "unit_id": "unit-1",
                        "llm_context_level": "function",
                        "extra_requests": [
                            {"type": "search_config_usage", "details": "DEBUG"},
                            {"type": "search_implementations", "details": "KernelFacade"},
                            {"type": "search_callers", "details": "run_review"},
                        ],
                        "skip_review": False,
                        "reason": "focus on runtime path",
                    }
                ]
            }
        )
        logger = _Logger()
        agent = PlanningAgent(adapter, logger=logger)

        result = await agent.run(
            {"units": [{"unit_id": "unit-1"}], "summary": {"files_changed": ["app.py"]}},
            stream=False,
        )

        self.assertEqual(len(adapter.calls), 1)
        self.assertIn("response_format", adapter.calls[0])
        extra_requests = result["plan"][0]["extra_requests"]
        self.assertEqual(
            [req["type"] for req in extra_requests],
            ["search_config_usage", "search_implementations", "callers"],
        )
        self.assertEqual(extra_requests[0]["keyword"], "DEBUG")
        self.assertEqual(extra_requests[1]["symbol"], "KernelFacade")
        self.assertEqual(extra_requests[2]["symbol"], "run_review")
        self.assertTrue(any(event == "planner_response" for event, _ in logger.entries))

    async def test_planner_skips_response_format_for_deepseek_contract(self) -> None:
        adapter = _StructuredPlannerAdapter({"plan": [{"unit_id": "unit-1"}]}, provider_name="deepseek")
        agent = PlanningAgent(adapter)

        result = await agent.run(
            {"units": [{"unit_id": "unit-1"}], "summary": {"files_changed": ["app.py"]}},
            stream=False,
        )

        self.assertEqual(result["plan"][0]["unit_id"], "unit-1")
        self.assertNotIn("response_format", adapter.calls[0])

    async def test_planner_raises_on_invalid_json_payload(self) -> None:
        agent = PlanningAgent(_InvalidPlannerAdapter("not a json payload"))

        with self.assertRaises(PlannerContractError):
            await agent.run(
                {"units": [{"unit_id": "unit-1"}], "summary": {"files_changed": ["app.py"]}},
                stream=False,
            )

    async def test_non_stream_planner_does_not_use_first_token_timeout(self) -> None:
        agent = PlanningAgent(_SlowPlannerAdapter())

        with patch("Agent.agents.planning_agent.get_planner_timeout", return_value=1.0), patch(
            "Agent.agents.planning_agent.get_planner_first_token_timeout",
            return_value=0.01,
        ), patch(
            "Agent.agents.planning_agent.get_planner_first_token_timeout_thinking",
            return_value=0.01,
        ):
            result = await agent.run(
                {"units": [{"unit_id": "unit-1"}], "summary": {"files_changed": ["app.py"]}},
                stream=False,
            )

        self.assertEqual(result["plan"][0]["unit_id"], "unit-1")

    async def test_non_stream_planner_timeout_without_logger_still_raises_contract_error(self) -> None:
        agent = PlanningAgent(_SlowPlannerAdapter())

        with patch("Agent.agents.planning_agent.get_planner_timeout", return_value=0.01), self.assertRaisesRegex(
            PlannerContractError,
            "planner timeout after",
        ):
            await agent.run(
                {"units": [{"unit_id": "unit-1"}], "summary": {"files_changed": ["app.py"]}},
                stream=False,
            )

    async def test_planner_raises_on_targetless_search_extra_request(self) -> None:
        adapter = _StructuredPlannerAdapter(
            {
                "plan": [
                    {
                        "unit_id": "unit-1",
                        "extra_requests": [{"type": "search_config_usage"}],
                    }
                ]
            }
        )
        agent = PlanningAgent(adapter)

        with self.assertRaisesRegex(PlannerContractError, "missing target"):
            await agent.run(
                {"units": [{"unit_id": "unit-1"}], "summary": {"files_changed": ["app.py"]}},
                stream=False,
            )

    async def test_planner_compacts_review_index_before_prompting(self) -> None:
        adapter = _StructuredPlannerAdapter({"plan": [{"unit_id": "unit-1"}]})
        agent = PlanningAgent(adapter)

        await agent.run(
            {
                "review_metadata": {"total_files": 3, "total_changes": 3, "mode": "staged"},
                "summary": {
                    "files_changed": ["legacy/a.py", "src/core.py", "output/x.py"],
                    "changes_by_type": {"modify": 3},
                    "total_lines": {"added": 5, "removed": 2},
                },
                "units": [
                    {
                        "unit_id": "unit-1",
                        "file_path": "src/core.py",
                        "patch_type": "modify",
                        "tags": ["security_sensitive", "clustered_changes"],
                        "metrics": {"added_lines": 5, "removed_lines": 2, "hunk_count": 1},
                        "rule_context_level": "function",
                        "rule_confidence": 0.932,
                        "line_numbers": {"new_compact": "L10-16"},
                        "rule_extra_requests": [{"type": "search_config_usage", "details": "DEBUG"}],
                    },
                    {
                        "unit_id": "unit-2",
                        "file_path": "legacy/a.py",
                        "patch_type": "modify",
                        "tags": ["only_comments"],
                        "metrics": {"added_lines": 1, "removed_lines": 0, "hunk_count": 1},
                    },
                ],
            },
            stream=False,
        )

        prompt = adapter.messages[0][-1]["content"]
        payload = json.loads(prompt.split("review_index JSON:\n", 1)[1])
        self.assertNotIn("files_changed", payload["summary"])
        self.assertIn("files_changed_sample", payload["summary"])
        self.assertIn("files_changed_omitted", payload["summary"])
        self.assertEqual(payload["review_metadata"]["optional_units_total"], 1)
        self.assertEqual(payload["review_metadata"]["rule_mandatory_units_total"], 1)
        self.assertEqual([unit["unit_id"] for unit in payload["units"]], ["unit-2"])
        self.assertEqual(
            [unit["unit_id"] for unit in payload["rule_mandatory_units_sample"]],
            ["unit-1"],
        )
        self.assertEqual(payload["rule_mandatory_units_sample"][0]["rule_confidence"], 0.93)


if __name__ == "__main__":
    unittest.main()
