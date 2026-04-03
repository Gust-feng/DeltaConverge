"""审查执行 Stage。

负责：
1. 构建最终用户的 prompt（包含 intent, contextual bundle）
2. 初始化运行时环境 (Tools, ContextProvider, State)
3. 调用 CodeReviewAgent
4. 提取和处理最终结果、解析审查标题
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter
from .fusion_stage import _truncate_prompt_text


class ReviewStage:
    """最终的审查执行。"""

    @property
    def name(self) -> str:
        return "reviewer"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        request = ctx.request
        agents = set(request.agents or ["intent", "planner", "reviewer"])
        if "reviewer" not in agents:
            # 如果不执行 review，直接用之前的中间产物作为最终报告
            if "planner" in agents:
                ctx.final_report = json.dumps(ctx.plan, ensure_ascii=False, indent=2)
            elif "intent" in agents:
                ctx.final_report = ctx.intent_summary or ""
            else:
                ctx.final_report = "No agents executed."
            return

        from Agent.core.api.config import get_review_prompt_limits
        from Agent.core.context.diff_provider import build_markdown_and_json_context
        from Agent.core.services.prompt_builder import build_review_prompt
        from Agent.core.tools.runtime import ToolRuntime
        from Agent.tool.registry import get_tool_functions
        from Agent.core.services.tool_policy import resolve_tools
        from Agent.core.context.provider import ContextProvider
        from Agent.core.state.conversation import ConversationState
        from Agent.core.logging.api_logger import APILogger
        from Agent.agents.code_reviewer import CodeReviewAgent

        try:
            limits = get_review_prompt_limits()
        except Exception:
            limits = {
                "review_index_max_chars": 18000,
                "intent_max_chars": 6000,
            }

        # 1. 组装 Prompt
        review_index_md, _ = build_markdown_and_json_context(ctx.diff_ctx, max_files=4, max_changes_per_file=2)
        review_index_md = _truncate_prompt_text(
            review_index_md, limits.get("review_index_max_chars", 18000), label="审查索引"
        ) or ""

        ctx_json = json.dumps({"context_bundle": {"items": ctx.context_bundle or []}}, ensure_ascii=False, indent=2)
        compact_intent_md = _truncate_prompt_text(
            ctx.intent_summary, limits.get("intent_max_chars", 6000), label="项目意图摘要"
        )

        augmented_prompt = build_review_prompt(
            review_index_md, ctx_json, request.prompt, intent_md=compact_intent_md
        )

        # 2. 准备运行环境
        runtime = ToolRuntime()
        tool_funcs = get_tool_functions(request.tools)
        for name, func in tool_funcs.items():
            runtime.register(name, func)

        tp = resolve_tools(request.tools, request.auto_approve)
        tools_schema = tp["schemas"]
        auto_approve_list = tp["auto_approve"]

        context_provider = ContextProvider()
        state = ConversationState()
        
        if request.message_history:
            for msg in request.message_history:
                role = msg.get("role")
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls")
                if role == "user":
                    state.add_user_message(str(content))
                elif role == "assistant":
                    state.add_assistant_message(str(content), tool_calls or [])
                elif role == "system":
                    state.add_system_message(str(content))

        trace_logger = APILogger(trace_id=ctx.trace_id)

        def _dispatch_stream(evt: Dict[str, Any]) -> None:
            # 简化版：直接发送用量或普通事件
            usage = evt.get("usage")
            call_index = evt.get("call_index")
            stage_name = evt.get("usage_stage") or ("planner" if call_index == 0 else "review")
            
            if evt.get("type") == "usage_summary":
                if usage:
                    emit.delta(stage_name, type="usage_summary", usage=usage, call_index=call_index)
                return
            
            emit.delta("review", **evt)

        # 3. 执行 Agent
        agent = CodeReviewAgent(
            ctx.review_adapter,
            runtime,
            context_provider,
            state,
            trace_logger=trace_logger,
            file_tree=ctx.project_file_tree or {},
        )

        result = await agent.run(
            augmented_prompt,
            files=ctx.diff_ctx.files,
            stream_observer=_dispatch_stream,
            tools=tools_schema,  # type: ignore
            auto_approve_tools=auto_approve_list,
            tool_approver=request.tool_approver,
        )

        ctx.final_report = str(result)

        # 4. 解析会话标题
        self._parse_session_title(ctx, emit)

    def _parse_session_title(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        if not ctx.final_report:
            return

        generic_titles = {
            "代码审查报告", "审查报告", "代码审查", "code review report",
            "code review", "review report", "审查结果", "审查总结",
            "变更审查", "变更审查报告"
        }
        
        heading_pattern = r'^#{1,3}\s+(.+?)(?:\s*L\d+.*)?$'
        all_headings = re.findall(heading_pattern, ctx.final_report, re.MULTILINE)
        
        session_title = None
        for heading in all_headings:
            cleaned = re.sub(r'[#*`\[\]:：]', '', heading).strip()
            if not cleaned:
                continue
            if cleaned.lower() in {t.lower() for t in generic_titles}:
                continue
            if cleaned.startswith("文件") or cleaned.lower().startswith("file"):
                continue
            session_title = cleaned[:20]
            break
        
        if not session_title and all_headings:
            session_title = re.sub(r'[#*`\[\]:：]', '', all_headings[0]).strip()[:20]
        
        if session_title:
            ctx.session_title = session_title
            emit.delta("review", type="session_title", title=session_title, trace_id=ctx.trace_id)
