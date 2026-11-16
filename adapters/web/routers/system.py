from __future__ import annotations

import asyncio
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


@router.post("/pick-folder")
async def pick_folder(facade: KernelFacade = Depends(get_facade)):
    """打开系统原生文件夹选择框；沿用 legacy 契约，异常也回 HTTP 200。"""
    try:
        path = await asyncio.to_thread(facade.system_service.pick_folder)
        return {"path": path or None}
    except Exception as exc:
        return {"error": str(exc)}
