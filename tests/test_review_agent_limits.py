from __future__ import annotations

import unittest

from Agent.agents.code_reviewer import CodeReviewAgent, MAX_TOOL_CALL_ROUNDS
from Agent.core.tools.runtime import ToolRuntime


class _LoopingAdapter:
    def __init__(self) -> None:
        self.calls = []
        self.client = type("Client", (), {"model": "test-model"})()
        self.provider_name = "test"

    async def complete(self, messages, tools=None, observer=None, **kwargs):
        self.calls.append({"tools": tools, "messages": list(messages)})
        if len(self.calls) <= MAX_TOOL_CALL_ROUNDS:
            return {
                "type": "assistant",
                "role": "assistant",
                "content": None,
                "reasoning": "need more context",
                "tool_calls": [
                    {
                        "id": f"call-{len(self.calls)}",
                        "name": "dummy_tool",
                        "index": 0,
                        "arguments": {},
                    }
                ],
                "finish_reason": "tool_calls",
                "raw": {},
                "usage": None,
            }
        return {
            "type": "assistant",
            "role": "assistant",
            "content": "# 审查总结\n## 文件: foo.py\n### warning L1-1\n### 严重性: warning\n### 问题:\n- x\n### 建议:\n- y",
            "reasoning": None,
            "tool_calls": [],
            "finish_reason": "stop",
            "raw": {},
            "usage": None,
        }


class ReviewAgentLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_code_review_agent_forces_finalize_after_tool_round_limit(self) -> None:
        adapter = _LoopingAdapter()
        runtime = ToolRuntime()
        runtime.register("dummy_tool", lambda args: "ok")
        agent = CodeReviewAgent(adapter=adapter, runtime=runtime)

        result = await agent.run(
            prompt="开始代码审查",
            files=["foo.py"],
            tools=[{"type": "function", "function": {"name": "dummy_tool", "parameters": {"type": "object"}}}],
            auto_approve_tools=["dummy_tool"],
        )

        self.assertIn("审查总结", result)
        self.assertEqual(len(adapter.calls), MAX_TOOL_CALL_ROUNDS + 1)
        self.assertIsNone(adapter.calls[-1]["tools"])


if __name__ == "__main__":
    unittest.main()
