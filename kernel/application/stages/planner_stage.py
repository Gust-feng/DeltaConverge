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

        # 容错：planner 可能返回缺 target 的 extra_request，预先清洗，避免后续 contract fail。
        plan = self._sanitize_plan_extra_requests(plan)

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
