from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
TERMINAL_SESSION_STATUSES = {"completed", "failed", "archived"}


@dataclass(slots=True)
class ArtifactRef:
    id: str
    kind: str
    session_id: str
    run_id: Optional[str]
    rel_path: str
    mime_type: str
    size_bytes: int
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionSummary:
    id: str
    name: str
    project_root: Optional[str]
    status: str
    created_at: str
    updated_at: str
    tags: List[str] = field(default_factory=list)
    latest_run_id: Optional[str] = None
    last_error: Optional[str] = None


@dataclass(slots=True)
class ReviewRun:
    id: str
    session_id: str
    prompt: str
    model: str
    status: str
    created_at: str
    updated_at: str
    enable_static_scan: bool = False
    diff_mode: Optional[str] = None
    commit_from: Optional[str] = None
    commit_to: Optional[str] = None
    error_message: Optional[str] = None
    final_report_artifact_id: Optional[str] = None


@dataclass(slots=True)
class SessionDetail:
    summary: SessionSummary
    latest_run: Optional[ReviewRun]
    artifacts: List[ArtifactRef] = field(default_factory=list)
    latest_report_artifact_id: Optional[str] = None


@dataclass(slots=True)
class MessageRecord:
    id: Optional[int]
    session_id: str
    role: str
    content: str
    created_at: str
    run_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowEvent:
    id: Optional[int]
    run_id: str
    session_id: str
    seq: int
    type: str
    created_at: str
    stage: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScanResult:
    run_id: str
    session_id: str
    summary: Dict[str, Any]
    issues_by_severity: Dict[str, List[Dict[str, Any]]]
    linked: Dict[str, Any]
    created_at: str
    artifact_id: Optional[str] = None


@dataclass(slots=True)
class ProjectAnalysis:
    info: Dict[str, Any]
    tree: Dict[str, Any]
    readme: Dict[str, Any]
    dependencies: Dict[str, Any]
    git: Dict[str, Any]


@dataclass(slots=True)
class ReviewCreateRequest:
    prompt: str
    model: str = "auto"
    tools: List[str] = field(default_factory=list)
    auto_approve: bool = False
    project_root: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    agents: List[str] = field(default_factory=list)
    enable_static_scan: bool = False
    diff_mode: Optional[str] = None
    commit_from: Optional[str] = None
    commit_to: Optional[str] = None
    planner_model: Optional[str] = None


@dataclass(slots=True)
class QARequest:
    run_id: str
    question: str
    model: str = "auto"
    project_root: Optional[str] = None


@dataclass(slots=True)
class QAResponse:
    run_id: str
    session_id: str
    answer: str
    message: MessageRecord


@dataclass(slots=True)
class LegacyImportResult:
    session: SessionSummary
    run: Optional[ReviewRun]
    imported_messages: int
    imported_events: int
    imported_artifacts: int
