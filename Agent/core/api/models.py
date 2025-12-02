"""API 数据模型与类型定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TypedDict


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
