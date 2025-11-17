"""Code review agent built atop the modular components."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.context.provider import ContextProvider
from Agent.core.state.conversation import ConversationState
from Agent.core.tools.runtime import ToolRuntime


class CodeReviewAgent:
    """Simple loop that coordinates adapter, tools, and state."""

    def __init__(
        self,
        adapter: LLMAdapter,
        runtime: ToolRuntime,
        context_provider: ContextProvider,
        state: ConversationState | None = None,
    ) -> None:
        self.adapter = adapter
        self.runtime = runtime
        self.context_provider = context_provider
        self.state = state or ConversationState()

    async def run(
        self,
        prompt: str,
        files: Sequence[str],
        stream_observer=None,
    ) -> str:
        """Execute the agent loop until finish_reason == 'stop'."""

        if not self.state.messages:
            self.state.add_system_message(
                "You are an AI code reviewer that reasons carefully, "
                "requests tools when necessary, and follows Moonshot rules."
            )

        context = self.context_provider.load_context(list(files))
        context_block = "\n\n".join(
            f"--- {path} ---\n{snippet}" for path, snippet in context.items()
        )
        user_message = f"{prompt}\n\nContext:\n{context_block}"
        self.state.add_user_message(user_message)

        while True:
            assistant_msg = await self.adapter.complete(
                self.state.messages, observer=stream_observer
            )
            self.state.add_assistant_message(
                assistant_msg.get("content", ""),
                assistant_msg.get("tool_calls", []),
            )

            tool_calls = assistant_msg.get("tool_calls", [])
            finish_reason = assistant_msg.get("finish_reason")

            if tool_calls:
                results = await self.runtime.execute(tool_calls)
                for result in results:
                    self.state.add_tool_result(result)
                continue  # Loop back to give responses to the LLM

            if finish_reason == "stop" or not tool_calls:
                return assistant_msg.get("content", "")
