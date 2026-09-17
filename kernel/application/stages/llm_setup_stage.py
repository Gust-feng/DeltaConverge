"""LLM 资源初始化 Stage。

负责：
1. 生成 trace_id
2. 创建 review / planner LLM 客户端
3. 组装适配器

全部经 LLMFactoryPort 完成，不直接依赖旧 Agent/ 代码。
"""

from __future__ import annotations

import logging
import uuid

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter
from kernel.ports.llm import LLMFactoryPort

logger = logging.getLogger(__name__)


class LLMSetupStage:
    """创建 LLM 客户端与适配器，写入 PipelineContext。"""

    def __init__(
        self,
        *,
        llm_factory: LLMFactoryPort | None = None,
    ) -> None:
        if llm_factory is None:
            from kernel.infrastructure import LegacyLLMFactory
            llm_factory = LegacyLLMFactory()
        self.llm_factory = llm_factory

    @property
    def name(self) -> str:
        return "llm_setup"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        # 1. trace_id
        ctx.trace_id = str(uuid.uuid4())

        # 2. Review 客户端（client / provider / adapter 三件套由端口一次装配）
        review_runtime = self.llm_factory.create_runtime_client(
            ctx.request.model, trace_id=ctx.trace_id
        )
        ctx.review_client = review_runtime.client
        ctx.review_provider = review_runtime.provider
        ctx.review_adapter = review_runtime.adapter

        # 3. Planner 客户端：与 review 同模型时直接复用，避免重复建连
        planner_pref = self.llm_factory.resolve_planner_preference(
            ctx.request.model, ctx.request.planner_model
        )
        if planner_pref == ctx.request.model:
            ctx.planner_client = ctx.review_client
            ctx.planner_provider = ctx.review_provider
            ctx.planner_adapter = ctx.review_adapter
        else:
            planner_runtime = self.llm_factory.create_runtime_client(
                planner_pref, trace_id=ctx.trace_id
            )
            ctx.planner_client = planner_runtime.client
            ctx.planner_provider = planner_runtime.provider
            ctx.planner_adapter = planner_runtime.adapter
