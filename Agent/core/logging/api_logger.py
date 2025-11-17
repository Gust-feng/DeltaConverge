"""Simple API logger that stores request/response pairs per session."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class APILogger:
    """Writes structured request/response logs to ./log/api_log."""

    def __init__(self, base_dir: str | Path = "log/api_log") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self, label: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.base_dir / f"{label}_{timestamp}.log"

    def start(self, label: str, payload: Dict[str, Any]) -> Path:
        """Create a new log file and write the request payload."""

        path = self._log_path(label)
        self._write_section(path, "REQUEST", payload)
        return path

    def append(self, path: Path, section: str, payload: Any) -> None:
        """Append a JSON section to an existing log file."""

        self._write_section(path, section, payload)

    def _write_section(self, path: Path, heading: str, payload: Any) -> None:
        with path.open("a", encoding="utf-8") as fp:
            fp.write(f"=== {heading} ===\n")
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.write("\n\n")

