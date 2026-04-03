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
from kernel.infrastructure import FileArtifactStore, SQLiteKernelStore

_facade: Optional[KernelFacade] = None


def get_kernel_facade() -> KernelFacade:
    global _facade
    if _facade is None:
        root = Path(__file__).resolve().parents[1]
        data_root = root / "data" / "kernel"
        store = SQLiteKernelStore(data_root / "kernel.db")
        artifact_store = FileArtifactStore(data_root / "artifacts")
        event_bus = RunEventBus()
        orchestrator = ReviewOrchestrator(store, artifact_store, event_bus)

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
