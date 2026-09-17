from __future__ import annotations

from pathlib import Path
from typing import Optional

from kernel.application import KernelFacade, ReviewOrchestrator, RunEventBus
from kernel.application.services import (
    ConfigService,
    ProjectService,
    ReviewService,
    RuleService,
    SessionService,
    SystemService,
)
from kernel.infrastructure import (
    FileArtifactStore,
    SQLiteKernelStore,
    LegacyLLMFactory,
    LegacyGitAdapter,
    LegacyDiffAdapter,
    LegacyToolRegistry,
    LegacyToolPolicy,
    LegacyPromptAdapter,
    LegacyContextAdapter,
    LegacyConfigAdapter,
    LegacyProjectAdapter,
    LegacyProjectDiffAdapter,
    LegacyRuleAdapter,
    LegacyRuntimeContextAdapter,
    LegacyFusionEngine,
    LegacyIntentEngine,
    LegacyPlannerEngine,
    LegacyReviewerEngine,
)
from kernel.infrastructure.scan.legacy_adapter import LegacyScanServiceAdapter
from kernel.infrastructure.scan.runner import LegacyScanRunner

_facade: Optional[KernelFacade] = None


def build_kernel_facade(root: Optional[Path] = None) -> KernelFacade:
    """组装一个内核 Facade 实例（组合根）。

    所有 Port 适配器在此集中创建并注入，Stage 与 Service 不再各自隐式兜底，
    以便外部替换任意端口（测试可注入 Fake 实现）。
    """
    root = root or Path(__file__).resolve().parents[1]
    data_root = root / "data" / "kernel"

    # ── 核心存储与事件 ──
    store = SQLiteKernelStore(data_root / "kernel.db")
    artifact_store = FileArtifactStore(data_root / "artifacts")
    event_bus = RunEventBus()

    # ── 基础设施适配器（桥接旧内核） ──
    scan_service = LegacyScanServiceAdapter()
    scan_runner = LegacyScanRunner()
    llm_factory = LegacyLLMFactory()
    git_adapter = LegacyGitAdapter()
    diff_adapter = LegacyDiffAdapter(git_adapter=git_adapter)
    runtime_context = LegacyRuntimeContextAdapter()

    # Stage 级端口
    context_port = LegacyContextAdapter()
    prompt_port = LegacyPromptAdapter()
    config_port = LegacyConfigAdapter()
    project_port = LegacyProjectAdapter()
    tool_registry = LegacyToolRegistry()
    tool_policy = LegacyToolPolicy(registry=tool_registry)

    # 引擎端口（审查链路的四个"大脑"）
    intent_engine = LegacyIntentEngine()
    planner_engine = LegacyPlannerEngine()
    fusion_engine = LegacyFusionEngine()
    reviewer_engine = LegacyReviewerEngine()

    # ── 编排器 ──
    orchestrator = ReviewOrchestrator(
        store=store,
        artifact_store=artifact_store,
        event_bus=event_bus,
        scan_service=scan_service,
        llm_factory=llm_factory,
        git_port=git_adapter,
        diff_port=diff_adapter,
        runtime_context=runtime_context,
        scan_runner=scan_runner,
        context_port=context_port,
        prompt_port=prompt_port,
        config_port=config_port,
        project_port=project_port,
        tool_policy=tool_policy,
        intent_engine=intent_engine,
        planner_engine=planner_engine,
        fusion_engine=fusion_engine,
        reviewer_engine=reviewer_engine,
    )

    # ── 服务层 ──
    review_service = ReviewService(
        store,
        artifact_store,
        event_bus,
        orchestrator,
        llm_factory=llm_factory,
        reviewer_engine=reviewer_engine,
    )
    session_service = SessionService(store, artifact_store)
    config_service = ConfigService(config_port=config_port)
    project_service = ProjectService(
        project_port=project_port,
        project_diff_port=LegacyProjectDiffAdapter(),
        git_port=git_adapter,
    )
    rule_service = RuleService(rule_port=LegacyRuleAdapter())
    system_service = SystemService()

    return KernelFacade(
        store=store,
        artifact_store=artifact_store,
        event_bus=event_bus,
        orchestrator=orchestrator,
        review_service=review_service,
        session_service=session_service,
        config_service=config_service,
        project_service=project_service,
        rule_service=rule_service,
        system_service=system_service,
    )


def get_kernel_facade() -> KernelFacade:
    """获取新内核 Facade（单例模式）

    新内核通过 Port 接口与旧内核交互，使用 Legacy 适配器桥接。
    这样架构上已经解耦，后续可以逐步替换 Legacy 适配器为原生实现。
    """
    global _facade
    if _facade is None:
        _facade = build_kernel_facade()
    return _facade


def reset_kernel_facade() -> None:
    """重置内核 Facade（用于测试）"""
    global _facade
    _facade = None