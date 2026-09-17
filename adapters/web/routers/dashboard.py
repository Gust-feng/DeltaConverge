from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from adapters.web.dependencies import get_facade
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade


router = APIRouter(prefix="/api/v2/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary(project_root: str | None = None, facade: KernelFacade = Depends(get_facade)):
    return serialize(facade.get_dashboard_summary(project_root))
