from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from adapters.web.dependencies import get_facade
from adapters.web.schemas import ConfigUpdatePayload

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

router = APIRouter(prefix="/api/v2", tags=["config"])


@router.get("/config")
def get_config(facade: KernelFacade = Depends(get_facade)):
    return facade.get_config()


@router.get("/config/doctor")
def get_config_doctor(facade: KernelFacade = Depends(get_facade)):
    return facade.get_config_doctor()


@router.patch("/config")
def update_config(payload: ConfigUpdatePayload, facade: KernelFacade = Depends(get_facade)):
    try:
        return facade.update_config(payload.updates, payload.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/models/providers")
def get_model_providers(facade: KernelFacade = Depends(get_facade)):
    return {"items": facade.get_model_providers()}


@router.get("/tools")
def get_tools(facade: KernelFacade = Depends(get_facade)):
    return {"items": facade.get_tools()}
