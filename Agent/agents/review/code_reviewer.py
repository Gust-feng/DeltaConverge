"""Code review agent built atop the modular components."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Callable

from Agent.core.adapter.llm_adapter import LLMAdapter, ToolDefinition
from Agent.core.context.provider import ContextProvider
from Agent.core.logging.api_logger import APILogger
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
        trace_logger: APILogger | None = None,
    ) -> None:
        self.adapter = adapter
        self.runtime = runtime
        self.context_provider = context_provider
        self.state = state or ConversationState()
        self._trace_logger = trace_logger
        self._trace_path = None
        self._call_index = 0

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
                "你是一名严谨的 AI 代码审查员，任务是基于给定的 PR diff 上下文，优先发现真实问题，"
                "而不是泛泛而谈。\n\n"
                "请遵循以下原则：\n"
                "1）先整体理解本次变更的目的，再进入细节；\n"
                "2）重点关注高风险变更（安全敏感、配置/依赖调整、复杂逻辑和结构性修改），"
                "对纯注释/导入/日志等噪音级变更可以简要带过；\n"
                "3）必要时调用工具（如 read_file_hunk / list_project_files / search_in_project），"
                "补充函数上下文、调用链或依赖信息，但避免无意义的过度调用；\n"
                "4）审查意见应具体、可执行，指出问题所在行/函数，并给出改进建议；\n"
                "5）如果上下文不足以做出判断，请明确说明“不足以判断”，而不是臆测。"
            )

        # 会话级别日志：记录一次审查的起点（包含文件列表和可用工具）
        if self._trace_logger and self._trace_path is None:
            try:
                tool_names = (
                    [t["function"]["name"] for t in tools] if tools else []
                )
            except Exception:
                tool_names = []
            session_meta: Dict[str, Any] = {
                "provider": getattr(self.adapter, "provider_name", "unknown"),
                "files": list(files),
                "tools_exposed": tool_names,
            }
            self._trace_path = self._trace_logger.start(
                "agent_session", session_meta
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
            # 日志：记录每次对 LLM 的请求（包含当前 messages 和工具定义）
            if self._trace_logger and self._trace_path is not None:
                self._call_index += 1
                self._trace_logger.append(
                    self._trace_path,
                    f"LLM_CALL_{self._call_index}_REQUEST",
                    {
                        "call_index": self._call_index,
                        "model": getattr(
                            getattr(self.adapter, "client", None), "model", None
                        ),
                        "messages": self.state.messages,
                        "tools": tools,
                    },
                )

            assistant_msg = await self.adapter.complete(
                self.state.messages,
                tools=tools,
                observer=stream_observer,
            )

            if self._trace_logger and self._trace_path is not None:
                self._trace_logger.append(
                    self._trace_path,
                    f"LLM_CALL_{self._call_index}_RESPONSE",
                    {
                        "call_index": self._call_index,
                        "assistant_message": assistant_msg,
                    },
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

                    if self._trace_logger and self._trace_path is not None:
                        # 为了日志可读性，对工具输出内容做轻度截断
                        safe_results: List[Dict[str, Any]] = []
                        for r in results:
                            r_copy = dict(r)
                            content = r_copy.get("content")
                            if isinstance(content, str) and len(content) > 1000:
                                r_copy["content"] = content[:1000] + "...(truncated)"
                        safe_results.append(r_copy)
                        self._trace_logger.append(
                            self._trace_path,
                            f"TOOLS_EXECUTION_{self._call_index}",
                            {
                                "call_index": self._call_index,
                                "approved_calls": approved_calls,
                                "results": safe_results,
                            },
                        )

                    for result in results:
                        self.state.add_tool_result(result)
                    continue  # Loop back to give responses to the LLM

                if finish_reason == "stop":
                    if self._trace_logger and self._trace_path is not None:
                        self._trace_logger.append(
                            self._trace_path,
                            "SESSION_END",
                            {
                                "call_index": self._call_index,
                                "final_content": assistant_msg.get("content", ""),
                            },
                        )
                    return assistant_msg.get("content", "")
                continue

            self.state.add_assistant_message(content_text, [])
            if finish_reason == "stop":
                if self._trace_logger and self._trace_path is not None:
                    self._trace_logger.append(
                        self._trace_path,
                        "SESSION_END",
                        {
                            "call_index": self._call_index,
                            "final_content": assistant_msg.get("content", ""),
                        },
                    )
                return assistant_msg.get("content", "")
