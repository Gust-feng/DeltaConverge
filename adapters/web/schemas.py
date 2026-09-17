from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReviewCreatePayload(BaseModel):
    prompt: str = ""
    model: str = "auto"
    tools: List[str] = Field(default_factory=list)
    auto_approve: bool = False
    project_root: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    agents: List[str] = Field(default_factory=list)
    enable_static_scan: bool = False
    diff_mode: Optional[str] = None
    commit_from: Optional[str] = None
    commit_to: Optional[str] = None
    planner_model: Optional[str] = None


class QARequestPayload(BaseModel):
    question: str
    model: str = "auto"
    project_root: Optional[str] = None


class SessionUpdatePayload(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None


class ConfigUpdatePayload(BaseModel):
    updates: Dict[str, Any]
    persist: bool = True


class DirectoryListPayload(BaseModel):
    path: Optional[str] = None


class CommitHistoryQuery(BaseModel):
    project_root: str
    limit: int = 50


class CommitRangeQuery(BaseModel):
    project_root: str
    commit_from: str
    commit_to: Optional[str] = None


class RuleApplyPayload(BaseModel):
    rule_id: str


class RulePromotePayload(BaseModel):
    language: str
    tags: List[str] = Field(default_factory=list)
    suggested_context_level: str
    sample_count: int = 0
    consistency: float = 0.0
    conflict_type: str = ""


class RuleCleanupPayload(BaseModel):
    max_age_days: int = 30
    clear_session: bool = True
