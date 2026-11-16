"""系统与环境相关服务。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional


class SystemService:
    def __init__(self, *, probe: Any | None = None) -> None:
        # 允许测试注入替身；默认惰性使用 infrastructure 的系统探测器。
        self._probe = probe

    def _probe_impl(self) -> Any:
        if self._probe is not None:
            return self._probe
        from kernel.infrastructure import system_probe

        return system_probe

    def get_system_env(self) -> Dict[str, Any]:
        probe = self._probe_impl()
        cwd = str(Path.cwd())
        return {
            "is_docker": bool(probe.is_docker()),
            "platform": sys.platform,
            "default_project_root": probe.default_project_root(),
            "allowed_project_roots": list(probe.allowed_project_roots()),
            "docker_path_restrictions": bool(probe.docker_path_restrictions()),
            "drives": list(probe.list_drives()),
            "base": cwd,
            "cwd": cwd,
        }

    def pick_folder(self) -> Optional[str]:
        """打开系统原生文件夹选择器；阻塞调用方需放入线程池。"""
        return self._probe_impl().pick_folder()

    def list_directory(self, path: Optional[str] = None) -> Dict[str, Any]:
        target = Path(path or Path.cwd()).expanduser().resolve()
        if not target.exists():
            return {"error": f"Directory not found: {target}"}
        if not target.is_dir():
            return {"error": f"Not a directory: {target}"}

        children = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if child.name.startswith(".") and child.name not in {".git"}:
                continue
            if not child.is_dir():
                continue
            children.append({"name": child.name, "path": str(child), "is_dir": True})

        return {"path": str(target), "children": children}
