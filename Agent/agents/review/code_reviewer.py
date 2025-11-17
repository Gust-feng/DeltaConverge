"""Code review agent built atop the modular components."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Callable

from Agent.core.adapter.llm_adapter import LLMAdapter, ToolDefinition
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
        tools: Optional[List[ToolDefinition]] = None,
        auto_approve_tools: Optional[List[str]] = None,
        tool_approver: Optional[
            Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
        ] = None,
    ) -> str:
        """Execute the agent loop until finish_reason == 'stop'."""

        if not self.state.messages:
            self.state.add_system_message(
                "You are an AI code reviewer that reasons carefully, "
                "requests tools when necessary, and follows Moonshot rules."
            )

        context = self.context_provider.load_context(list(files))
        if context:
            context_block = "\n\n".join(
                f"--- {path} ---\n{snippet}" for path, snippet in context.items()
            )
            user_message = f"{prompt}\n\nContext:\n{context_block}"
        else:
            user_message = prompt
        self.state.add_user_message(user_message)

        whitelist = set(auto_approve_tools or [])

        while True:
            assistant_msg = await self.adapter.complete(
                self.state.messages,
                tools=tools,
                observer=stream_observer,
            )

            content_text = assistant_msg.get("content", "") or ""
            tool_calls = assistant_msg.get("tool_calls") or []
            finish_reason = assistant_msg.get("finish_reason")

            if tool_calls:
                approved_calls = [
                    call for call in tool_calls if call.get("name") in whitelist
                ]
                pending_calls = [
                    call for call in tool_calls if call.get("name") not in whitelist
                ]
                if pending_calls:
                    if tool_approver:
                        user_approved = tool_approver(pending_calls)
                        approved_calls.extend(user_approved)
                    else:
                        # default: approve nothing for pending ones
                        pass

                self.state.add_assistant_message(content_text, approved_calls)

                if approved_calls:
                    results = await self.runtime.execute(approved_calls)
                    for result in results:
                        self.state.add_tool_result(result)
                    continue  # Loop back to give responses to the LLM

                if finish_reason == "stop":
                    return assistant_msg.get("content", "")
                continue

            self.state.add_assistant_message(content_text, [])
            if finish_reason == "stop":
                return assistant_msg.get("content", "")
