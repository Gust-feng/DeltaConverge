from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from kernel.ports.stores import ScanServicePort


@dataclass(slots=True)
class LegacyScanCacheSnapshot:
    issues_cache: Dict[str, Any] = field(default_factory=dict)
    linked_cache: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return bool(self.issues_cache or self.linked_cache)


def read_legacy_scan_cache(
    session_id: str,
    scan_service: Optional[ScanServicePort] = None,
) -> LegacyScanCacheSnapshot:
    if not session_id:
        return LegacyScanCacheSnapshot()

    if scan_service is not None:
        snapshot = scan_service.get_scan_snapshot(session_id)
        return LegacyScanCacheSnapshot(
            issues_cache=getattr(snapshot, "issues_cache", {}),
            linked_cache=getattr(snapshot, "linked_cache", {}),
        )

    from Agent.DIFF.static_scan_service import (
        _STATIC_SCAN_ISSUES_CACHE,
        _STATIC_SCAN_ISSUES_CACHE_LOCK,
        _STATIC_SCAN_LINKED_CACHE,
        _STATIC_SCAN_LINKED_CACHE_LOCK,
    )

    with _STATIC_SCAN_ISSUES_CACHE_LOCK:
        issues_cache = deepcopy(_STATIC_SCAN_ISSUES_CACHE.get(session_id) or {})
    with _STATIC_SCAN_LINKED_CACHE_LOCK:
        linked_cache = deepcopy(_STATIC_SCAN_LINKED_CACHE.get(session_id) or {})
    return LegacyScanCacheSnapshot(issues_cache=issues_cache, linked_cache=linked_cache)


async def wait_for_scan_completion(
    session_id: str,
    timeout: float = 60.0,
    scan_service: Optional[ScanServicePort] = None,
) -> bool:
    if not session_id:
        return False

    if scan_service is not None:
        return await scan_service.wait_scan_complete(session_id, timeout=float(timeout))

    from Agent.DIFF.static_scan_service import wait_scan_complete

    return await wait_scan_complete(session_id, timeout=float(timeout))


def is_scan_complete(
    session_id: str,
    scan_service: Optional[ScanServicePort] = None,
) -> bool:
    if not session_id:
        return False

    if scan_service is not None:
        return scan_service.is_scan_complete(session_id)

    from Agent.DIFF.static_scan_service import is_scan_complete as _is_scan_complete

    return _is_scan_complete(session_id)
