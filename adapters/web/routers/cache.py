from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends

from adapters.web.dependencies import get_facade

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

cache_router = APIRouter(prefix="/api/v2/cache", tags=["cache"])


@cache_router.get("/stats")
def get_cache_stats(facade: KernelFacade = Depends(get_facade)):
    return facade.get_cache_stats()


@cache_router.get("/intent")
def list_intent_caches(facade: KernelFacade = Depends(get_facade)):
    return facade.list_intent_caches()


@cache_router.delete("/intent")
def clear_intent_cache(
    project_name: Optional[str] = None,
    facade: KernelFacade = Depends(get_facade),
):
    return facade.clear_intent_cache(project_name)
