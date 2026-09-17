"""会话管理服务。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from kernel.domain.models import ReviewRun, ScanResult, SessionDetail, SessionSummary
from kernel.ports.stores import ArtifactStore, SessionStore


class SessionService:
    def __init__(self, store: SessionStore, artifact_store: ArtifactStore) -> None:
        self.store = store
        self.artifact_store = artifact_store

    def list_sessions(self, *, status: Optional[str] = None, project_root: Optional[str] = None, limit: int = 50, offset: int = 0) -> List[SessionSummary]:
        return self.store.list_sessions(status=status, project_root=project_root, limit=limit, offset=offset)

    def get_session_summary(self, session_id: str) -> Optional[SessionSummary]:
        return self.store.get_session_summary(session_id)

    def get_session_detail(self, session_id: str) -> Optional[SessionDetail]:
        return self.store.get_session_detail(session_id)

    def get_session_messages(self, session_id: str, *, limit: int = 200, offset: int = 0):
        return self.store.list_messages(session_id, limit=limit, offset=offset)

    def get_session_events(self, run_id: str, *, limit: Optional[int] = None, offset: int = 0):
        return self.store.list_events(run_id, limit=limit, offset=offset)

    def update_session(self, session_id: str, *, name: Optional[str] = None, status: Optional[str] = None, tags: Optional[List[str]] = None) -> Optional[SessionSummary]:
        return self.store.update_session(session_id, name=name, status=status, tags=tags)

    def delete_session(self, session_id: str) -> None:
        self.store.delete_session(session_id)

    def get_review_run(self, run_id: str) -> Optional[ReviewRun]:
        return self.store.get_run(run_id)

    def get_review_diff(self, run_id: str) -> Dict[str, object]:
        run = self.store.get_run(run_id)
        if not run:
            return {}
        artifacts = self.store.list_artifacts(session_id=run.session_id, run_id=run.id)
        for artifact in artifacts:
            if artifact.kind == "review_diff_snapshot":
                return self.artifact_store.read_json(artifact)
        return {}

    def get_scan_result(self, run_id: str) -> Optional[ScanResult]:
        return self.store.get_scan_result(run_id)

    def get_session_stats(self) -> Dict[str, Any]:
        sessions = self.store.list_sessions(limit=10_000, offset=0)
        by_status: Dict[str, int] = {}
        by_project: Dict[str, int] = {}
        total_messages = 0

        for session in sessions:
            by_status[session.status] = by_status.get(session.status, 0) + 1
            project_key = session.project_root or "unknown"
            by_project[project_key] = by_project.get(project_key, 0) + 1
            total_messages += len(self.store.list_messages(session.id, limit=10_000, offset=0))

        return {
            "total_sessions": len(sessions),
            "by_status": by_status,
            "by_project": by_project,
            "total_messages": total_messages,
        }
