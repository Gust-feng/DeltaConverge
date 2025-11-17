"""Code review agent built atop the modular components."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

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
                self.state.messages,
                tools=tools,
                observer=stream_observer,
            )

            content_text = assistant_msg.get("content", "") or ""
            tool_calls = assistant_msg.get("tool_calls") or []
            finish_reason = assistant_msg.get("finish_reason")

            # NOTE: 临时测试逻辑（后续需要移除）------------------------------------
            # 某些模型在工具集刚接入时，可能还不会立刻产出规范的 tool_calls，
            # 而是仅在自然语言中表达“需要调用某个工具”。为了验证整体链路，
            # 这里在没有结构化 tool_calls 的情况下，根据文本提示合成一次
            # 简单的工具调用请求，并走完整的执行 + 再次调用 LLM 的流程。
            if not tool_calls and tools:
                lowered = content_text.lower()
                if ("调用工具" in content_text) or ("use tool" in lowered):
                    synthetic_calls: List[Dict[str, Any]] = []
                    for index, tool_def in enumerate(tools):
                        fn = tool_def.get("function", {})
                        name = fn.get("name")
                        if not name:
                            continue
                        params = fn.get("parameters", {})
                        props = params.get("properties", {})
                        args: Dict[str, Any] = {}
                        for key, prop in props.items():
                            t = prop.get("type")
                            if t == "string":
                                args[key] = content_text[:2000]
                            elif t in ("number", "integer"):
                                args[key] = 0
                            elif t == "boolean":
                                args[key] = False
                            else:
                                args[key] = None
                        synthetic_calls.append(
                            {
                                "id": f"{name}:{index}",
                                "name": name,
                                "arguments": args,
                            }
                        )
                    if synthetic_calls:
                        tool_calls = synthetic_calls
            # ----------------------------------------------------------------

            self.state.add_assistant_message(content_text, tool_calls)

            if tool_calls:
                results = await self.runtime.execute(tool_calls)
                for result in results:
                    self.state.add_tool_result(result)
                continue  # Loop back to give responses to the LLM

            if finish_reason == "stop" or not tool_calls:
                return assistant_msg.get("content", "")
