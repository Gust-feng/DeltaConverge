from __future__ import annotations

from typing import TYPE_CHECKING

from kernel import get_kernel_facade

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade


def get_facade() -> "KernelFacade":
    return get_kernel_facade()
