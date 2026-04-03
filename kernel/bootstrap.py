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
    LegacyConversationAdapter,
    LegacyToolRegistry,
    LegacyToolRuntime,
    LegacyToolPolicy,
    LegacyPromptAdapter,
    LegacyContextAdapter,
    LegacyStreamAdapter,
)
from kernel.infrastructure.scan.legacy_adapter import LegacyScanServiceAdapter

_facade: Optional[KernelFacade] = None


def get_kernel_facade() -> KernelFacade:
    """获取新内核 Facade（单例模式）
    
    新内核通过 Port 接口与旧内核交互，使用 Legacy 适配器桥接。
    这样架构上已经解耦，后续可以逐步替换 Legacy 适配器为原生实现。
    """
    global _facade
    if _facade is None:
        root = Path(__file__).resolve().parents[1]
        data_root = root / "data" / "kernel"
        
        # 核心存储
        store = SQLiteKernelStore(data_root / "kernel.db")
        artifact_store = FileArtifactStore(data_root / "artifacts")
        event_bus = RunEventBus()
        scan_service = LegacyScanServiceAdapter()
        
        # Port 适配器（桥接旧内核）
        llm_factory = LegacyLLMFactory()
        git_adapter = LegacyGitAdapter()
        diff_adapter = LegacyDiffAdapter(git_adapter=git_adapter)
        conversation_adapter = LegacyConversationAdapter()
        tool_registry = LegacyToolRegistry()
        tool_runtime = LegacyToolRuntime(registry=tool_registry)
        tool_policy = LegacyToolPolicy(registry=tool_registry)
        prompt_adapter = LegacyPromptAdapter()
        context_adapter = LegacyContextAdapter()
        stream_adapter = LegacyStreamAdapter()
        
        # 编排器（注入 Port 依赖）
        orchestrator = ReviewOrchestrator(
            store=store,
            artifact_store=artifact_store,
            event_bus=event_bus,
            scan_service=scan_service,
            # Port 依赖注入
            llm_factory=llm_factory,
            git_port=git_adapter,
            diff_port=diff_adapter,
        )

        # 服务层
        review_service = ReviewService(store, artifact_store, event_bus, orchestrator)
        session_service = SessionService(store, artifact_store)
        config_service = ConfigService()
        project_service = ProjectService()
        rule_service = RuleService()
        system_service = SystemService()

        _facade = KernelFacade(
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
    return _facade


def reset_kernel_facade() -> None:
    """重置内核 Facade（用于测试）"""
    global _facade
    _facade = None
