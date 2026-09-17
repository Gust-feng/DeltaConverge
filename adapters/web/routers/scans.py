from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from adapters.web.dependencies import get_facade
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

router = APIRouter(prefix="/api/v2/scans", tags=["scans"])


@router.get("/{run_id}")
def get_scan_result(run_id: str, facade: KernelFacade = Depends(get_facade)):
    if not facade.get_review_run(run_id):
        raise HTTPException(status_code=404, detail="run_not_found")
    result = facade.get_scan_result(run_id)
    if not result:
        return {"run_id": run_id, "status": "pending"}
    return serialize(result)
