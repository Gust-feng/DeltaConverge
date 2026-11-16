"""Git 轻量级检测路由（G09）。

旧 UI 在文件夹选择/项目切换时调用 ``POST /api/git/check``，
只关心 ``is_git`` / ``git_root`` / ``error`` 三个字段。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from adapters.web.dependencies import get_facade

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade


git_router = APIRouter(prefix="/api/v2/git", tags=["git"])


class GitCheckRequest(BaseModel):
    path: str


@git_router.post("/check")
def check_git_repository(
    request: GitCheckRequest,
    facade: "KernelFacade" = Depends(get_facade),
):
    """检测指定目录是否位于 Git 工作区内，并返回仓库根目录。"""
    return facade.project_service.check_git_repository(request.path)
