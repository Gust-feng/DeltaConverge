from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from adapters.web.dependencies import get_facade
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

router = APIRouter(prefix="/api/v2/scans", tags=["scans"])


def _with_issue_counts(payload: dict) -> dict:
    """Supplement the persisted summary with per-severity counts.

    ``build_scan_summary`` lives in the infrastructure scan normalizer, which is
    outside this change's ownership, so the counts are added at the adapter edge.
    """
    issues_by_severity = payload.get("issues_by_severity") or {}
    counts = {
        severity: len(issues_by_severity.get(severity) or [])
        for severity in ("error", "warning", "info")
    }
    summary = dict(payload.get("summary") or {})
    summary.update(
        {
            "total_issues": sum(counts.values()),
            "error_count": counts["error"],
            "warning_count": counts["warning"],
            "info_count": counts["info"],
        }
    )
    payload["summary"] = summary
    return payload


@router.get("/{run_id}/issues")
def get_scan_issues(
    run_id: str,
    severity: str = "error",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    facade: KernelFacade = Depends(get_facade),
):
    try:
        return facade.get_scan_issues_page(run_id, severity=severity, offset=offset, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{run_id}")
def get_scan_result(run_id: str, facade: KernelFacade = Depends(get_facade)):
    if not facade.get_review_run(run_id):
        raise HTTPException(status_code=404, detail="run_not_found")
    result = facade.get_scan_result(run_id)
    if not result:
        return {"run_id": run_id, "status": "pending"}
    return _with_issue_counts(serialize(result))
