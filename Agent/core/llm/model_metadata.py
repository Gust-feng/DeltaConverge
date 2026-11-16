"""Read local model metadata without the LiteLLM SDK or network requests."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
CATALOG_PATH = Path(__file__).with_name("catalog") / "model_prices_and_context_window.json"
CATALOG_PATH_ENV = "DELTACONVERGE_MODEL_METADATA_PATH"

_PROVIDERS = {
    "glm": "zai", "bailian": "dashscope", "deepseek": "deepseek",
    "minimax": "minimax", "moonshot": "moonshot", "siliconflow": "siliconflow",
    "modelscope": "modelscope", "openrouter": "openrouter", "openai": "openai",
}
_CAPABILITIES = {
    "supports_reasoning": "reasoning",
    "supports_response_schema": "structured_output",
    "supports_function_calling": "tool_calling",
    "supports_vision": "vision",
}


@lru_cache(maxsize=2)
def _read_catalog(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Model metadata must be a JSON object")
    return payload


def _catalog() -> tuple[dict[str, Any], str]:
    custom_path = os.getenv(CATALOG_PATH_ENV)
    if custom_path:
        try:
            return _read_catalog(custom_path), "user"
        except (OSError, ValueError) as exc:
            logger.warning("Cannot read model metadata %s: %s; using bundled catalog", custom_path, exc)
    try:
        return _read_catalog(str(CATALOG_PATH)), "bundled"
    except (OSError, ValueError) as exc:
        logger.warning("Cannot read bundled model metadata: %s", exc)
        return {}, "bundled"


def get_model_metadata(provider: str, model: str, *, metadata_key: str | None = None) -> dict[str, Any]:
    """Match an exact provider/model pair; private aliases need a catalog key.

    Keep input/output limits separate. Do not interpret legacy max_tokens as a
    context window or add independent input/output limits to invent one.
    """
    catalog, origin = _catalog()
    catalog_provider = _PROVIDERS.get(provider)
    if metadata_key:
        keys = [metadata_key]
    elif catalog_provider:
        keys = [f"{catalog_provider}/{model}", model]
    else:
        return {}
    for key in keys:
        entry = catalog.get(key)
        if not isinstance(entry, dict):
            continue
        if not metadata_key and entry.get("litellm_provider") != catalog_provider:
            continue
        if entry.get("mode") not in (None, "chat", "responses"):
            continue
        limits = {}
        for name in ("context_window", "max_input_tokens", "max_output_tokens"):
            value = entry.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                limits[name] = value
        capabilities = {
            name: entry[field]
            for field, name in _CAPABILITIES.items()
            if isinstance(entry.get(field), bool)
        }
        if "structured_output" in capabilities:
            capabilities["json_schema"] = capabilities["structured_output"]
        return {"source": "litellm", "catalog": origin, "key": key,
                "limits": limits, "capabilities": capabilities}
    return {}
