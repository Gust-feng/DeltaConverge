from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from adapters.web.dependencies import get_facade
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade


router = APIRouter(prefix="/api/v2/diff", tags=["diff"])


@router.get("/status")
def get_diff_status(project_root: str | None = None, facade: KernelFacade = Depends(get_facade)):
    return facade.get_diff_status(project_root)


@router.get("/summary")
def get_diff_summary(
    project_root: str | None = None,
    mode: str = "auto",
    facade: KernelFacade = Depends(get_facade),
):
    return facade.get_diff_summary(project_root, mode)


@router.get("/files")
def get_diff_files(
    project_root: str | None = None,
    mode: str = "auto",
    facade: KernelFacade = Depends(get_facade),
):
    return facade.get_diff_files(project_root, mode)


@router.get("/file")
def get_file_diff(
    file_path: str,
    project_root: str | None = None,
    mode: str = "auto",
    commit_from: str | None = None,
    commit_to: str | None = None,
    facade: KernelFacade = Depends(get_facade),
):
    return facade.get_file_diff(
        file_path,
        project_root=project_root,
        mode=mode,
        commit_from=commit_from,
        commit_to=commit_to,
    )


@router.get("/quick-status")
def get_diff_quick_status(
    project_root: str | None = None,
    facade: KernelFacade = Depends(get_facade),
):
    """与旧 UI 同契约的轻量 Diff 检测（单次 git status --porcelain）。"""
    return facade.project_service.get_diff_quick_status(project_root)


@router.get("/commits")
def get_commit_history(
    project_root: str,
    limit: int = 50,
    skip: int = 0,
    branch: str | None = None,
    facade: KernelFacade = Depends(get_facade),
):
    # KernelFacade 的公开代理签名暂未扩展分页参数，这里直接复用其 ProjectService；
    # 返回结构与 facade.get_commit_history 保持一致并补齐旧 UI 字段。
    return facade.project_service.get_commit_history(
        project_root,
        limit=limit,
        skip=skip,
        branch=branch,
    )


@router.get("/commit-range")
def get_commit_range_diff(
    project_root: str,
    commit_from: str,
    commit_to: str | None = None,
    facade: KernelFacade = Depends(get_facade),
):
    return serialize(
        facade.get_commit_range_diff(
            project_root=project_root,
            commit_from=commit_from,
            commit_to=commit_to,
        )
    )
