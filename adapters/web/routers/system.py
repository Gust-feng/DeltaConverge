from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from adapters.web.dependencies import get_facade
from adapters.web.schemas import DirectoryListPayload
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade


router = APIRouter(prefix="/api/v2/system", tags=["system"])


@router.get("/env")
def get_system_env(facade: KernelFacade = Depends(get_facade)):
    return serialize(facade.get_system_env())


@router.post("/list-directory")
def list_directory(payload: DirectoryListPayload, facade: KernelFacade = Depends(get_facade)):
    return serialize(facade.list_directory(payload.path))
