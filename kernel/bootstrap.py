from __future__ import annotations

import importlib
import logging
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

# 适配器在方法体内惰性导入的旧模块清单。
#
# 为何需要预热：这些惰性导入一旦发生在请求线程（FastAPI 的 threadpool）中，
# 并发请求会同时请求相互引用的模块，CPython 的 per-module 导入锁可能形成
# 等待环，触发 _DeadlockError（表现为偶发 500）。在服务启动阶段（单线程）
# 预先导入，请求期即可直接从 sys.modules 命中，不再争锁。
_PREWARM_MODULES = (
    # 旧 API 层（Agent.core.api 包初始化会带入 config/tools/project/diff 等）
    "Agent.core.api",
    "Agent.core.api.tools",
    "Agent.core.api.api",
    "Agent.core.api.factory",
    "Agent.core.api.diff",
    "Agent.core.api.project",
    "Agent.core.api.config",
    "Agent.core.api.rule_growth",
    # 工具系统
    "Agent.tool.registry",
    "Agent.core.tools.runtime",
    "Agent.core.services.tool_policy",
    "Agent.core.services.prompt_builder",
    # 上下文与状态
    "Agent.core.context.diff_provider",
    "Agent.core.context.provider",
    "Agent.core.context.runtime_context",
    "Agent.core.state.conversation",
    # 流与适配器
    "Agent.core.stream.stream_processor",
    "Agent.core.adapter.llm_adapter",
    "Agent.core.logging.api_logger",
    # 审查引擎
    "Agent.agents",
    "Agent.agents.context_scheduler",
    # Diff 与扫描
    "Agent.DIFF.git_operations",
    "Agent.DIFF.output_formatting",
    "Agent.DIFF.rule",
    "Agent.DIFF.rule.context_decision",
    "Agent.DIFF.rule.scanner_registry",
    "Agent.DIFF.static_scan_service",
)


def prewarm_legacy_imports() -> None:
    """在服务启动阶段（单线程）预先导入旧模块，避免请求期并发导入死锁。

    单个模块导入失败不阻断启动，仅记录告警——缺失的扫描器或可选依赖
    不应让整个服务起不来。
    """
    logger = logging.getLogger(__name__)
    for module in _PREWARM_MODULES:
        try:
            importlib.import_module(module)
        except Exception:
            logger.warning("预热导入失败 (module=%s)", module, exc_info=True)


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