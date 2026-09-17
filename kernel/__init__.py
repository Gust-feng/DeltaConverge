from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application.facade import KernelFacade


def get_kernel_facade() -> "KernelFacade":
    from .bootstrap import get_kernel_facade as _get_kernel_facade

    return _get_kernel_facade()


__all__ = ["get_kernel_facade", "KernelFacade"]
