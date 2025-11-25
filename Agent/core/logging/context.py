"""日志上下文辅助方法（trace/session ID）。"""

from __future__ import annotations

import uuid


def generate_trace_id() -> str:
    """生成用于关联日志的简短、可安全嵌入 URL 的 trace id。"""

    return uuid.uuid4().hex[:12]


__all__ = ["generate_trace_id"]
