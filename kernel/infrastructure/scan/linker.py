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


class LegacyReviewReportLinker:
    def link_report(self, report: str, units: list[Dict[str, Any]]) -> Dict[str, Any]:
        from Agent.DIFF.static_scan_service import (
            build_linked_unit_llm_suggestions,
            parse_review_report_issues,
        )

        suggestions = parse_review_report_issues(report)
        return build_linked_unit_llm_suggestions(units, suggestions)
