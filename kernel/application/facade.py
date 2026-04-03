"""内核统一门户层（门面模式）。

将外部请求委托给底层的各个独立 Service，自身作为聚合代理，
API 方法签名保持与重构前100%一致。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional

from kernel.domain.models import (
    ProjectAnalysis, QARequest, QAResponse, ReviewCreateRequest,
    ReviewRun, ScanResult, SessionDetail, SessionSummary, WorkflowEvent,
)
from kernel.ports.stores import ArtifactStore, SessionStore

from .services.config_service import ConfigService
from .services.project_service import ProjectService
from .services.review_service import ReviewService
from .services.rule_service import RuleService
from .services.session_service import SessionService
from .services.system_service import SystemService
from .event_bus import RunEventBus
from .review_orchestrator import ReviewOrchestrator


class KernelFacade:
    def __init__(
        self,
        *,
        store: SessionStore,
        artifact_store: ArtifactStore,
        event_bus: RunEventBus,
        orchestrator: ReviewOrchestrator,
        review_service: ReviewService,
        session_service: SessionService,
        config_service: ConfigService,
        project_service: ProjectService,
        rule_service: RuleService,
        system_service: SystemService,
    ) -> None:
        # 保留原有基础属性，以保持向下兼容（旧代码如果直访 self.store 不会报错）
        self.store = store
        self.artifact_store = artifact_store
        self.event_bus = event_bus
        self.orchestrator = orchestrator

        self.review_service = review_service
        self.session_service = session_service
        self.config_service = config_service
        self.project_service = project_service
        self.rule_service = rule_service
        self.system_service = system_service

    # ── Review Lifecycle (from review_service) ──
    async def create_review_run(self, request: ReviewCreateRequest) -> Dict[str, object]:
        return await self.review_service.create_review_run(request)

    async def stream_review(self, run_id: str) -> AsyncIterator[WorkflowEvent]:
        async for event in self.review_service.stream_review(run_id):
            yield event

    async def ask_review_qa(self, request: QARequest) -> QAResponse:
        return await self.review_service.ask_review_qa(request)

    # ── Session & Run Management (from session_service) ──
    def list_sessions(self, *, status: Optional[str] = None, project_root: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[SessionSummary]:
        return self.session_service.list_sessions(status=status, project_root=project_root, limit=limit, offset=offset)

    def get_session_summary(self, session_id: str) -> Optional[SessionSummary]:
        return self.session_service.get_session_summary(session_id)

    def get_session_detail(self, session_id: str) -> Optional[SessionDetail]:
        return self.session_service.get_session_detail(session_id)

    def get_session_messages(self, session_id: str, *, limit: int = 200, offset: int = 0):
        return self.session_service.get_session_messages(session_id, limit=limit, offset=offset)

    def get_session_events(self, run_id: str, *, limit: Optional[int] = None, offset: int = 0):
        return self.session_service.get_session_events(run_id, limit=limit, offset=offset)

    def update_session(self, session_id: str, *, name: Optional[str] = None, status: Optional[str] = None, tags: Optional[List[str]] = None) -> Optional[SessionSummary]:
        return self.session_service.update_session(session_id, name=name, status=status, tags=tags)

    def delete_session(self, session_id: str) -> None:
        self.session_service.delete_session(session_id)

    def get_review_run(self, run_id: str) -> Optional[ReviewRun]:
        return self.session_service.get_review_run(run_id)

    def get_review_diff(self, run_id: str) -> Dict[str, object]:
        return self.session_service.get_review_diff(run_id)

    def get_scan_result(self, run_id: str) -> Optional[ScanResult]:
        return self.session_service.get_scan_result(run_id)

    def get_session_stats(self) -> Dict[str, Any]:
        return self.session_service.get_session_stats()

    def get_dashboard_summary(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        project = self.project_service.analyze_project(project_root) if project_root else None
        return {
            "health": {"status": "healthy"},
            "project_root": project_root,
            "project": project,
            "diff_status": self.project_service.get_diff_status(project_root),
            "session_stats": self.session_service.get_session_stats(),
            "providers": self.config_service.get_model_providers(),
            "scanners": self.project_service.get_scanner_status(project_root),
        }

    # ── Config & Providers (from config_service) ──
    def get_config(self) -> Dict[str, object]:
        return self.config_service.get_config()

    def update_config(self, updates: Dict[str, object], persist: bool = True) -> Dict[str, object]:
        return self.config_service.update_config(updates, persist)

    def get_model_providers(self):
        return self.config_service.get_model_providers()

    def get_tools(self):
        return self.config_service.get_tools()

    # ── Project, Diff & Git (from project_service) ──
    def analyze_project(self, project_root: str) -> ProjectAnalysis:
        return self.project_service.analyze_project(project_root)

    def get_diff_status(self, project_root: Optional[str] = None):
        return self.project_service.get_diff_status(project_root)

    def get_diff_summary(self, project_root: Optional[str] = None, mode: str = "auto") -> Dict[str, Any]:
        return self.project_service.get_diff_summary(project_root, mode)

    def get_diff_files(self, project_root: Optional[str] = None, mode: str = "auto") -> Dict[str, Any]:
        return self.project_service.get_diff_files(project_root, mode)

    def get_file_diff(self, file_path: str, *, project_root: Optional[str] = None, mode: str = "auto", commit_from: Optional[str] = None, commit_to: Optional[str] = None) -> Dict[str, Any]:
        return self.project_service.get_file_diff(file_path, project_root=project_root, mode=mode, commit_from=commit_from, commit_to=commit_to)

    def get_commit_history(self, project_root: str, limit: int = 50) -> Dict[str, Any]:
        return self.project_service.get_commit_history(project_root, limit=limit)

    def get_commit_range_diff(self, *, project_root: str, commit_from: str, commit_to: Optional[str] = None) -> Dict[str, Any]:
        return self.project_service.get_commit_range_diff(project_root=project_root, commit_from=commit_from, commit_to=commit_to)

    def get_scanner_status(self, project_root: Optional[str] = None) -> Dict[str, Any]:
        return self.project_service.get_scanner_status(project_root)

    # ── Rule Growth (from rule_service) ──
    def get_rule_growth_summary(self) -> Dict[str, Any]:
        return self.rule_service.get_rule_growth_summary()

    def get_rule_growth_suggestions(self) -> Dict[str, Any]:
        return self.rule_service.get_rule_growth_suggestions()

    def apply_rule_growth_rule(self, rule_id: str) -> Dict[str, Any]:
        return self.rule_service.apply_rule_growth_rule(rule_id)

    def promote_rule_growth_hint(self, *, language: str, tags: List[str], suggested_context_level: str, sample_count: int = 0, consistency: float = 0.0, conflict_type: str = "") -> Dict[str, Any]:
        return self.rule_service.promote_rule_growth_hint(language=language, tags=tags, suggested_context_level=suggested_context_level, sample_count=sample_count, consistency=consistency, conflict_type=conflict_type)

    def cleanup_rule_growth(self, *, max_age_days: int = 30, clear_session: bool = True) -> Dict[str, Any]:
        return self.rule_service.cleanup_rule_growth(max_age_days=max_age_days, clear_session=clear_session)

    # ── System Info (from system_service) ──
    def get_system_env(self) -> Dict[str, Any]:
        return self.system_service.get_system_env()

    def list_directory(self, path: Optional[str] = None) -> Dict[str, Any]:
        return self.system_service.list_directory(path)
