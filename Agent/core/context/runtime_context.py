from contextvars import ContextVar
from typing import Optional

_project_root_ctx: ContextVar[Optional[str]] = ContextVar("project_root", default=None)

def set_project_root(path: Optional[str]) -> None:
    _project_root_ctx.set(path)

def get_project_root() -> Optional[str]:
    return _project_root_ctx.get()
