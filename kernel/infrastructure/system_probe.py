"""系统环境探测与原生文件夹选择桥接。

集中放置 ``/api/v2/system/env`` 需要的平台探测逻辑，避免在 service 层散落
``sys.platform`` / 环境变量判断。GUI 对话框直接复用 legacy 实现，不在新内核
中复制任何 GUI 代码。
"""

from __future__ import annotations

import os
import string
import sys
from pathlib import Path
from typing import List, Optional

_TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(raw: Optional[str]) -> bool:
    if raw is None:
        return False
    return str(raw).strip().lower() in _TRUTHY


def is_docker() -> bool:
    """检测是否运行在 Docker 容器中。

    与 legacy ``UI/server.py::is_docker`` 保持一致：环境变量标记、
    ``/.dockerenv`` 文件、``/proc/1/cgroup`` 关键字三重检测。
    所有探测异常都视为“未检测到”，不影响接口返回。
    """
    try:
        flags = (
            os.environ.get("RUNNING_IN_DOCKER"),
            os.environ.get("DOCKER"),
            os.environ.get("IS_DOCKER"),
        )
        if any(_is_truthy(flag) for flag in flags if flag is not None):
            return True
        if os.path.exists("/.dockerenv"):
            return True
        try:
            with open("/proc/1/cgroup", "r", encoding="utf-8") as file:
                content = file.read().lower()
            if "docker" in content or "kubepods" in content or "containerd" in content:
                return True
        except OSError:
            pass
    except Exception:
        pass
    return False


def docker_path_restrictions() -> bool:
    """Docker 路径白名单是否启用（仅在容器内生效）。"""
    return is_docker() and _is_truthy(os.getenv("DOCKER_PATH_RESTRICTIONS"))


def default_project_root() -> str:
    """默认项目根：优先 ``DEFAULT_PROJECT_ROOT``，否则当前工作目录。"""
    raw = os.getenv("DEFAULT_PROJECT_ROOT")
    if raw and raw.strip():
        return raw.strip()
    return str(Path.cwd())


def allowed_project_roots() -> List[str]:
    """解析 ``ALLOWED_PROJECT_ROOTS``（按 ``os.pathsep`` 分隔）。"""
    raw = os.getenv("ALLOWED_PROJECT_ROOTS")
    if not raw:
        return []
    return [item.strip() for item in raw.split(os.pathsep) if item.strip()]


def list_drives() -> List[str]:
    """Windows 下枚举存在的盘符（A:-Z:），其它平台返回空列表。"""
    if sys.platform != "win32":
        return []
    drives: List[str] = []
    for letter in string.ascii_uppercase:
        try:
            if Path(f"{letter}:/").exists():
                drives.append(f"{letter}:\\")
        except OSError:
            continue
    return drives


def pick_folder() -> Optional[str]:
    """调用 legacy 原生文件夹选择对话框（阻塞）。

    调用方应在线程池中执行。异常向上传播，由路由转换为 ``{"error": ...}``。
    """
    from legacy.ui_v1.dialogs import pick_folder as _pick_folder

    result = _pick_folder()
    return str(result) if result else None


__all__ = [
    "allowed_project_roots",
    "default_project_root",
    "docker_path_restrictions",
    "is_docker",
    "list_drives",
    "pick_folder",
]
