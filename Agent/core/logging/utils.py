"""Logging 辅助方法：时间戳与安全截断。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Set


def utc_iso(dt: datetime | None = None) -> str:
    """返回 UTC ISO8601 字符串，便于跨时区排序。"""

    return (dt or datetime.now(timezone.utc)).isoformat()


def _is_primitive(value: Any) -> bool:
    return value is None or isinstance(value, (int, float, bool))


def _truncate_str(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    head = value[: max_chars - 20]
    return f"{head}...(truncated {len(value) - max_chars + 20} chars)"


def safe_payload(
    data: Any,
    *,
    max_chars: int = 2000,
    max_items: int = 50,
    redacted_keys: Iterable[str] | None = None,
    _depth: int = 0,
) -> Any:
    """递归截断过长字段，避免日志爆炸。

    - 字符串：超过 max_chars 则截断并标记。
    - 列表/元组：超过 max_items 仅保留前 max_items 项并追加提示。
    - 字典：深度复制，命中 redacted_keys 的键将被替换为占位提示。
    - 其他：原样返回。
    """

    if _is_primitive(data):
        return data
    redacted: Set[str] = set(redacted_keys or [])

    if isinstance(data, str):
        return _truncate_str(data, max_chars)

    if isinstance(data, (list, tuple)):
        items = list(data)
        if len(items) > max_items:
            trimmed = items[:max_items]
            trimmed.append(f"...(truncated {len(items) - max_items} items)")
            return [
                safe_payload(
                    v,
                    max_chars=max_chars,
                    max_items=max_items,
                    redacted_keys=redacted,
                    _depth=_depth + 1,
                )
                for v in trimmed
            ]
        return [
            safe_payload(
                v,
                max_chars=max_chars,
                max_items=max_items,
                redacted_keys=redacted,
                _depth=_depth + 1,
            )
            for v in items
        ]

    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in data.items():
            key_str = str(k)
            if key_str in redacted:
                sanitized[key_str] = "(redacted)"
                continue
            sanitized[key_str] = safe_payload(
                v,
                max_chars=max_chars,
                max_items=max_items,
                redacted_keys=redacted,
                _depth=_depth + 1,
            )
        return sanitized

    # 其余类型：尽量转成字符串再截断，保持日志可序列化
    return _truncate_str(str(data), max_chars)


__all__ = ["utc_iso", "safe_payload"]
