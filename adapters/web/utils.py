from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {key: serialize(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): serialize(val) for key, val in value.items()}
    if isinstance(value, list):
        return [serialize(item) for item in value]
    return value
