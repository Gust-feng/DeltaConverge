"""用于多阶段规划/审查的流水线日志器。"""

from __future__ import annotations

import json
from uuid import uuid4
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Set

from Agent.core.logging.utils import safe_payload, utc_iso


class PipelineLogger:
    """轻量 JSONL 日志器，用于跟踪规划→融合→上下文→审查。"""

    def __init__(
        self,
        root: str | Path = "log/pipeline",
        trace_id: str | None = None,
        *,
        max_chars: int = 4000,
        max_items: int = 50,
        redacted_keys: Iterable[str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_path: Path | None = None
        self.trace_id = trace_id or uuid4().hex[:12]
        self.started_at: datetime | None = None
        self.max_chars = max_chars
        self.max_items = max_items
        self.redacted_keys: Set[str] = set(
            redacted_keys
            or {
                "messages",
                "tools",
                "unified_diff",
                "unified_diff_with_lines",
                "context",
                "code_snippets",
                "file_context",
                "full_file",
                "function_context",
            }
        )

    def start(self, name: str, meta: Dict[str, Any] | None = None) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.started_at = datetime.now(timezone.utc)
        self.session_path = self.root / f"{ts}_{name}_{self.trace_id}.jsonl"
        self._write(
            {
                "event": "session_start",
                "stage": name,
                "status": "start",
                "meta": safe_payload(
                    meta or {},
                    max_chars=self.max_chars,
                    max_items=self.max_items,
                    redacted_keys=self.redacted_keys,
                ),
                "ts": utc_iso(self.started_at),
            }
        )
        return self.session_path

    def log(self, stage: str, payload: Dict[str, Any] | None = None, status: str = "info") -> None:
        """记录阶段事件，自动补充 trace_id/时间戳/运行时长。"""

        self._write(
            {
                "event": stage,
                "stage": stage,
                "status": status,
                "payload": safe_payload(
                    payload or {},
                    max_chars=self.max_chars,
                    max_items=self.max_items,
                    redacted_keys=self.redacted_keys,
                ),
            }
        )

    def _write(self, obj: Dict[str, Any]) -> None:
        if self.session_path is None:
            raise RuntimeError("PipelineLogger session not started")
        now = datetime.now(timezone.utc)
        obj.setdefault("ts", utc_iso(now))
        obj.setdefault("trace_id", self.trace_id)
        if self.started_at:
            delta = now - self.started_at
            obj.setdefault("uptime_ms", int(delta.total_seconds() * 1000))
        with self.session_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


__all__ = ["PipelineLogger"]
