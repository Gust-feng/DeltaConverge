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
from kernel.ports.diff import DiffPort
from kernel.ports.engines import PlannerEnginePort


class PlannerStage:
    """审查规划。"""

    def __init__(
        self,
        *,
        planner_engine: PlannerEnginePort | None = None,
        diff_port: DiffPort | None = None,
    ) -> None:
        if planner_engine is None:
            from kernel.infrastructure import LegacyPlannerEngine
            planner_engine = LegacyPlannerEngine()
        if diff_port is None:
            from kernel.infrastructure import LegacyDiffAdapter
            diff_port = LegacyDiffAdapter()
        self.planner_engine = planner_engine
        self.diff_port = diff_port

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

        planner_index = self.diff_port.build_planner_index(ctx.diff_ctx)

        # 旧版规划阶段是流式的：前端依赖 delta 事件渲染“上下文决策”与
        # planner 可视化。这里恢复流式观察者，事件形态与旧 SSE 保持一致。
        def _observer(event: Dict[str, Any]) -> None:
            emit.delta("planner", **event)

        result = await self.planner_engine.plan(
            llm_adapter=ctx.planner_adapter,
            review_index=planner_index,
            stream=True,
            observer=_observer,
            intent_summary=ctx.intent_summary,
            user_prompt=request.prompt,
        )
        plan = result.plan

        # 容错：planner 可能返回缺 target 的 extra_request，预先清洗，避免后续 contract fail。
        plan = self._sanitize_plan_extra_requests(plan)

        ctx.plan = plan
        ctx.planner_output = PlannerStageOutput(plan=plan, usage=result.usage)
        emit.stage_finished("planner", has_output=bool(plan))

        # 上报用量
        usage = result.usage
        if usage:
            emit.delta(
                "planner",
                type="usage_summary",
                usage_stage="planner",
                call_index=0,
                usage=usage,
            )

    @staticmethod
    def _sanitize_plan_extra_requests(plan: Dict[str, Any]) -> Dict[str, Any]:
        items = plan.get("plan")
        if not isinstance(items, list):
            return plan
        target_required = {"callers", "search_implementations", "search", "search_config_usage"}
        out_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            reqs = item.get("extra_requests")
            if not isinstance(reqs, list):
                out_items.append(item)
                continue
            cleaned = []
            for req in reqs:
                if not isinstance(req, dict):
                    continue
                req_type = str(req.get("type") or "").strip()
                if req_type == "search_callers":
                    req_type = "callers"
                if not req_type:
                    continue
                details = req.get("details") or req.get("symbol") or req.get("keyword") or req.get("text")
                details = str(details).strip() if details is not None else ""
                if req_type in target_required and not details:
                    continue
                nr = dict(req)
                nr["type"] = req_type
                cleaned.append(nr)
            ni = dict(item)
            ni["extra_requests"] = cleaned
            out_items.append(ni)
        out = dict(plan)
        out["plan"] = out_items
        return out
