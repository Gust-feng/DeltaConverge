"""运行时上下文管理（Legacy - 仅用于旧内核兼容）。

警告: 此模块使用全局ContextVar，存在以下问题:
1. 并发审查时可能互相干扰（虽然ContextVar是线程安全的，但cleanup失败会泄漏）
2. 测试时需要手动清理，否则状态污染
3. 隐式依赖，不利于代码理解和维护

新内核应使用 PipelineContext 显式传递这些值，而不是依赖全局状态。
本模块仅保留用于旧ReviewKernel和工具层的兼容。

迁移路径:
- project_root → PipelineContext.project_root
- session_id → PipelineContext.session_id  
- diff_units → PipelineContext.diff_ctx.units
"""

from contextvars import ContextVar
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

_project_root_ctx: ContextVar[Optional[str]] = ContextVar("project_root", default=None)
_session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
_diff_units_ctx: ContextVar[List[Dict[str, Any]]] = ContextVar("diff_units", default=[])

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


@contextmanager
def runtime_context_scope(
    project_root: Optional[str] = None,
    session_id: Optional[str] = None,
    diff_units: Optional[List[Dict[str, Any]]] = None,
) -> Iterator[None]:
    """安全的运行时上下文作用域管理器（修复P1问题: 全局副作用隔离）。
    
    确保即使发生异常或取消，上下文也能正确清理，避免跨请求污染。
    
    用法:
        with runtime_context_scope(project_root="/path", session_id="abc"):
            # 使用全局上下文的代码
            result = some_legacy_function()
        # 自动清理
    
    推荐: 新代码应使用 PipelineContext 显式传递，而不是依赖此上下文管理器。
    """
    # 保存旧值用于恢复（支持嵌套）
    old_project_root = get_project_root()
    old_session_id = get_session_id()
    old_diff_units = get_diff_units()
    
    try:
        # 设置新值
        if project_root is not None:
            set_project_root(project_root)
        if session_id is not None:
            set_session_id(session_id)
        if diff_units is not None:
            set_diff_units(diff_units)
        yield
    finally:
        # 无论如何都恢复旧值，防止泄漏
        set_project_root(old_project_root)
        set_session_id(old_session_id)
        set_diff_units(old_diff_units)

