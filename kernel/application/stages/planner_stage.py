"""Planner 规划 Stage。

负责：
1. 构建 planner_index（Diff 摘要）
2. 调用 PlanningAgent 生成审查规划
3. 将 plan 写入 ctx.plan
"""

from __future__ import annotations

from typing import Any, Dict

from kernel.domain.context import PipelineContext, PlannerStageOutput
from kernel.domain.protocols import EventEmitter


class PlannerStage:
    """审查规划。"""

    @property
    def name(self) -> str:
        return "planner"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        request = ctx.request
        agents = set(request.agents or ["intent", "planner", "reviewer"])

        if "planner" not in agents:
            ctx.plan = {}
            ctx.planner_output = PlannerStageOutput(plan={})
            return

        emit.stage_started("planner")
        from Agent.agents.planning_agent import PlanningAgent
        from Agent.DIFF.output_formatting import build_planner_index
        from Agent.core.state.conversation import ConversationState

        diff_ctx = ctx.diff_ctx
        planner_index = build_planner_index(diff_ctx.units, diff_ctx.mode, diff_ctx.base_branch)

        planner = PlanningAgent(ctx.planner_adapter, ConversationState())
        plan = await planner.run(
            planner_index,
            stream=False,
            observer=None,
            intent_md=ctx.intent_summary,
            user_prompt=request.prompt,
        )

        if not isinstance(plan, dict):
            raise RuntimeError("planner returned invalid plan payload")

        ctx.plan = plan
        ctx.planner_output = PlannerStageOutput(plan=plan, usage=getattr(planner, "last_usage", None))
        emit.stage_finished("planner", has_output=bool(plan))

        # 上报用量
        usage = getattr(planner, "last_usage", None)
        if usage:
            emit.delta(
                "planner",
                type="usage_summary",
                usage_stage="planner",
                call_index=0,
                usage=usage,
            )
