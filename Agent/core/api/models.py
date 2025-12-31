"""API 数据模型与类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TypedDict, Literal


class LLMOption(TypedDict):
    name: str
    available: bool
    reason: str | None


class ToolOption(TypedDict):
    name: str
    default: bool
    description: str | None


StreamCallback = Callable[[Dict[str, Any]], None]
ToolApprover = Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]


@dataclass
class ReviewRequest:
    """标准化审查请求参数。"""

    prompt: str
    llm_preference: str
    tool_names: List[str]
    auto_approve: bool
    project_root: Optional[str] = None
    stream_callback: Optional[StreamCallback] = None
    tool_approver: Optional[ToolApprover] = None
    planner_llm_preference: Optional[str] = None
    session_id: Optional[str] = None  # 新增：会话 ID
    message_history: Optional[List[Dict[str, Any]]] = None  # 新增：历史消息
    agents: Optional[List[str]] = None  # 新增：指定要运行的 Agent 列表
    enable_static_scan: bool = False  # 是否启用静态分析旁路扫描
    # Diff模式和commit范围支持
    diff_mode: Optional[
        Literal["auto", "working", "staged", "pr", "commit"]
    ] = None  # auto|working|staged|pr|commit
    commit_from: Optional[str] = None  # 历史提交模式的起始commit
    commit_to: Optional[str] = None  # 历史提交模式的结束commit


@dataclass
class ExtraRequest:
    type: str
    details: Optional[str] = None


@dataclass
class PlanItem:
    unit_id: str
    llm_context_level: Optional[str] = None
    extra_requests: Optional[List[ExtraRequest]] = None
    skip_review: bool = False
    reason: Optional[str] = None
