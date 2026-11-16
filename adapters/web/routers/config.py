from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from adapters.web.dependencies import get_facade
from adapters.web.schemas import ConfigUpdatePayload

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

router = APIRouter(prefix="/api/v2", tags=["config"])


class ProviderKeyPayload(BaseModel):
    """Provider API Key 写入请求（兼容 legacy 字段名）。"""

    provider: str
    value: Optional[str] = None


class ModelPayload(BaseModel):
    """模型增删请求（兼容 legacy ``model_name`` 字段）。"""

    provider: str
    model_name: Optional[str] = None


class ModelMetadataPayload(BaseModel):
    """两个覆盖对象整体替换；严格拒绝隐式类型转换和额外字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    provider: StrictStr
    model_name: StrictStr
    limits: dict[str, Annotated[int, Field(strict=True, gt=0, le=9007199254740991)]]
    capabilities: dict[str, StrictBool]


class ProviderCreatePayload(BaseModel):
    """自定义（OpenAI 兼容）服务创建请求。"""

    label: str
    base_url: str
    protocol: str = "chat_completions"
    api_key: Optional[str] = None


class ProviderStatePayload(BaseModel):
    """局部更新服务连接配置或软删除状态；未提供 / null 字段保持原值。"""

    disabled: Optional[bool] = None
    protocol: Optional[Literal["chat_completions", "responses"]] = None
    base_url: Optional[str] = None


class DiscoverModelsPayload(BaseModel):
    """上游模型发现请求。"""

    provider: str


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


@router.get("/providers/keys")
def list_provider_keys(facade: KernelFacade = Depends(get_facade)):
    return {"providers": facade.config_service.list_provider_keys()}


@router.post("/providers/keys")
def set_provider_key(payload: ProviderKeyPayload, facade: KernelFacade = Depends(get_facade)):
    # ValueError（未知 Provider / 非法值）由 app.py 全局处理器转为 400。
    return facade.config_service.set_provider_key(payload.provider, payload.value)


@router.post("/models/add")
def add_model(payload: ModelPayload, facade: KernelFacade = Depends(get_facade)):
    facade.config_service.add_model(payload.provider, payload.model_name or "")
    return {"status": "ok"}


@router.post("/models/delete")
def delete_model(payload: ModelPayload, facade: KernelFacade = Depends(get_facade)):
    facade.config_service.remove_model(payload.provider, payload.model_name or "")
    return {"status": "ok"}


@router.get("/models/metadata")
def get_model_metadata(provider: str, model_name: str, facade: KernelFacade = Depends(get_facade)):
    return facade.get_model_metadata(provider, model_name)


@router.patch("/models/metadata")
def update_model_metadata(payload: ModelMetadataPayload, facade: KernelFacade = Depends(get_facade)):
    return facade.update_model_metadata(
        payload.provider, payload.model_name, payload.limits, payload.capabilities
    )


@router.get("/models/providers")
def get_model_providers(include_disabled: bool = False, facade: KernelFacade = Depends(get_facade)):
    return {"items": facade.get_model_providers(include_disabled=include_disabled)}


@router.post("/models/providers")
def create_model_provider(payload: ProviderCreatePayload, facade: KernelFacade = Depends(get_facade)):
    return facade.add_provider(payload.label, payload.base_url, payload.protocol, payload.api_key)


@router.patch("/models/providers/{provider}")
def update_model_provider(
    provider: str,
    payload: ProviderStatePayload,
    facade: KernelFacade = Depends(get_facade),
):
    return facade.update_provider(
        provider,
        disabled=payload.disabled,
        protocol=payload.protocol,
        base_url=payload.base_url,
    )


@router.delete("/models/providers/{provider}")
def delete_model_provider(provider: str, facade: KernelFacade = Depends(get_facade)):
    return facade.delete_provider(provider)


@router.post("/models/discover")
def discover_models(payload: DiscoverModelsPayload, facade: KernelFacade = Depends(get_facade)):
    return facade.discover_models(payload.provider)


@router.get("/tools")
def get_tools(facade: KernelFacade = Depends(get_facade)):
    return {"items": facade.get_tools()}
