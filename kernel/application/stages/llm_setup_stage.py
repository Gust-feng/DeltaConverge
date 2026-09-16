"""LLM 资源初始化 Stage。

负责：
1. 生成 trace_id
2. 创建 review / planner LLM 客户端
3. 组装适配器
"""

from __future__ import annotations

import logging

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter
from kernel.ports.llm import LLMFactoryPort

logger = logging.getLogger(__name__)


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

        # 2. Review 客户端（优先旧工厂真实链路，Port 创建仅用于校验/预热）
        from Agent.core.api.factory import LLMFactory
        ctx.review_client, ctx.review_provider = LLMFactory.create(
            ctx.request.model, trace_id=ctx.trace_id
        )
        try:
            _ = self.llm_factory.create_client(ctx.request.model, trace_id=ctx.trace_id)
        except Exception:
            # Port 创建仅用于校验/预热，失败不影响主链路，但必须留痕
            logger.warning(
                "LLMFactoryPort 预热 review 客户端失败 (model=%s)",
                ctx.request.model,
                exc_info=True,
            )

        # 3. Planner 客户端
        planner_pref = resolve_planner_preference(
            ctx.request.model, ctx.request.planner_model
        )
        if planner_pref == ctx.request.model:
            ctx.planner_client = ctx.review_client
            ctx.planner_provider = ctx.review_provider
        else:
            ctx.planner_client, ctx.planner_provider = LLMFactory.create(
                planner_pref, trace_id=ctx.trace_id
            )
            try:
                _ = self.llm_factory.create_client(planner_pref, trace_id=ctx.trace_id)
            except Exception:
                # 同上：planner 预热失败不阻断流程，仅记录
                logger.warning(
                    "LLMFactoryPort 预热 planner 客户端失败 (model=%s)",
                    planner_pref,
                    exc_info=True,
                )

        # 4. 适配器（保留旧接口兼容性）
        ctx.review_adapter = OpenAIAdapter(
            ctx.review_client, StreamProcessor(), provider_name=ctx.review_provider
        )
        ctx.planner_adapter = OpenAIAdapter(
            ctx.planner_client, StreamProcessor(), provider_name=ctx.planner_provider
        )

