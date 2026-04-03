"""Pipeline 执行引擎。

按序执行 Stage 列表，内核信任原则：Stage 内部错误直接向上传播。
"""

from __future__ import annotations

from typing import Sequence

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter, Stage


class PipelineExecutor:
    """线性执行 Stage 列表的引擎。

    职责单一：按序调用每个 Stage 的 execute 方法。
    不做错误吞咽，异常直接传播给调用方（ReviewOrchestrator）。
    """

    def __init__(self, stages: Sequence[Stage], emitter: EventEmitter) -> None:
        self.stages = stages
        self.emitter = emitter

    async def run(self, ctx: PipelineContext) -> str:
        """执行所有 Stage，返回最终审查报告。"""
        for stage in self.stages:
            await stage.execute(ctx, self.emitter)
        return ctx.final_report or ""
