"""系统与环境相关服务。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional


class SystemService:
    def get_system_env(self) -> Dict[str, Any]:
        return {
            "platform": sys.platform,
            "default_project_root": str(Path.cwd()),
            "cwd": str(Path.cwd()),
        }

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
