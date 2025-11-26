"""基于模块化组件构建的代码审查 Agent。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Callable, cast
import asyncio
import os

from Agent.core.adapter.llm_adapter import LLMAdapter, ToolDefinition
from Agent.core.context.provider import ContextProvider
from Agent.core.logging.api_logger import APILogger
from Agent.core.state.conversation import ConversationState
from Agent.core.tools.runtime import ToolRuntime
from Agent.core.stream.stream_processor import NormalizedToolCall, NormalizedMessage
from Agent.agents.prompts import SYSTEM_PROMPT_REVIEWER


class CodeReviewAgent:
    """协调适配器、工具与状态的简易循环。"""

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
        self.trace_id = getattr(trace_logger, "trace_id", None)

    async def run(
        self,
        prompt: str,
        files: Sequence[str],
        stream_observer=None,
        tools: Optional[List[ToolDefinition]] = None,
        auto_approve_tools: Optional[List[str]] = None,
        tool_approver: Optional[
            Callable[[List[NormalizedToolCall]], List[NormalizedToolCall]]
        ] = None,
    ) -> str:
        """执行 Agent 循环，直到 finish_reason == 'stop'。"""

        if not self.state.messages:
            self.state.add_system_message(SYSTEM_PROMPT_REVIEWER)

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
                "trace_id": self.trace_id,
            }
            self._trace_path = self._trace_logger.start(
                "agent_session", session_meta
            )

        # 为避免重复贴整文件内容，这里不再追加 ContextProvider 的全文片段。
        # 如需更多上下文，请通过工具（read_file_hunk 等）按需读取。
        self.state.add_user_message(prompt)

        whitelist = set(auto_approve_tools or [])
        call_timeout = float(os.getenv("LLM_CALL_TIMEOUT", "120") or 120)

        while True:
            # 每轮 LLM 调用的序号（用于日志与流式回调）
            self._call_index += 1
            call_idx = self._call_index

            # 日志：记录每次对 LLM 的请求（包含当前 messages 和工具定义）
            if self._trace_logger and self._trace_path is not None:
                self._trace_logger.append(
                    self._trace_path,
                    f"LLM_CALL_{call_idx}_REQUEST",
                    {
                        "call_index": call_idx,
                        "model": getattr(
                            getattr(self.adapter, "client", None), "model", None
                        ),
                        "messages": self.state.messages,
                        "tools": tools,
                        "trace_id": self.trace_id,
                    },
                )

            # 为流式回调补充 call_index，便于前端统计每次调用的 tokens
            def wrapped_observer(event: Dict[str, Any]) -> None:
                if stream_observer:
                    event_with_idx = dict(event)
                    event_with_idx["call_index"] = call_idx
                    stream_observer(event_with_idx)

            try:
                assistant_msg = await asyncio.wait_for(
                    self.adapter.complete(
                        self.state.messages,
                        tools=tools,
                        observer=wrapped_observer if stream_observer else None,
                    ),
                    timeout=call_timeout,
                )
            except asyncio.TimeoutError:
                timeout_msg = (
                    f"LLM call timeout after {call_timeout}s "
                    f"(call_index={call_idx})"
                )
                if self._trace_logger and self._trace_path is not None:
                    self._trace_logger.append(
                        self._trace_path,
                        f"LLM_CALL_{call_idx}_TIMEOUT",
                        {"message": timeout_msg, "trace_id": self.trace_id},
                    )
                raise RuntimeError(timeout_msg)

            usage = self._extract_usage(assistant_msg)

            # 即便流式未上报 usage，也在最终返回后补一条用量事件
            if stream_observer and usage:
                stream_observer(
                    {
                        "type": "usage_summary",
                        "call_index": call_idx,
                        "usage": usage,
                    }
                )

            if self._trace_logger and self._trace_path is not None:
                self._trace_logger.append(
                    self._trace_path,
                    f"LLM_CALL_{call_idx}_RESPONSE",
                    {
                        "call_index": call_idx,
                        "assistant_message": assistant_msg,
                        "trace_id": self.trace_id,
                    },
                )

            content_text = assistant_msg.get("content", "") or ""
            tool_calls = assistant_msg.get("tool_calls") or []
            finish_reason = assistant_msg.get("finish_reason")

            if tool_calls:
                normalized_calls = cast(List[NormalizedToolCall], tool_calls)

                def _call_key(call: NormalizedToolCall) -> tuple[Any, Any, Any]:
                    return (call.get("id"), call.get("name"), call.get("index"))

                # 白名单内的工具自动执行，其余工具走审批或拒绝
                approved_calls: List[NormalizedToolCall] = [
                    call for call in normalized_calls if call.get("name") in whitelist
                ]
                pending_calls: List[NormalizedToolCall] = [
                    call for call in normalized_calls if call.get("name") not in whitelist
                ]
                denied_calls: List[NormalizedToolCall] = []

                if pending_calls:
                    if tool_approver:
                        user_approved = tool_approver(pending_calls) or []
                        approved_calls.extend(user_approved)
                        approved_keys = {_call_key(c) for c in user_approved}
                        denied_calls = [
                            call for call in pending_calls if _call_key(call) not in approved_keys
                        ]
                    else:
                        # 没有审批器且未开启 auto_approve，直接拒绝并返回错误结果
                        denied_calls = pending_calls

                # 将原始的 tool_calls（包括被拒绝的）都写入会话，保持调用链一致
                self.state.add_assistant_message(
                    content_text, cast(List[Dict[str, Any]], normalized_calls)
                )

                # 执行已批准的工具
                results: List[Dict[str, Any]] = []
                if approved_calls:
                    results = await self.runtime.execute(
                        cast(List[Dict[str, Any]], approved_calls)
                    )

                # 为被拒绝的调用生成错误结果，避免模型陷入重复请求
                error_results: List[Dict[str, Any]] = []
                if denied_calls:
                    err_msg = (
                        "工具调用被拒绝：未开启自动工具执行，且未配置工具审批回调 "
                        "(auto_approve_tools/tool_approver)。"
                    )
                    for call in denied_calls:
                        error_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id", "unknown_call"),
                                "name": call.get("name"),
                                "content": "",
                                "error": err_msg,
                            }
                        )

                # 记录日志（包含成功与拒绝的结果）
                if self._trace_logger and self._trace_path is not None and (results or error_results):
                    safe_results: List[Dict[str, Any]] = []
                    for r in [*results, *error_results]:
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
                            "denied_calls": denied_calls,
                            "results": safe_results,
                            "trace_id": self.trace_id,
                        },
                    )

                # 推送给流式观察者，前端可以看到“拒绝”结果
                if stream_observer:
                    for call, result in list(zip(approved_calls, results)) + list(
                        zip(denied_calls, error_results)
                    ):
                        stream_observer(
                            {
                                "type": "tool_result",
                                "call_index": call_idx,
                                "tool_name": call.get("name"),
                                "arguments": call.get("arguments"),
                                "content": result.get("content"),
                                "error": result.get("error"),
                            }
                        )

                for result in [*results, *error_results]:
                    self.state.add_tool_result(result)

                # 将工具结果交还给 LLM，让其基于错误或成功结果继续对话
                continue  # 回到循环让 LLM 根据工具结果继续回复

            self.state.add_assistant_message(content_text, [])
            if finish_reason == "stop":
                if self._trace_logger and self._trace_path is not None:
                    self._trace_logger.append(
                        self._trace_path,
                        "SESSION_END",
                        {
                            "call_index": self._call_index,
                            "final_content": str(assistant_msg.get("content", "")),
                            "trace_id": self.trace_id,
                        },
                    )
                return str(assistant_msg.get("content", ""))

    @staticmethod
    def _extract_usage(assistant_msg: NormalizedMessage) -> Optional[Dict[str, Any]]:
        """从标准化消息或原始片段中提取用量信息。"""

        usage = assistant_msg.get("usage")
        if usage:
            return usage

        raw_chunks = None
        raw_field = assistant_msg.get("raw")
        if isinstance(raw_field, dict):
            raw_chunks = raw_field.get("chunks")
        if isinstance(raw_chunks, list):
            for chunk in reversed(raw_chunks):
                if isinstance(chunk, dict):
                    maybe_usage = chunk.get("usage")
                    if maybe_usage:
                        assistant_msg["usage"] = maybe_usage
                        return maybe_usage
        return None
        # 版本优化，删除部分冗杂代码片段

__all__ = ["CodeReviewAgent"]
