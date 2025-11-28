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
from typing import Any, Callable, Dict, List, Optional


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
        priority: str = "warning",  # critical, warning, info
        category: str = "general",
        request_id: Optional[str] = None,
        sampling_rate: float = 1.0,
    ) -> None:
        """记录一次回退，并保留少量示例便于排查。"""
        import time
        import traceback
        import random

        # 采样逻辑
        if sampling_rate < 1.0 and random.random() > sampling_rate:
            return

        with self._lock:
            self._counts[key] += 1
            bucket = self._samples[key]
            if len(bucket) < sample_limit:
                entry = {
                    "message": message,
                    "timestamp": time.time(),
                    "priority": priority,
                    "category": category,
                    "call_stack": traceback.format_stack()[-10:],  # 保留最近10层调用栈
                }
                if request_id:
                    entry["request_id"] = request_id
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
            # 按优先级统计
            priority_counts = defaultdict(int)
            # 按分类统计
            category_counts = defaultdict(int)
            # 按优先级和分类统计
            priority_category_counts = defaultdict(lambda: defaultdict(int))
            
            # 遍历所有样本，统计优先级和分类
            for key, samples in self._samples.items():
                for sample in samples:
                    priority = sample.get("priority", "warning")
                    category = sample.get("category", "general")
                    priority_counts[priority] += 1
                    category_counts[category] += 1
                    priority_category_counts[priority][category] += 1
            
            return {
                "total": sum(self._counts.values()),
                "by_key": dict(self._counts),
                "samples": {k: v[:] for k, v in self._samples.items() if v},
                "by_priority": dict(priority_counts),
                "by_category": dict(category_counts),
                "by_priority_category": {k: dict(v) for k, v in priority_category_counts.items()},
            }

    def emit_summary(
        self,
        *,
        logger: Any | None = None,
        pipeline_logger: Any | None = None,
        status: str = "warn",
        log_file: Optional[str] = None,
        thresholds: Optional[Dict[str, int]] = None,
        alert_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """输出汇总到日志/流水线，并重置计数。"""
        import json
        import time

        summary = self.summary()
        if summary.get("total", 0) == 0:
            return summary

        # 检查告警阈值
        alerts_triggered = []
        if thresholds:
            for priority, threshold in thresholds.items():
                priority_count = summary.get("by_priority", {}).get(priority, 0)
                if priority_count >= threshold:
                    alerts_triggered.append({
                        "priority": priority,
                        "count": priority_count,
                        "threshold": threshold
                    })
        
        # 记录到日志文件
        if log_file:
            try:
                log_entry = {
                    "timestamp": time.time(),
                    "summary": summary,
                    "alerts_triggered": alerts_triggered,
                }
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            except Exception as e:
                if logger:
                    logger.exception(f"Failed to write fallback log to {log_file}: {e}")

        # 输出到日志
        if logger:
            try:
                logger.warning("fallback triggered: %s, by_priority: %s, by_category: %s", 
                              summary["by_key"], summary.get("by_priority"), summary.get("by_category"))
                if alerts_triggered:
                    logger.warning("fallback alerts triggered: %s", alerts_triggered)
            except Exception:
                pass

        # 输出到流水线日志
        if pipeline_logger:
            try:
                pipeline_logger.log("fallback_summary", summary, status=status)
                if alerts_triggered:
                    pipeline_logger.log("fallback_alerts", {"alerts": alerts_triggered}, status="error")
            except Exception:
                if logger:
                    logger.exception("failed to log fallback summary")
        
        # 调用告警回调
        if alert_callback and alerts_triggered:
            try:
                alert_callback({
                    "summary": summary,
                    "alerts": alerts_triggered
                })
            except Exception as e:
                if logger:
                    logger.exception(f"Failed to execute alert callback: {e}")

        self.reset()
        return summary


fallback_tracker = FallbackTracker()


def record_fallback(
    key: str, 
    message: str, 
    meta: Optional[Dict[str, Any]] = None,
    priority: str = "warning",
    category: str = "general",
    request_id: Optional[str] = None,
    sampling_rate: float = 1.0,
) -> None:
    """便捷方法，避免各处重复获取单例。"""

    fallback_tracker.record(
        key, 
        message, 
        meta=meta,
        priority=priority,
        category=category,
        request_id=request_id,
        sampling_rate=sampling_rate,
    )


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
