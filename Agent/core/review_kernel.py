"""核心审查内核：封装从 Diff 解析到最终审查的业务流转。"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, cast, Tuple

from Agent.agents.code_reviewer import CodeReviewAgent
from Agent.agents.planning_agent import PlanningAgent
from Agent.agents.fusion import fuse_plan
from Agent.agents.context_scheduler import build_context_bundle
from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import (
    collect_diff_context,
    build_markdown_and_json_context,
    DiffContext,
)
from Agent.DIFF.output_formatting import build_planner_index
from Agent.core.logging import get_logger
from Agent.core.logging.api_logger import APILogger
from Agent.core.logging.pipeline_logger import PipelineLogger
from Agent.core.logging.fallback_tracker import fallback_tracker
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import NormalizedToolCall
from Agent.core.tools.runtime import ToolRuntime
from Agent.tool.registry import get_tool_functions
from Agent.core.services.prompt_builder import build_review_prompt
from Agent.core.services.tool_policy import resolve_tools
from Agent.core.services.usage_service import UsageService
from Agent.core.services.pipeline_events import PipelineEvents

logger = get_logger(__name__)


class UsageAggregator:
    def __init__(self) -> None:
        self._svc = UsageService()
    def reset(self) -> None:
        self._svc.reset()
    def update(self, usage: Dict[str, Any], call_index: int | None) -> Tuple[Dict[str, int], Dict[str, int]]:
        return self._svc.update(usage, call_index)
    def session_totals(self) -> Dict[str, int]:
        return self._svc.session_totals()


class ReviewKernel:
    """核心审查引擎，负责编排各 Agent 与 Context 模块。"""

    def __init__(
        self,
        review_adapter: LLMAdapter,
        planner_adapter: LLMAdapter,
        review_provider: str,
        planner_provider: str,
        trace_id: str,
    ) -> None:
        self.review_adapter = review_adapter
        self.planner_adapter = planner_adapter
        self.review_provider = review_provider
        self.planner_provider = planner_provider
        self.trace_id = trace_id
        
        self.usage_agg = UsageAggregator()
        self.pipe_logger = PipelineLogger(trace_id=trace_id)
        self.session_log = None

    def _summarize_context_bundle(self, bundle: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成上下文包的体积/截断概览。"""
        if not bundle:
            return {"items": 0, "total_chars": 0, "truncated_fields": 0, "by_level": {}}

        text_fields = ("diff", "function_context", "file_context", "full_file", "previous_version")
        total_chars = 0
        truncated_fields = 0
        level_count: Dict[str, int] = {}

        for item in bundle:
            level = str(item.get("final_context_level") or "unknown")
            level_count[level] = level_count.get(level, 0) + 1
            for field in text_fields:
                val = item.get(field)
                if isinstance(val, str):
                    total_chars += len(val)
                    if "TRUNCATED" in val:
                        truncated_fields += 1
            callers = item.get("callers") or []
            for c in callers:
                snippet = c.get("snippet")
                if isinstance(snippet, str):
                    total_chars += len(snippet)
                    if "TRUNCATED" in snippet:
                        truncated_fields += 1

        avg_chars = total_chars // max(len(bundle), 1)
        return {
            "items": len(bundle),
            "total_chars": total_chars,
            "avg_chars": avg_chars,
            "truncated_fields": truncated_fields,
            "by_level": level_count,
        }

    def _notify(self, callback: Optional[Callable], evt: Dict[str, Any]) -> None:
        if callback:
            try:
                callback(evt)
            except Exception:
                pass

    async def run(
        self,
        prompt: str,
        tool_names: List[str],
        auto_approve: bool,
        diff_ctx: DiffContext,
        stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        tool_approver: Optional[Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]] = None,
    ) -> str:
        """运行审查流程核心逻辑。"""
        
        fallback_tracker.reset()
        
        self.session_log = self.pipe_logger.start(
            "planning_review_service_async",
            {
                "review_provider": self.review_provider,
                "planner_provider": self.planner_provider,
                "trace_id": self.trace_id,
            },
        )
        
        self.pipe_logger.log(
            "diff_summary",
            {
                "mode": diff_ctx.mode.value,
                "files": len(diff_ctx.files),
                "units": len(diff_ctx.units),
                "review_index_units": len(diff_ctx.review_index.get("units", [])),
                "review_index_preview": diff_ctx.review_index.get("units", [])[:3],
                "trace_id": self.trace_id,
            },
        )

        events = PipelineEvents(stream_callback)
        events.stage_end("diff_parse", files=len(diff_ctx.files), units=len(diff_ctx.units))
        events.stage_end("review_units")
        events.stage_end("rule_layer")
        events.stage_end("review_index")

        # Planning Phase
        events.stage_start("planner")
        
        planner_state = ConversationState()
        planner = PlanningAgent(self.planner_adapter, planner_state, logger=self.pipe_logger)

        def _planner_observer(evt: Dict[str, Any]) -> None:
            if not stream_callback:
                return
            try:
                reasoning = evt.get("reasoning_delta") or ""
                content = evt.get("content_delta") or ""
                payload = reasoning or content
                if payload:
                    stream_callback(
                        {
                            "type": "planner_delta",
                            "content_delta": payload,
                            "reasoning_delta": reasoning or None,
                        }
                    )
            except Exception:
                pass

        try:
            planner_index = build_planner_index(diff_ctx.units, diff_ctx.mode, diff_ctx.base_branch)
            plan = await planner.run(planner_index, stream=True, observer=_planner_observer)
            events.stage_end("planner")

            planner_usage = getattr(planner, "last_usage", None)
            if planner_usage:
                call_usage, session_usage = self.usage_agg.update(planner_usage, 0)
                self.pipe_logger.log(
                    "planner_usage",
                    {
                        "call_index": 0,
                        "usage": planner_usage,
                        "call_usage": call_usage,
                        "session_usage": session_usage,
                        "trace_id": self.trace_id,
                    },
                )
                self._notify(stream_callback, {
                    "type": "usage_summary",
                    "usage_stage": "planner",
                    "call_index": 0,
                    "usage": planner_usage,
                    "call_usage": call_usage,
                    "session_usage": session_usage,
                })

            # Fusion & Context Phase
            events.stage_start("fusion")
            fused = fuse_plan(diff_ctx.review_index, plan)
            
            events.stage_start("context_provider")
            events.stage_start("context_bundle")
            
            context_bundle = build_context_bundle(diff_ctx, fused)
            bundle_stats = self._summarize_context_bundle(context_bundle)
            
            logger.info(
                "plan fused provider=%s plan_units=%d bundle_items=%d",
                self.review_provider,
                len(plan.get("plan", [])) if isinstance(plan, dict) else 0,
                len(context_bundle),
            )
            self.pipe_logger.log("planning_output", {"plan": plan})
            self.pipe_logger.log("fusion_output", {"fused": fused})
            
            events.stage_end("fusion")
            events.stage_end("final_context_plan")
            
            self.pipe_logger.log(
                "context_bundle_summary",
                {
                    "bundle_size": len(context_bundle),
                    "unit_ids": [c.get("unit_id") for c in context_bundle],
                    "bundle_stats": bundle_stats,
                },
            )

            if stream_callback:
                for item in context_bundle:
                    events.bundle_item(item)
            
            events.stage_end("context_bundle")
            events.stage_end("context_provider")

        except Exception as exc:
            logger.exception("pipeline failure after planner")
            self.pipe_logger.log(
                "pipeline_error",
                {"stage": "post_planner", "error": repr(exc), "trace_id": self.trace_id},
            )
            self._notify(stream_callback, {
                "type": "error",
                "stage": "post_planner",
                "message": str(exc),
            })
            raise

        # Review Phase
        runtime = ToolRuntime()
        for name, func in get_tool_functions(tool_names).items():
            runtime.register(name, func)
        
        tp = resolve_tools(tool_names, auto_approve)
        tools = tp["schemas"]
        auto_approve_list = tp["auto_approve"]

        context_provider = ContextProvider()
        state = ConversationState()
        trace_logger = APILogger(trace_id=self.trace_id)

        review_index_md, _ = build_markdown_and_json_context(diff_ctx)
        ctx_json = json.dumps({"context_bundle": context_bundle}, ensure_ascii=False, indent=2)
        augmented_prompt = build_review_prompt(review_index_md, ctx_json, prompt)
        self.pipe_logger.log(
            "review_request",
            {
                "prompt_preview": augmented_prompt[:2000],
                "context_bundle_size": len(context_bundle),
                "trace_id": self.trace_id,
            },
        )

        events.stage_start("reviewer")
        
        agent = CodeReviewAgent(
            self.review_adapter, runtime, context_provider, state, trace_logger=trace_logger
        )

        def _dispatch_stream(evt: Dict[str, Any]) -> None:
            """为用量事件补充聚合统计并记录日志。"""
            usage = evt.get("usage")
            call_index = evt.get("call_index")
            stage = evt.get("usage_stage") or ("planner" if call_index == 0 else "review")
            enriched = dict(evt)

            if usage:
                call_usage, session_usage = self.usage_agg.update(usage, call_index)
                enriched["call_usage"] = call_usage
                enriched["session_usage"] = session_usage
                enriched["usage_stage"] = stage
                if self.pipe_logger and evt.get("type") == "usage_summary":
                    self.pipe_logger.log(
                        "review_call_usage",
                        {
                            "call_index": call_index,
                            "usage_stage": stage,
                            "usage": usage,
                            "call_usage": call_usage,
                            "session_usage": session_usage,
                            "trace_id": self.trace_id,
                        },
                    )

            self._notify(stream_callback, enriched)

        tool_approver_cast = cast(Optional[Callable[[List[NormalizedToolCall]], List[NormalizedToolCall]]], tool_approver)
        result = await agent.run(
            augmented_prompt,
            files=diff_ctx.files,
            stream_observer=_dispatch_stream,
            tools=tools,  # type: ignore[arg-type]
            auto_approve_tools=auto_approve_list,
            tool_approver=tool_approver_cast,
        )
        
        self.pipe_logger.log("review_result", {"result_preview": str(result)[:500]})
        events.stage_end("reviewer")
        
        fb_summary = fallback_tracker.emit_summary(logger=logger, pipeline_logger=self.pipe_logger)
        if fb_summary.get("total"):
            self._notify(stream_callback, {
                "type": "warning",
                "message": f"回退触发 {fb_summary['total']} 次：{fb_summary['by_key']}",
                "fallback_summary": fb_summary,
            })
            
        self.pipe_logger.log(
            "session_end",
            {
                "log_path": str(self.session_log),
                "session_usage": self.usage_agg.session_totals(),
                "trace_id": self.trace_id,
            },
        )
        events.stage_end("final_output", result_preview=str(result)[:300])
        
        return result
