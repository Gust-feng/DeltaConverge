"""Legacy 配置适配器

包装旧内核的 ``Agent.core.api.config`` 与 ``Agent.core.api.factory`` /
``Agent.core.api.tools``，实现新的 ConfigPort 接口。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from kernel.ports.config import ConfigPort, ReviewPromptLimits

logger = logging.getLogger(__name__)


class LegacyConfigAdapter(ConfigPort):
    """包装旧配置 API 的适配器。"""

    def get_config(self) -> Dict[str, Any]:
        """获取当前完整配置。"""
        from Agent.core.api.config import ConfigAPI

        return ConfigAPI.get_config()

    def update_config(
        self,
        updates: Dict[str, Any],
        *,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """更新配置。"""
        from Agent.core.api.config import ConfigAPI

        return ConfigAPI.update_config(updates, persist)

    def get_config_doctor(self) -> Dict[str, Any]:
        """获取配置体检结果。"""
        from Agent.core.api.config import ConfigAPI

        return ConfigAPI.get_config_doctor()

    def get_review_prompt_limits(self) -> ReviewPromptLimits:
        """获取审查提示词限制；读取失败时回退到默认值。"""
        from Agent.core.api.config import get_review_prompt_limits

        try:
            return ReviewPromptLimits.from_dict(get_review_prompt_limits())
        except Exception:
            logger.warning("读取审查提示词限制失败，回退默认值", exc_info=True)
            return ReviewPromptLimits()

    def get_model_providers(self) -> List[Dict[str, Any]]:
        """列出模型提供商及其可用模型。"""
        from Agent.core.api.factory import LLMFactory

        LLMFactory._ensure_models_loaded()
        items: List[Dict[str, Any]] = []
        for provider_id, config in LLMFactory.PROVIDERS.items():
            models = list(LLMFactory._MODELS.get(provider_id, []))
            configured = bool(os.getenv(config.api_key_env))
            base_url_env = f"{config.api_key_env.split('_API_KEY')[0]}_BASE_URL"
            items.append(
                {
                    "id": provider_id,
                    "label": config.label,
                    "available": configured,
                    "configured": configured,
                    "model_count": len(models),
                    "models": models,
                    "api_key_env": config.api_key_env,
                    "base_url": os.getenv(base_url_env, config.base_url),
                    "error": None if configured else f"缺少 {config.api_key_env}",
                }
            )
        return items

    def get_tools(self) -> List[Dict[str, Any]]:
        """列出可用工具定义。"""
        from Agent.core.api.tools import ToolAPI

        return ToolAPI.list_tools()


__all__ = ["LegacyConfigAdapter"]
