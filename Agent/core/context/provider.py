"""Context provider that selects files or snippets for review."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List


class ContextProvider:
    """Loads contextual snippets (e.g., diff-selected files)."""

    def __init__(self, max_bytes: int = 16_000) -> None:
        self.max_bytes = max_bytes

    def load_context(self, files: List[str]) -> Dict[str, str]:
        """Return a mapping of file_path -> snippet limited by max_bytes."""

        context: Dict[str, str] = {}
        budget = self.max_bytes
        for file_path in files:
            path = Path(file_path)
            if not path.exists() or budget <= 0:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            snippet = text[: min(len(text), budget)]
            context[file_path] = snippet
            budget -= len(snippet)
            if budget <= 0:
                break
        return context

