"""Code review agent built atop the modular components."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Callable, cast

from Agent.core.adapter.llm_adapter import LLMAdapter, ToolDefinition
from Agent.core.context.provider import ContextProvider
from Agent.core.logging.api_logger import APILogger
from Agent.core.state.conversation import ConversationState
from Agent.core.tools.runtime import ToolRuntime
from Agent.core.stream.stream_processor import NormalizedToolCall, NormalizedMessage


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
            Callable[[List[NormalizedToolCall]], List[NormalizedToolCall]]
        ] = None,
    ) -> str:
        """Execute the agent loop until finish_reason == 'stop'."""

        if not self.state.messages:
            self.state.add_system_message(
                "你是一名严谨的 AI 代码审查员，任务是基于给定的 PR diff 上下文，重点发现以下四类问题：\n"
                "1）静态缺陷：语法错误、明显的类型不匹配、依赖缺失/导入错误、明显错误的 API 使用等；\n"
                "2）逻辑缺陷：条件判断错误、边界条件遗漏、状态不一致、错误返回值、异常路径遗漏等；\n"
                "3）内存/资源问题：潜在的资源泄漏（文件/连接未关闭）、循环中累积的大对象、无限增长的缓存/集合等；\n"
                "4）安全漏洞：鉴权/权限缺失、未校验的外部输入、硬编码敏感信息、危险函数调用（如 eval/exec/拼接 SQL）、不安全依赖等。\n\n"
                "请遵循以下原则：\n"
                "- 优先审查安全问题和静态缺陷，其次是逻辑和内存/资源问题，最后才是风格和可读性建议；\n"
                "- 先整体理解本次变更的目的，再结合 diff 逐块审查，不要只看单行；\n"
                "- 必要时调用工具（如 read_file_hunk / list_project_files / search_in_project / get_dependencies）"
                "补充函数上下文、调用链或依赖信息：如果需要多个工具，请在同一轮一次性列出所有 tool_calls，"
                "等待全部工具结果返回后再继续推理，避免拆成多轮；\n"
                "- 审查意见应具体、可执行，指出问题所在的文件/行或函数，并给出改进建议；\n"
                "- 如果上下文不足以做出判断，请明确说明“不足以判断”，而不是臆测。"
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

        # 为避免重复贴整文件内容，这里不再追加 ContextProvider 的全文片段。
        # 如需更多上下文，请通过工具（read_file_hunk 等）按需读取。
        self.state.add_user_message(prompt)

        whitelist = set(auto_approve_tools or [])

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
                    },
                )

            # 为流式回调补充 call_index，便于前端统计每次调用的 token
            def wrapped_observer(event: Dict[str, Any]) -> None:
                if stream_observer:
                    event_with_idx = dict(event)
                    event_with_idx["call_index"] = call_idx
                    stream_observer(event_with_idx)

            assistant_msg = await self.adapter.complete(
                self.state.messages,
                tools=tools,
                observer=wrapped_observer if stream_observer else None,
            )

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
                    },
                )

            content_text = assistant_msg.get("content", "") or ""
            tool_calls = assistant_msg.get("tool_calls") or []
            finish_reason = assistant_msg.get("finish_reason")

            # 部分模型可能将 tool_call 作为纯文本 JSON 返回，这里做兜底解析
            if not tool_calls and content_text:
                parsed_calls = self._extract_tool_calls_from_text(
                    content_text, tools
                )
                if parsed_calls:
                    tool_calls = parsed_calls
                    content_text = ""

            if tool_calls:
                normalized_calls = cast(List[NormalizedToolCall], tool_calls)
                approved_calls: List[NormalizedToolCall] = [
                    call for call in normalized_calls if call.get("name") in whitelist
                ]
                pending_calls: List[NormalizedToolCall] = [
                    call for call in normalized_calls if call.get("name") not in whitelist
                ]
                if pending_calls:
                    if tool_approver:
                        user_approved = tool_approver(pending_calls)
                        approved_calls.extend(user_approved)
                    else:
                        # default: approve nothing for pending ones
                        pass

                self.state.add_assistant_message(
                    content_text, cast(List[Dict[str, Any]], approved_calls)
                )

                if approved_calls:
                    results = await self.runtime.execute(
                        cast(List[Dict[str, Any]], approved_calls)
                    )

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

                    # 将工具结果推送给流式观察者，便于前端展示
                    if stream_observer:
                        for call, result in zip(approved_calls, results):
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
                                "final_content": str(assistant_msg.get("content", "")),
                            },
                        )
                    return str(assistant_msg.get("content", ""))
                continue

            self.state.add_assistant_message(content_text, [])
            if finish_reason == "stop":
                if self._trace_logger and self._trace_path is not None:
                    self._trace_logger.append(
                        self._trace_path,
                        "SESSION_END",
                        {
                            "call_index": self._call_index,
                            "final_content": str(assistant_msg.get("content", "")),
                        },
                    )
                return str(assistant_msg.get("content", ""))

    @staticmethod
    def _extract_usage(assistant_msg: NormalizedMessage) -> Optional[Dict[str, Any]]:
        """Extract usage info from normalized message or raw chunks."""

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

    @staticmethod
    def _extract_tool_calls_from_text(
        content_text: str, tools: Optional[List[ToolDefinition]]
    ) -> List[NormalizedToolCall]:
        """Heuristically parse tool calls when model returns JSON text instead of tool_calls."""

        try:
            parsed = json.loads(content_text)
        except Exception:
            return []

        if isinstance(parsed, dict):
            candidates = [parsed]
        elif isinstance(parsed, list):
            candidates = parsed
        else:
            return []

        allowed_names = {
            t["function"]["name"]
            for t in (tools or [])
            if isinstance(t, dict) and isinstance(t.get("function"), dict)
        }

        tool_calls: List[NormalizedToolCall] = []
        for idx, obj in enumerate(candidates):
            if not isinstance(obj, dict):
                continue
            name = (
                obj.get("name")
                or obj.get("tool")
                or (
                    obj.get("function", {}).get("name")
                    if isinstance(obj.get("function"), dict)
                    else None
                )
            )
            if not name:
                continue
            if allowed_names and name not in allowed_names:
                continue

            raw_args = (
                obj.get("arguments")
                or (
                    obj.get("function", {}).get("arguments")
                    if isinstance(obj.get("function"), dict)
                    else {}
                )
                or {}
            )
            arguments: Dict[str, Any]
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except Exception:
                    arguments = {"_raw": raw_args}
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                arguments = {}

            tool_calls.append(
                {
                    "id": obj.get("id") or f"{name}:{idx}",
                    "name": name,
                    "index": obj.get("index", idx),
                    "arguments": arguments,
                }
            )

        return tool_calls
