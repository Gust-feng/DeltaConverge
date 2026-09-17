from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .executor import LegacyScanCacheSnapshot


def build_scan_artifact_payload(snapshot: LegacyScanCacheSnapshot) -> Dict[str, Any]:
    return {
        "issues_cache": deepcopy(snapshot.issues_cache or {}),
        "linked_cache": deepcopy(snapshot.linked_cache or {}),
    }


def build_linked_payload(snapshot: LegacyScanCacheSnapshot) -> Dict[str, Any]:
    return deepcopy(snapshot.linked_cache or {})
