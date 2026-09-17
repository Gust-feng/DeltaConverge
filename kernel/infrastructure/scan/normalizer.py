from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from kernel.domain.models import ScanResult
from kernel.infrastructure.persistence import utc_now

from .executor import LegacyScanCacheSnapshot


def build_scan_summary(snapshot: LegacyScanCacheSnapshot) -> Dict[str, Any]:
    issues_cache = snapshot.issues_cache or {}
    return {
        "files_total": issues_cache.get("files_total"),
        "files_scanned": issues_cache.get("files_scanned"),
        "duration_ms": issues_cache.get("duration_ms"),
        "scanners_used": list(issues_cache.get("scanners_used", []) or []),
    }


def build_issues_by_severity(snapshot: LegacyScanCacheSnapshot) -> Dict[str, List[Dict[str, Any]]]:
    issues_cache = snapshot.issues_cache or {}
    issues_by_severity = issues_cache.get("issues_by_severity") or {}
    return {
        "error": list(issues_by_severity.get("error") or []),
        "warning": list(issues_by_severity.get("warning") or []),
        "info": list(issues_by_severity.get("info") or []),
    }


def build_scan_result(
    run_id: str,
    session_id: str,
    snapshot: LegacyScanCacheSnapshot,
    *,
    created_at: Optional[str] = None,
    artifact_id: Optional[str] = None,
) -> ScanResult:
    return ScanResult(
        run_id=run_id,
        session_id=session_id,
        summary=build_scan_summary(snapshot),
        issues_by_severity=build_issues_by_severity(snapshot),
        linked=deepcopy(snapshot.linked_cache or {}),
        created_at=created_at or utc_now(),
        artifact_id=artifact_id,
    )
