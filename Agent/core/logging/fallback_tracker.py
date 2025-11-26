"""统一的回退计数与示警工具。

用途：
- 在代码路径发生降级/兜底时调用 record_fallback；
- 运行结束时通过 emit_summary 将计数写入日志/流水线；
- 提供 read_text_with_fallback 以便捕获编码降级。
"""

from __future__ import annotations

import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


class FallbackTracker:
    """线程安全的回退计数器，聚合示警。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._samples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    def record(
        self,
        key: str,
        message: str,
        *,
        meta: Optional[Dict[str, Any]] = None,
        sample_limit: int = 5,
    ) -> None:
        """记录一次回退，并保留少量示例便于排查。"""

        with self._lock:
            self._counts[key] += 1
            bucket = self._samples[key]
            if len(bucket) < sample_limit:
                entry = {"message": message}
                if meta:
                    entry["meta"] = meta
                bucket.append(entry)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()
            self._samples.clear()

    def summary(self) -> Dict[str, Any]:
        """返回当前累计的汇总数据（不会清空计数）。"""

        with self._lock:
            return {
                "total": sum(self._counts.values()),
                "by_key": dict(self._counts),
                "samples": {k: v[:] for k, v in self._samples.items() if v},
            }

    def emit_summary(
        self,
        *,
        logger: Any | None = None,
        pipeline_logger: Any | None = None,
        status: str = "warn",
    ) -> Dict[str, Any]:
        """输出汇总到日志/流水线，并重置计数。"""

        summary = self.summary()
        if summary.get("total", 0) == 0:
            return summary

        if logger:
            try:
                logger.warning("fallback triggered: %s", summary["by_key"])
            except Exception:
                pass

        if pipeline_logger:
            try:
                pipeline_logger.log("fallback_summary", summary, status=status)
            except Exception:
                if logger:
                    logger.exception("failed to log fallback summary")

        self.reset()
        return summary


fallback_tracker = FallbackTracker()


def record_fallback(key: str, message: str, meta: Optional[Dict[str, Any]] = None) -> None:
    """便捷方法，避免各处重复获取单例。"""

    fallback_tracker.record(key, message, meta=meta)


def read_text_with_fallback(
    path: Path,
    *,
    encoding: str = "utf-8",
    tracker_key: str = "io_decode_fallback",
    reason: str | None = None,
) -> str:
    """优先严格解码，失败时降级 errors='ignore' 并记录回退。"""

    try:
        return path.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        record_fallback(
            tracker_key,
            reason or "decode_error",
            meta={"path": str(path), "error": exc.__class__.__name__},
        )
        return path.read_text(encoding=encoding, errors="ignore")


__all__ = [
    "FallbackTracker",
    "fallback_tracker",
    "record_fallback",
    "read_text_with_fallback",
]
