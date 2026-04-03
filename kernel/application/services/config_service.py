"""配置、工具和提供商服务。"""

from __future__ import annotations

import os
from typing import Dict, List, Any


class ConfigService:
    def get_config(self) -> Dict[str, object]:
        from Agent.core.api.config import ConfigAPI

        return ConfigAPI.get_config()

    def update_config(self, updates: Dict[str, object], persist: bool = True) -> Dict[str, object]:
        from Agent.core.api.config import ConfigAPI

        return ConfigAPI.update_config(updates, persist)

    def get_model_providers(self) -> List[Dict[str, Any]]:
        from Agent.core.api.factory import LLMFactory

        LLMFactory._ensure_models_loaded()
        items = []
        for provider_id, config in LLMFactory.PROVIDERS.items():
            models = list(LLMFactory._MODELS.get(provider_id, []))
            configured = bool(os.getenv(config.api_key_env))
            items.append(
                {
                    "id": provider_id,
                    "label": config.label,
                    "available": configured,
                    "configured": configured,
                    "model_count": len(models),
                    "models": models,
                    "api_key_env": config.api_key_env,
                    "base_url": os.getenv(f"{config.api_key_env.split('_API_KEY')[0]}_BASE_URL", config.base_url),
                    "error": None if configured else f"缺少 {config.api_key_env}",
                }
            )
        return items

    def get_tools(self) -> List[Dict[str, Any]]:
        from Agent.core.api.tools import ToolAPI

        return ToolAPI.list_tools()
