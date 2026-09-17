from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from adapters.web.dependencies import get_facade
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

router = APIRouter(prefix="/api/v2/projects", tags=["projects"])


@router.get("/analyze")
def analyze_project(project_root: str, facade: KernelFacade = Depends(get_facade)):
    return serialize(facade.analyze_project(project_root))


@router.get("/diff-status")
def diff_status(project_root: str | None = None, facade: KernelFacade = Depends(get_facade)):
    return facade.get_diff_status(project_root)
