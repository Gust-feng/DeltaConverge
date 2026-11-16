"""LLM 客户端工厂模块。"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import List, Optional, Set, Tuple, Dict, Any, Type
from dataclasses import dataclass

from Agent.core.llm.client import (
    BaseLLMClient,
    BailianLLMClient,
    GLMLLMClient,
    MiniMaxLLMClient,
    MockMoonshotClient,
    OpenAIClientBase,
    MoonshotLLMClient,
    ModelScopeLLMClient,
    OpenRouterLLMClient,
    SiliconFlowLLMClient,
    DeepSeekLLMClient,
)
from Agent.core.logging.api_logger import APILogger
from Agent.core.llm.model_metadata import get_model_metadata

@dataclass
class ProviderConfig:
    client_class: Type[BaseLLMClient]
    api_key_env: str
    base_url: str
    label: str

class LLMFactory:
    """LLM 客户端工厂，负责管理多厂商客户端的创建。"""

    # 注册厂商配置 (优先级顺序)
    PROVIDERS: Dict[str, ProviderConfig] = {
        "minimax": ProviderConfig(
            client_class=MiniMaxLLMClient,
            api_key_env="MINIMAX_API_KEY",
            base_url="https://api.minimaxi.com/v1",
            label="MiniMax"
        ),
        "deepseek": ProviderConfig(
            client_class=DeepSeekLLMClient,
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            label="DeepSeek"
        ),
        "moonshot": ProviderConfig(
            client_class=MoonshotLLMClient,
            api_key_env="MOONSHOT_API_KEY",
            base_url="https://api.moonshot.cn/v1",
            label="月之暗面 (Moonshot)"
        ),
        "siliconflow": ProviderConfig(
            client_class=SiliconFlowLLMClient,
            api_key_env="SILICONFLOW_API_KEY",
            base_url="https://api.siliconflow.cn/v1",
            label="硅基流动 (SiliconFlow)"
        ),
        "glm": ProviderConfig(
            client_class=GLMLLMClient,
            api_key_env="GLM_API_KEY",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            label="智谱AI (GLM)"
        ),
        "bailian": ProviderConfig(
            client_class=BailianLLMClient,
            api_key_env="BAILIAN_API_KEY",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            label="阿里百炼 (Bailian)"
        ),
        "modelscope": ProviderConfig(
            client_class=ModelScopeLLMClient,
            api_key_env="MODELSCOPE_API_KEY",
            base_url="https://api-inference.modelscope.cn/v1",
            label="魔搭社区 (ModelScope)"
        ),
        "openrouter": ProviderConfig(
            client_class=OpenRouterLLMClient,
            api_key_env="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            label="OpenRouter"
        ),
        "openai": ProviderConfig(
            client_class=OpenAIClientBase,
            api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            label="OpenAI",
        ),


    }

    _MODELS: Dict[str, List[str]] = {}
    _CONFIG_PATH = Path(__file__).parent / "models_config.json"
    _MODEL_SETTINGS: Dict[str, Dict[str, Dict[str, Any]]] = {}
    _PROVIDER_SETTINGS: Dict[str, Dict[str, Any]] = {}
    # 软删除的服务不参与服务/模型列表，但配置与 Key 保留，可在服务目录恢复。
    _DISABLED_PROVIDERS: Set[str] = set()
    # 代码内置的厂商配置快照，reload 时以此为基础再合并 models_config.json。
    _BASE_PROVIDERS: Optional[Dict[str, "ProviderConfig"]] = None

    @classmethod
    def _provider_defaults(cls) -> Dict[str, "ProviderConfig"]:
        if cls._BASE_PROVIDERS is None:
            cls._BASE_PROVIDERS = dict(cls.PROVIDERS)
        return cls._BASE_PROVIDERS

    @classmethod
    def reload(cls) -> None:
        """重新读取 models_config.json；新增/删除服务后使用。"""
        cls._MODELS = {}
        cls._MODEL_SETTINGS = {}
        cls._PROVIDER_SETTINGS = {}
        cls._DISABLED_PROVIDERS = set()
        cls.PROVIDERS = dict(cls._provider_defaults())
        cls._ensure_models_loaded()

    @staticmethod
    def _ensure_models_loaded():
        """Load legacy model lists and the extended connection format without writing."""
        if LLMFactory._MODELS:
            return
        with open(LLMFactory._CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
        providers = config.get("providers", config)
        models_by_provider = {}
        model_settings = {}
        provider_settings = {}
        disabled_providers: Set[str] = set()
        configured_providers = dict(LLMFactory._provider_defaults())
        from Agent.core.llm.client import OpenAIClientBase
        for name, value in providers.items():
            if isinstance(value, list):
                value = {"models": value}
            protocol = value.get("protocol", "chat_completions")
            if protocol not in {"chat_completions", "responses"}:
                raise ValueError(f"Invalid protocol for {name}: {protocol}")
            provider_settings[name] = value
            if value.get("disabled") is True:
                disabled_providers.add(name)
            models = value.get("models", [])
            models_by_provider[name] = [m if isinstance(m, str) else m["id"] for m in models]
            model_settings[name] = {m["id"]: m for m in models if isinstance(m, dict)}
            for model in model_settings[name].values():
                if model.get("protocol", protocol) not in {"chat_completions", "responses"}:
                    raise ValueError(f"Invalid protocol for {name}:{model['id']}")
            existing = configured_providers.get(name)
            configured_providers[name] = ProviderConfig(
                existing.client_class if existing else OpenAIClientBase,
                value.get("api_key_env", existing.api_key_env if existing else ""),
                value.get("base_url", existing.base_url if existing else ""),
                value.get("label", existing.label if existing else name))
        LLMFactory.PROVIDERS = configured_providers
        LLMFactory._PROVIDER_SETTINGS = provider_settings
        LLMFactory._MODEL_SETTINGS = model_settings
        LLMFactory._MODELS = models_by_provider
        LLMFactory._DISABLED_PROVIDERS = disabled_providers

    @staticmethod
    def _save_models():
        with open(LLMFactory._CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
        providers = config.get("providers", config)
        for name, models in LLMFactory._MODELS.items():
            entry = providers.get(name)
            original_models = entry.get("models", []) if isinstance(entry, dict) else (entry or [])
            original = {m["id"]: m for m in original_models if isinstance(m, dict)}
            saved_models = [original.get(m, m) for m in models]
            if isinstance(entry, dict):
                entry["models"] = saved_models
            else:
                providers[name] = saved_models
        with open(LLMFactory._CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    @staticmethod
    def add_model(provider: str, model: str):
        """添加新模型。"""
        LLMFactory._ensure_models_loaded()
        if provider not in LLMFactory.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        
        if provider not in LLMFactory._MODELS:
            LLMFactory._MODELS[provider] = []
            
        if model not in LLMFactory._MODELS[provider]:
            LLMFactory._MODELS[provider].append(model)
            LLMFactory._save_models()

    @staticmethod
    def remove_model(provider: str, model: str):
        """移除模型。"""
        LLMFactory._ensure_models_loaded()
        if provider in LLMFactory._MODELS:
            if model in LLMFactory._MODELS[provider]:
                LLMFactory._MODELS[provider].remove(model)
                LLMFactory._save_models()

    @staticmethod
    def create(preference: str = "auto", trace_id: str | None = None) -> Tuple[BaseLLMClient, str]:
        """根据偏好创建 LLM 客户端。"""
        LLMFactory._ensure_models_loaded()
        
        # 1. Mock 模式
        if preference == "mock":
            return MockMoonshotClient(), "mock"

        # 2. 指定模式 (e.g. "glm", "glm:glm-4-plus")
        if preference != "auto":
            provider_name, model_override = LLMFactory._resolve_provider_and_model(preference)
            
            if provider_name in LLMFactory.PROVIDERS:
                client = LLMFactory._create_client(provider_name, trace_id, model_override)
                if client:
                    return client, provider_name
            
            reason = LLMFactory._provider_unavailable_reason(provider_name)
            raise RuntimeError(f"无法创建指定的 LLM 客户端: '{preference}'。{reason or '客户端初始化失败。'}")

        # 3. Auto 模式：按注册顺序尝试
        for name in LLMFactory.PROVIDERS:
            try:
                client = LLMFactory._create_client(name, trace_id)
                if client:
                    return client, name
            except Exception:
                # 自动模式下，单个厂商初始化失败（如配置错误）则跳过，尝试下一个
                continue

        # 4. 全部失败：严格失败，不自动降级为 Mock
        raise RuntimeError("未找到可用 LLM 客户端。请检查环境变量中的 API Key 配置。")

    @staticmethod
    def _resolve_provider_and_model(preference: str) -> Tuple[str, Optional[str]]:
        """将前端传入的 provider / provider:model / 纯模型名 统一解析成 provider + model。"""
        provider_name, _, model_override = preference.partition(":")
        model_override = model_override or None

        if provider_name in LLMFactory.PROVIDERS:
            return provider_name, model_override

        # 兼容前端直接传纯模型名，例如 deepseek-reasoner。
        matches: List[Tuple[str, str]] = []
        for name in LLMFactory.PROVIDERS:
            if name in LLMFactory._DISABLED_PROVIDERS:
                continue
            for candidate in LLMFactory._MODELS.get(name, []):
                if candidate == preference:
                    matches.append((name, candidate))

        if matches:
            # 优先选择当前已配置的提供商，避免多个 provider 共享同名模型时选到不可用项。
            for name, model in matches:
                config = LLMFactory.PROVIDERS.get(name)
                if config and os.getenv(config.api_key_env):
                    return name, model
            return matches[0]

        return provider_name, model_override

    @staticmethod
    def _provider_unavailable_reason(provider_name: str) -> Optional[str]:
        """基于已加载的本地配置判断可用性，不请求上游验证凭据。"""
        config = LLMFactory.PROVIDERS.get(provider_name)
        if config is None:
            return f"Unknown provider: {provider_name}"
        if provider_name in LLMFactory._DISABLED_PROVIDERS:
            return f"Provider '{provider_name}' is disabled."
        if not os.getenv(config.api_key_env):
            return f"缺少 {config.api_key_env}"
        if not LLMFactory._MODELS.get(provider_name):
            return f"Provider '{provider_name}' has no registered models."
        return None

    @staticmethod
    def _create_client(provider_name: str, trace_id: str | None, model_override: str | None = None) -> Optional[BaseLLMClient]:
        """只为启用的服务创建客户端，模型必须在已保存列表中。"""
        LLMFactory._ensure_models_loaded()
        config = LLMFactory.PROVIDERS.get(provider_name)
        if not config:
            return None

        models = LLMFactory._MODELS.get(provider_name, [])
        if model_override is not None and model_override not in models:
            raise RuntimeError(f"Model '{provider_name}:{model_override}' is not registered in models_config.json.")
        if LLMFactory._provider_unavailable_reason(provider_name) is not None:
            return None

        api_key = os.getenv(config.api_key_env)
        model = model_override if model_override is not None else models[0]

        # 构造参数
        env_base_var = f"{config.api_key_env.split('_API_KEY')[0]}_BASE_URL"
        dynamic_base = os.getenv(env_base_var, config.base_url)
        kwargs: Dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "base_url": dynamic_base,
        }
        
        if trace_id:
            kwargs["logger"] = APILogger(trace_id=trace_id)

        settings = LLMFactory._PROVIDER_SETTINGS.get(provider_name, {})
        model_settings = LLMFactory._MODEL_SETTINGS.get(provider_name, {}).get(model, {})
        if settings.get("base_url"):
            kwargs["base_url"] = os.getenv(env_base_var, settings["base_url"])
        client = config.client_class(**kwargs)
        client.provider_name = provider_name
        client.protocol = model_settings.get("protocol", settings.get("protocol", "chat_completions"))
        metadata = LLMFactory.get_model_metadata(provider_name, model)
        client.capabilities = metadata["capabilities"]
        client.limits = metadata["limits"]
        client.model_metadata = metadata
        return client

    @staticmethod
    def get_model_metadata(provider: str, model: str) -> Dict[str, Any]:
        """Supplement explicit settings with catalog data without changing routing."""
        settings = LLMFactory._PROVIDER_SETTINGS.get(provider, {})
        model_settings = LLMFactory._MODEL_SETTINGS.get(provider, {}).get(model, {})
        return LLMFactory._merge_model_metadata(provider, model, settings, model_settings)

    @staticmethod
    def _merge_model_metadata(
        provider: str, model: str, settings: Dict[str, Any], model_settings: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve a settings snapshot without mutating the factory's loaded state."""
        metadata = get_model_metadata(provider, model, metadata_key=model_settings.get("metadata_key"))
        protocol = model_settings.get("protocol", settings.get("protocol", "chat_completions"))
        capabilities = dict(metadata.get("capabilities", {}))
        for config in (settings, model_settings):
            for layer in (config.get("capabilities", {}), config.get("protocol_capabilities", {}).get(protocol, {})):
                capabilities.update(layer)
                if "structured_output" in layer and "json_schema" not in layer:
                    capabilities["json_schema"] = layer["structured_output"]
        if "json_schema" in capabilities:
            capabilities["structured_output"] = capabilities["json_schema"]
        limits = {**metadata.get("limits", {}), **settings.get("limits", {}), **model_settings.get("limits", {})}
        defaults = {"limits": dict(limits), "capabilities": dict(capabilities)}
        manual = model_settings.get("metadata_overrides", {})
        overrides = {
            "limits": dict(manual.get("limits", {})),
            "capabilities": dict(manual.get("capabilities", {})),
        }
        limits.update(overrides["limits"])
        capabilities.update(overrides["capabilities"])
        if "json_schema" in capabilities:
            capabilities["structured_output"] = capabilities["json_schema"]
        return {
            **metadata,
            "limits": limits,
            "capabilities": capabilities,
            "defaults": defaults,
            "overrides": overrides,
        }

    @staticmethod
    def get_available_options(include_mock: bool = True) -> List[Dict[str, Any]]:
        """列出已保存模型；可用性仅取决于本地配置，不请求上游。"""
        LLMFactory._ensure_models_loaded()
        groups = []
        
        for name, config in LLMFactory.PROVIDERS.items():
            if name in LLMFactory._DISABLED_PROVIDERS:
                continue
            reason = LLMFactory._provider_unavailable_reason(name)
            available = reason is None
            
            group = {
                "provider": name,
                "label": config.label,
                "is_active": available,
                "models": []
            }
            
            known_models = list(LLMFactory._MODELS.get(name, []))
            
            for model_id in known_models:
                group["models"].append({
                    "name": f"{name}:{model_id}",
                    "label": model_id,
                    "available": available,
                    "reason": reason,
                    "metadata": LLMFactory.get_model_metadata(name, model_id),
                })
            
            groups.append(group)

        if include_mock:
            groups.append({
                "provider": "mock",
                "label": "测试/Mock",
                "is_active": True,
                "models": [{"name": "mock", "label": "Mock Client", "available": True, "reason": None}]
            })
            
        return groups
