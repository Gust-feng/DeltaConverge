"""Legacy 审查引擎适配器

包装旧内核的四个"大脑"，实现 kernel/ports/engines.py 定义的端口：

- ``Agent.agents.intent_agent.IntentAgent``   → IntentEnginePort
- ``Agent.agents.planning_agent.PlanningAgent`` → PlannerEnginePort
- ``Agent.agents.fusion.fuse_plan``          → FusionEnginePort
- ``Agent.agents.code_reviewer.CodeReviewAgent`` → ReviewerEnginePort

设计要点：
1. ConversationState / ToolRuntime / ContextProvider / APILogger 等 legacy 内部
   类型全部在本模块内部装配，不出现在端口签名上；
2. 引擎类通过**模块属性方式**延迟解析（``module.ClassName``），
   使既有测试的 ``patch("Agent.agents.planning_agent.PlanningAgent", ...)``
   仍然生效；
3. 只做接线，不改引擎内部逻辑。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from kernel.ports.engines import (
    FusionContractViolation,
    FusionEnginePort,
    IntentEnginePort,
    IntentEngineResult,
    PlannerEnginePort,
    PlannerEngineResult,
    ReviewEngineResult,
    ReviewerEnginePort,
    StreamObserverCallback,
)

logger = logging.getLogger(__name__)


def _new_conversation_state() -> Any:
    """创建 legacy 对话状态对象。"""
    from Agent.core.state import conversation as conversation_module

    return conversation_module.ConversationState()


class LegacyIntentEngine(IntentEnginePort):
    """包装旧 IntentAgent 的适配器。"""

    async def analyze(
        self,
        *,
        llm_adapter: Any,
        intent_input: Dict[str, Any],
        stream: bool = True,
        observer: Optional[StreamObserverCallback] = None,
    ) -> IntentEngineResult:
        from Agent.agents import intent_agent as intent_module

        agent = intent_module.IntentAgent(llm_adapter, _new_conversation_state())
        summary = await agent.run(intent_input, stream=stream, observer=observer)
        return IntentEngineResult(
            summary=summary or "",
            usage=getattr(agent, "last_usage", None),
        )


class LegacyPlannerEngine(PlannerEnginePort):
    """包装旧 PlanningAgent 的适配器。"""

    async def plan(
        self,
        *,
        llm_adapter: Any,
        review_index: Dict[str, Any],
        stream: bool = False,
        observer: Optional[StreamObserverCallback] = None,
        intent_summary: Optional[str] = None,
        user_prompt: Optional[str] = None,
    ) -> PlannerEngineResult:
        from Agent.agents import planning_agent as planning_module

        planner = planning_module.PlanningAgent(llm_adapter, _new_conversation_state())
        plan = await planner.run(
            review_index,
            stream=stream,
            observer=observer,
            intent_md=intent_summary,
            user_prompt=user_prompt,
        )
        if not isinstance(plan, dict):
            raise RuntimeError("planner returned invalid plan payload")
        return PlannerEngineResult(
            plan=plan,
            usage=getattr(planner, "last_usage", None),
        )


class LegacyFusionEngine(FusionEnginePort):
    """包装旧 fuse_plan 的适配器。"""

    def fuse(
        self,
        review_index: Dict[str, Any],
        llm_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        from Agent.agents import fusion as fusion_module

        try:
            return fusion_module.fuse_plan(review_index, llm_plan)
        except fusion_module.FusionContractError as exc:
            # 转换为内核级异常，避免 application 层依赖 legacy 异常类型
            raise FusionContractViolation(str(exc)) from exc


class LegacyReviewerEngine(ReviewerEnginePort):
    """包装旧 CodeReviewAgent 的适配器。"""

    async def review(
        self,
        *,
        llm_adapter: Any,
        prompt: str,
        files: Sequence[str],
        tools: Optional[List[Dict[str, Any]]] = None,
        auto_approve_tools: Optional[List[str]] = None,
        tool_approver: Optional[Callable[[Any], Any]] = None,
        stream_observer: Optional[StreamObserverCallback] = None,
        trace_id: Optional[str] = None,
        file_tree: Optional[Dict[str, Any]] = None,
        message_history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        with_context_provider: bool = True,
    ) -> ReviewEngineResult:
        from Agent.agents import code_reviewer as reviewer_module
        from Agent.core.tools.runtime import ToolRuntime
        from Agent.tool.registry import get_tool_functions

        # 1. 工具运行时：注册工具实现
        runtime = ToolRuntime()
        tool_names = [
            str(item.get("function", {}).get("name") or item.get("name") or "")
            for item in (tools or [])
            if isinstance(item, dict)
        ]
        tool_names = [name for name in tool_names if name]
        if tool_names:
            for name, func in get_tool_functions(tool_names).items():
                runtime.register(name, func)

        # 2. 上下文提供器（legacy 内部类型，不外泄）
        context_provider = None
        if with_context_provider:
            from Agent.core.context.provider import ContextProvider

            context_provider = ContextProvider()

        # 3. 对话状态与预置历史
        state = _new_conversation_state()
        if system_prompt:
            state.add_system_message(system_prompt)
        for msg in message_history or []:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = str(msg.get("content") or "")
            if role == "user":
                state.add_user_message(content)
            elif role == "assistant":
                state.add_assistant_message(content, msg.get("tool_calls") or [])
            elif role == "system":
                state.add_system_message(content)

        # 4. 链路日志器
        trace_logger = None
        if trace_id:
            from Agent.core.logging.api_logger import APILogger

            trace_logger = APILogger(trace_id=trace_id)

        agent = reviewer_module.CodeReviewAgent(
            llm_adapter,
            runtime,
            context_provider,
            state,
            trace_logger=trace_logger,
            file_tree=file_tree or {},
        )
        report = await agent.run(
            prompt,
            files=list(files),
            stream_observer=stream_observer,
            tools=tools,  # type: ignore[arg-type]
            auto_approve_tools=auto_approve_tools,
            tool_approver=tool_approver,
        )
        return ReviewEngineResult(
            report=str(report),
            usage=getattr(agent, "last_usage", None),
        )


__all__ = [
    "LegacyFusionEngine",
    "LegacyIntentEngine",
    "LegacyPlannerEngine",
    "LegacyReviewerEngine",
]
