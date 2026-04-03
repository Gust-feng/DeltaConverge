"""LLM 资源初始化 Stage。

负责：
1. 生成 trace_id
2. 创建 review / planner LLM 客户端
3. 组装适配器
"""

from __future__ import annotations

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter
from kernel.ports.llm import LLMFactoryPort


class LLMSetupStage:
    """创建 LLM 客户端与适配器，写入 PipelineContext。"""

    def __init__(
        self,
        *,
        llm_factory: LLMFactoryPort,
    ) -> None:
        self.llm_factory = llm_factory

    @property
    def name(self) -> str:
        return "llm_setup"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        import uuid
        from Agent.core.api.api import resolve_planner_preference
        from Agent.core.adapter.llm_adapter import OpenAIAdapter
        from Agent.core.stream.stream_processor import StreamProcessor

        # 1. trace_id
        ctx.trace_id = str(uuid.uuid4())

        # 2. Review 客户端（使用 Port 接口）
        review_llm_client = self.llm_factory.create_client(
            ctx.request.model,
            trace_id=ctx.trace_id,
        )
        
        # 保留旧接口兼容性（从适配器中提取底层客户端）
        if hasattr(review_llm_client, '_adapter'):
            ctx.review_client = review_llm_client._adapter.client
            ctx.review_provider = getattr(review_llm_client._adapter, 'provider_name', 'openai')
        else:
            # 回退：直接使用旧工厂
            from Agent.core.api.factory import LLMFactory
            ctx.review_client, ctx.review_provider = LLMFactory.create(
                ctx.request.model, trace_id=ctx.trace_id
            )

        # 3. Planner 客户端
        planner_pref = resolve_planner_preference(
            ctx.request.model, ctx.request.planner_model
        )
        if planner_pref == ctx.request.model:
            ctx.planner_client = ctx.review_client
            ctx.planner_provider = ctx.review_provider
        else:
            planner_llm_client = self.llm_factory.create_client(
                planner_pref,
                trace_id=ctx.trace_id,
            )
            if hasattr(planner_llm_client, '_adapter'):
                ctx.planner_client = planner_llm_client._adapter.client
                ctx.planner_provider = getattr(planner_llm_client._adapter, 'provider_name', 'openai')
            else:
                from Agent.core.api.factory import LLMFactory
                ctx.planner_client, ctx.planner_provider = LLMFactory.create(
                    planner_pref, trace_id=ctx.trace_id
                )

        # 4. 适配器（保留旧接口兼容性）
        ctx.review_adapter = OpenAIAdapter(
            ctx.review_client, StreamProcessor(), provider_name=ctx.review_provider
        )
        ctx.planner_adapter = OpenAIAdapter(
            ctx.planner_client, StreamProcessor(), provider_name=ctx.planner_provider
        )

