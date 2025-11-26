"""上下文提供者：选择用于审查的文件或片段。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from Agent.core.logging.fallback_tracker import (
    read_text_with_fallback,
    record_fallback,
)


class ContextProvider:
    """加载上下文片段（如 diff 中挑选的文件）。"""

    def __init__(self, max_bytes: int = 16_000) -> None:
        self.max_bytes = max_bytes

    def load_context(self, files: List[str]) -> Dict[str, str]:
        """返回 file_path -> 片段 的映射，受 max_bytes 限制。"""

        context: Dict[str, str] = {}
        budget = self.max_bytes
        for file_path in files:
            path = Path(file_path)
            if not path.exists() or budget <= 0:
                continue
            try:
                text = read_text_with_fallback(
                    path, reason="context_provider_load"
                )
            except Exception as exc:
                record_fallback(
                    "context_provider_read_failed",
                    "上下文文件读取失败，跳过",
                    meta={"path": file_path, "error": str(exc)},
                )
                continue
            snippet = text[: min(len(text), budget)]
            context[file_path] = snippet
            budget -= len(snippet)
            if budget <= 0:
                break
        return context
