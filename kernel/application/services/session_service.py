"""会话管理服务。"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional

from kernel.domain.models import ReviewRun, ScanResult, SessionDetail, SessionSummary
from kernel.ports.scan import ReviewReportLinkerPort
from kernel.ports.stores import ArtifactStore, SessionStore

logger = logging.getLogger(__name__)

_SCAN_SEVERITIES = ("error", "warning", "info")


class SessionService:
    def __init__(
        self,
        store: SessionStore,
        artifact_store: ArtifactStore,
        report_linker: Optional[ReviewReportLinkerPort] = None,
    ) -> None:
        self.store = store
        self.artifact_store = artifact_store
        if report_linker is None:
            from kernel.infrastructure.scan.linker import LegacyReviewReportLinker
            report_linker = LegacyReviewReportLinker()
        self.report_linker = report_linker

    def create_session(
        self,
        *,
        session_id: Optional[str] = None,
        name: Optional[str] = None,
        project_root: Optional[str] = None,
    ) -> SessionSummary:
        """Create a session, or return the existing one for an identical id."""
        target_id = (session_id or "").strip() or f"sess_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        return self.store.ensure_session(session_id=target_id, name=name, project_root=project_root)

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Lightweight completion status used by the legacy 3s polling UI."""
        summary = self.store.get_session_summary(session_id)
        if not summary:
            return None
        latest_run = self.store.get_run(summary.latest_run_id) if summary.latest_run_id else None
        status = summary.status or "active"
        completed = status == "completed" or bool(latest_run and latest_run.status == "completed")
        return {"completed": completed, "status": status}

    def get_scan_issues_page(
        self,
        run_id: str,
        *,
        severity: str = "error",
        offset: int = 0,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return one severity's issues, sliced for the legacy paged endpoint."""
        if not self.store.get_run(run_id):
            raise LookupError("run_not_found")
        scan_result = self.store.get_scan_result(run_id)
        if not scan_result:
            raise LookupError("scan_result_not_found")

        normalized = severity if severity in _SCAN_SEVERITIES else "error"
        issues = list(scan_result.issues_by_severity.get(normalized) or [])
        safe_offset = max(0, int(offset))
        safe_limit = max(1, min(200, int(limit)))
        total = len(issues)
        page = issues[safe_offset : safe_offset + safe_limit]
        return {
            "run_id": run_id,
            "session_id": scan_result.session_id,
            "severity": normalized,
            "offset": safe_offset,
            "limit": safe_limit,
            "total": total,
            "has_more": safe_offset + len(page) < total,
            "issues": page,
        }

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
        result = self.store.get_scan_result(run_id)
        run = self.store.get_run(run_id)
        if not run or not run.final_report_artifact_id:
            return result
        report_artifact = self.store.get_artifact(run.final_report_artifact_id)
        if not report_artifact:
            return result

        try:
            report = self.artifact_store.read_text(report_artifact)
            if not report.strip():
                return result
            linked = dict(result.linked) if result else {}
            snapshot = self.get_review_diff(run_id)
            units = snapshot.get("diff_units") or linked.get("diff_units") or []
            linked.update(self.report_linker.link_report(report, units))
            linked["diff_units"] = units
            linked.setdefault("unit_issues", {})
            if result:
                return replace(result, linked=linked)
            # AI 问题与静态扫描独立；关闭扫描的会话也应显示报告解析。
            return ScanResult(
                run_id=run.id,
                session_id=run.session_id,
                summary={},
                issues_by_severity={},
                linked=linked,
                created_at=run.updated_at,
            )
        except Exception:
            logger.exception("关联 AI 审查报告失败 (run_id=%s)", run_id)
            return result

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
