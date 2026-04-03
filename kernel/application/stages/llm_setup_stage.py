"""LLM 资源初始化 Stage。

负责：
1. 生成 trace_id
2. 创建 review / planner LLM 客户端
3. 组装 OpenAI 适配器
"""

from __future__ import annotations

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter


class LLMSetupStage:
    """创建 LLM 客户端与适配器，写入 PipelineContext。"""

    @property
    def name(self) -> str:
        return "llm_setup"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        from Agent.core.logging.context import generate_trace_id
        from Agent.core.api.factory import LLMFactory
        from Agent.core.api.api import resolve_planner_preference
        from Agent.core.adapter.llm_adapter import OpenAIAdapter
        from Agent.core.stream.stream_processor import StreamProcessor

        # 1. trace_id
        ctx.trace_id = generate_trace_id()

        # 2. Review 客户端
        review_client, review_provider = LLMFactory.create(
            ctx.request.model, trace_id=ctx.trace_id
        )
        ctx.review_client = review_client
        ctx.review_provider = review_provider

        # 3. Planner 客户端（可能复用 review 客户端）
        planner_pref = resolve_planner_preference(
            ctx.request.model, ctx.request.planner_model
        )
        if planner_pref == ctx.request.model:
            ctx.planner_client = review_client
            ctx.planner_provider = review_provider
        else:
            planner_client, planner_provider = LLMFactory.create(
                planner_pref, trace_id=ctx.trace_id
            )
            ctx.planner_client = planner_client
            ctx.planner_provider = planner_provider

        # 4. 适配器
        ctx.review_adapter = OpenAIAdapter(
            review_client, StreamProcessor(), provider_name=review_provider
        )
        ctx.planner_adapter = OpenAIAdapter(
            ctx.planner_client, StreamProcessor(), provider_name=ctx.planner_provider
        )
