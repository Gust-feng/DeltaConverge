"""Pipeline logger for multi-stage planning/review."""

from __future__ import annotations

import json
from uuid import uuid4
from pathlib import Path
from datetime import datetime
from typing import Any, Dict


class PipelineLogger:
    """Lightweight JSONL logger to trace planning→fusion→context→review."""

    def __init__(self, root: str | Path = "log/pipeline", trace_id: str | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_path: Path | None = None
        self.trace_id = trace_id or uuid4().hex[:12]

    def start(self, name: str, meta: Dict[str, Any] | None = None) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_path = self.root / f"{ts}_{name}.jsonl"
        self._write({"stage": "session_start", "meta": meta or {}, "timestamp": ts, "trace_id": self.trace_id})
        return self.session_path

    def log(self, stage: str, payload: Dict[str, Any]) -> None:
        self._write({"stage": stage, "payload": payload})

    def _write(self, obj: Dict[str, Any]) -> None:
        if self.session_path is None:
            raise RuntimeError("PipelineLogger session not started")
        obj.setdefault("timestamp", datetime.now().isoformat())
        obj.setdefault("trace_id", self.trace_id)
        with self.session_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


__all__ = ["PipelineLogger"]
