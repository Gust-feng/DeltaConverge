from __future__ import annotations

from typing import Any


class LegacyScanServiceAdapter:
    """Adapter that wraps the legacy Agent.DIFF.static_scan_service globals
    behind the ScanServicePort protocol, isolating the kernel from global
    module imports."""

    def get_scan_snapshot(self, session_id: str) -> Any:
        from copy import deepcopy

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

        class _Snapshot:
            def __init__(self) -> None:
                self.issues_cache = issues_cache
                self.linked_cache = linked_cache

            @property
            def has_data(self) -> bool:
                return bool(self.issues_cache or self.linked_cache)

        return _Snapshot()

    async def wait_scan_complete(self, session_id: str, timeout: float) -> bool:
        from Agent.DIFF.static_scan_service import wait_scan_complete

        return await wait_scan_complete(session_id, timeout=float(timeout))

    def is_scan_complete(self, session_id: str) -> bool:
        from Agent.DIFF.static_scan_service import is_scan_complete as _is_scan_complete

        return _is_scan_complete(session_id)
