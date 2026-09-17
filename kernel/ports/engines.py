"""审查引擎接口定义

定义审查流水线中四个"大脑"的抽象接口：
意图分析、审查规划、规则/规划融合、代码审查执行。

设计原则：
1. 只暴露 application 层真正需要的输入输出；
2. 不把 legacy 内部类型（ConversationState / ToolRuntime / ContextProvider /
   APILogger 等）泄漏到端口签名里 —— 这些一律由适配器内部自行装配；
3. LLM 适配器对象以 ``llm_adapter: Any`` 透传，application 层只负责搬运，
   不解释其内部结构（"接线版独立"，不重写引擎内部逻辑）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, runtime_checkable

# 流式事件观察者：接收引擎产生的增量事件字典
StreamObserverCallback = Callable[[Dict[str, Any]], None]


class FusionContractViolation(RuntimeError):
    """融合输入不满足内核契约。

    内核级异常，用于替代 legacy 的 ``FusionContractError``，
    使 application 层无需 import 旧模块即可捕获该失败语义。
    """


@dataclass
class IntentEngineResult:
    """意图分析结果。"""

    summary: str = ""
    usage: Optional[Dict[str, Any]] = None


@dataclass
class PlannerEngineResult:
    """审查规划结果。"""

    plan: Dict[str, Any] = field(default_factory=dict)
    usage: Optional[Dict[str, Any]] = None


@dataclass
class ReviewEngineResult:
    """代码审查执行结果。"""

    report: str = ""
    usage: Optional[Dict[str, Any]] = None


@runtime_checkable
class IntentEnginePort(Protocol):
    """项目意图分析引擎接口。"""

    async def analyze(
        self,
        *,
        llm_adapter: Any,
        intent_input: Dict[str, Any],
        stream: bool = True,
        observer: Optional[StreamObserverCallback] = None,
    ) -> IntentEngineResult:
        """根据项目概览生成意图摘要。

        Args:
            llm_adapter: LLM 适配器对象（由 LLMSetupStage 准备，透传）
            intent_input: 项目概览数据（文件树 / README / 提交历史等）
            stream: 是否流式输出
            observer: 流式增量事件回调

        Returns:
            意图摘要与用量信息
        """
        ...


@runtime_checkable
class PlannerEnginePort(Protocol):
    """审查规划引擎接口。"""

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
        """基于 diff 索引生成上下文规划。

        Args:
            llm_adapter: LLM 适配器对象（透传）
            review_index: diff 摘要索引
            stream: 是否流式输出
            observer: 流式增量事件回调
            intent_summary: 项目意图摘要
            user_prompt: 用户额外审查指令

        Returns:
            规划结果与用量信息
        """
        ...


@runtime_checkable
class FusionEnginePort(Protocol):
    """规则与规划融合引擎接口。"""

    def fuse(
        self,
        review_index: Dict[str, Any],
        llm_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        """融合规则层结果与 LLM 规划。

        Args:
            review_index: 含 units 的原始元数据索引
            llm_plan: 规划引擎输出

        Returns:
            融合后的计划 ``{"plan": [...]}``

        Raises:
            FusionContractViolation: 输入不满足内核契约
        """
        ...


@runtime_checkable
class ReviewerEnginePort(Protocol):
    """代码审查执行引擎接口。"""

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
        """执行代码审查并返回报告文本。

        Args:
            llm_adapter: LLM 适配器对象（透传）
            prompt: 已组装好的审查提示词
            files: 变更文件列表
            tools: 工具 schema 列表
            auto_approve_tools: 免确认工具名单
            tool_approver: 工具调用审批回调
            stream_observer: 流式增量事件回调
            trace_id: 链路追踪 ID（适配器据此创建日志器）
            file_tree: 项目文件树，供引擎补充系统提示
            message_history: 预置历史消息（role/content/tool_calls）
            system_prompt: 显式系统提示词（QA 场景使用）
            with_context_provider: 是否启用上下文提供器

        Returns:
            审查报告与用量信息
        """
        ...


__all__ = [
    "FusionContractViolation",
    "FusionEnginePort",
    "IntentEnginePort",
    "IntentEngineResult",
    "PlannerEnginePort",
    "PlannerEngineResult",
    "ReviewEngineResult",
    "ReviewerEnginePort",
    "StreamObserverCallback",
]
