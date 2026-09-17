from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from kernel.domain.models import (
    ArtifactRef,
    MessageRecord,
    ReviewRun,
    ScanResult,
    SessionDetail,
    SessionSummary,
    WorkflowEvent,
)


class ArtifactStore(Protocol):
    def save_text(
        self,
        *,
        session_id: str,
        run_id: Optional[str],
        kind: str,
        content: str,
        extension: str,
        mime_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRef: ...

    def save_json(
        self,
        *,
        session_id: str,
        run_id: Optional[str],
        kind: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRef: ...

    def read_text(self, artifact: ArtifactRef) -> str: ...

    def read_json(self, artifact: ArtifactRef) -> Dict[str, Any]: ...


class SessionStore(Protocol):
    def create_session(
        self,
        *,
        session_id: str,
        name: Optional[str],
        project_root: Optional[str],
        tags: Optional[List[str]] = None,
        status: str = "active",
    ) -> SessionSummary: ...

    def ensure_session(
        self,
        *,
        session_id: str,
        name: Optional[str],
        project_root: Optional[str],
    ) -> SessionSummary: ...

    def get_session_summary(self, session_id: str) -> Optional[SessionSummary]: ...

    def get_session_detail(self, session_id: str) -> Optional[SessionDetail]: ...

    def list_sessions(
        self,
        *,
        status: Optional[str] = None,
        project_root: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SessionSummary]: ...

    def update_session(
        self,
        session_id: str,
        *,
        name: Optional[str] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
        last_error: Optional[str] = None,
        latest_run_id: Optional[str] = None,
    ) -> Optional[SessionSummary]: ...

    def delete_session(self, session_id: str) -> None: ...

    def create_run(
        self,
        *,
        run_id: str,
        session_id: str,
        prompt: str,
        model: str,
        enable_static_scan: bool,
        diff_mode: Optional[str],
        commit_from: Optional[str],
        commit_to: Optional[str],
    ) -> ReviewRun: ...

    def get_run(self, run_id: str) -> Optional[ReviewRun]: ...

    def update_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
        final_report_artifact_id: Optional[str] = None,
    ) -> Optional[ReviewRun]: ...

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageRecord: ...

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MessageRecord]: ...

    def append_event(
        self,
        *,
        run_id: str,
        session_id: str,
        event_type: str,
        stage: Optional[str],
        payload: Dict[str, Any],
    ) -> WorkflowEvent: ...

    def list_events(
        self,
        run_id: str,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[WorkflowEvent]: ...

    def register_artifact(self, artifact: ArtifactRef) -> ArtifactRef: ...

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactRef]: ...

    def list_artifacts(
        self,
        *,
        session_id: str,
        run_id: Optional[str] = None,
    ) -> List[ArtifactRef]: ...

    def upsert_scan_result(self, result: ScanResult) -> ScanResult: ...

    def get_scan_result(self, run_id: str) -> Optional[ScanResult]: ...


class ScanServicePort(Protocol):
    def get_scan_snapshot(self, session_id: str) -> Any: ...
    async def wait_scan_complete(self, session_id: str, timeout: float) -> bool: ...
    def is_scan_complete(self, session_id: str) -> bool: ...
