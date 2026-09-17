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

from kernel.domain.context import PipelineContext, ReviewStageOutput
from kernel.domain.protocols import EventEmitter
from kernel.ports.config import ConfigPort
from kernel.ports.diff import DiffPort
from kernel.ports.engines import ReviewerEnginePort
from kernel.ports.prompt import PromptPort
from kernel.ports.tool import ToolPolicyPort

from .text_utils import truncate_prompt_text as _truncate_prompt_text


class ReviewStage:
    """最终的审查执行。"""

    def __init__(
        self,
        *,
        reviewer_engine: ReviewerEnginePort | None = None,
        diff_port: DiffPort | None = None,
        prompt_port: PromptPort | None = None,
        config_port: ConfigPort | None = None,
        tool_policy: ToolPolicyPort | None = None,
    ) -> None:
        if reviewer_engine is None:
            from kernel.infrastructure import LegacyReviewerEngine
            reviewer_engine = LegacyReviewerEngine()
        if diff_port is None:
            from kernel.infrastructure import LegacyDiffAdapter
            diff_port = LegacyDiffAdapter()
        if prompt_port is None:
            from kernel.infrastructure import LegacyPromptAdapter
            prompt_port = LegacyPromptAdapter()
        if config_port is None:
            from kernel.infrastructure import LegacyConfigAdapter
            config_port = LegacyConfigAdapter()
        if tool_policy is None:
            from kernel.infrastructure import LegacyToolPolicy
            tool_policy = LegacyToolPolicy()
        self.reviewer_engine = reviewer_engine
        self.diff_port = diff_port
        self.prompt_port = prompt_port
        self.config_port = config_port
        self.tool_policy = tool_policy

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
            ctx.review_output = ReviewStageOutput(
                final_report=ctx.final_report,
                session_title=ctx.session_title,
            )
            return

        # 限制值经 ConfigPort 获取，适配器内部已做默认值兜底
        limits = self.config_port.get_review_prompt_limits().to_dict()

        emit.stage_started("reviewer")

        # 1. 组装 Prompt
        review_index_md, _ = self.diff_port.build_review_index_context(
            ctx.diff_ctx, max_files=4, max_changes_per_file=2
        )
        review_index_md = _truncate_prompt_text(
            review_index_md, limits.get("review_index_max_chars", 18000), label="审查索引"
        ) or ""

        ctx_json = json.dumps({"context_bundle": {"items": ctx.context_bundle or []}}, ensure_ascii=False, indent=2)
        compact_intent_md = _truncate_prompt_text(
            ctx.intent_summary, limits.get("intent_max_chars", 6000), label="项目意图摘要"
        )

        augmented_prompt = self.prompt_port.build_review_user_prompt(
            review_index_md=review_index_md,
            context_bundle_json=ctx_json,
            user_prompt=request.prompt,
            intent_md=compact_intent_md,
        )

        # 2. 解析工具策略（工具运行时与对话状态由引擎适配器内部装配）
        tools_schema, auto_approve_list = self.tool_policy.resolve_review_tools(
            request.tools, auto_approve=request.auto_approve
        )

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

        # 3. 执行审查引擎（工具运行时 / 上下文提供器 / 对话状态 / 链路日志
        #    等 legacy 装配全部由适配器内部完成）
        result = await self.reviewer_engine.review(
            llm_adapter=ctx.review_adapter,
            prompt=augmented_prompt,
            files=ctx.diff_ctx.files,
            tools=tools_schema,
            auto_approve_tools=auto_approve_list,
            tool_approver=getattr(request, "tool_approver", None),
            stream_observer=_dispatch_stream,
            trace_id=ctx.trace_id,
            file_tree=ctx.project_file_tree or {},
            message_history=getattr(request, "message_history", None),
        )

        ctx.final_report = str(result.report)

        # 4. 解析会话标题
        self._parse_session_title(ctx, emit)
        ctx.review_output = ReviewStageOutput(
            final_report=ctx.final_report,
            session_title=ctx.session_title,
        )
        emit.stage_finished(
            "reviewer",
            report_chars=len(ctx.final_report),
            has_title=bool(ctx.session_title),
        )

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
