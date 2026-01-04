from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

_project_root_ctx: ContextVar[Optional[str]] = ContextVar("project_root", default=None)
_session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
_diff_units_ctx: ContextVar[List[Dict[str, Any]]] = ContextVar("diff_units", default=[])
_commit_range_ctx: ContextVar[Tuple[Optional[str], Optional[str]]] = ContextVar("commit_range", default=(None, None))

def set_project_root(path: Optional[str]) -> None:
    _project_root_ctx.set(path)

def get_project_root() -> Optional[str]:
    return _project_root_ctx.get()

def set_session_id(session_id: Optional[str]) -> None:
    """设置当前会话ID，供工具获取扫描结果时使用。"""
    _session_id_ctx.set(session_id)

def get_session_id() -> Optional[str]:
    """获取当前会话ID。"""
    return _session_id_ctx.get()

def set_diff_units(units: List[Dict[str, Any]]) -> None:
    """设置当前审查的 diff units，供工具进行问题过滤时使用。"""
    _diff_units_ctx.set(units or [])

def get_diff_units() -> List[Dict[str, Any]]:
    """获取当前审查的 diff units。"""
    return _diff_units_ctx.get() or []

def set_commit_range(commit_from: Optional[str], commit_to: Optional[str]) -> None:
    """设置当前审查的 commit 范围，供工具从 Git 历史读取文件时使用。"""
    _commit_range_ctx.set((commit_from, commit_to))

def get_commit_range() -> Tuple[Optional[str], Optional[str]]:
    """获取当前审查的 commit 范围 (commit_from, commit_to)。"""
    return _commit_range_ctx.get() or (None, None)
