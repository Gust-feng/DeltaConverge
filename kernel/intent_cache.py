"""Shared project identity and storage rules for intent caches."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def project_identity(project_root: str) -> str:
    return os.path.normcase(str(Path(project_root).resolve()))


def cache_path(cache_dir: Path, project_root: str) -> Path:
    identity = project_identity(project_root)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def read_cache(cache_dir: Path, project_root: str) -> dict[str, Any] | None:
    paths = (cache_path(cache_dir, project_root), cache_dir / f"{Path(project_root).resolve().name}.json")
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            root = data.get("project_root")
            if root and project_identity(root) == project_identity(project_root):
                return data
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return None


def delete_cache(cache_dir: Path, project_root: str) -> None:
    """Remove the project cache and any matching legacy basename cache."""
    current = cache_path(cache_dir, project_root)
    legacy = cache_dir / f"{Path(project_root).resolve().name}.json"
    current.unlink(missing_ok=True)
    if legacy == current:
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
        root = data.get("project_root")
        if root and project_identity(root) == project_identity(project_root):
            legacy.unlink()
    except (FileNotFoundError, ValueError, TypeError, AttributeError):
        pass
