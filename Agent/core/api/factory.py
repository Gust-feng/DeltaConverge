"""LLM 客户端工厂模块。"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any, Type
from dataclasses import dataclass

from Agent.core.llm.client import (
    BaseLLMClient,
    BailianLLMClient,
    GLMLLMClient,
    MockMoonshotClient,
    MoonshotLLMClient,
    ModelScopeLLMClient,
    OpenRouterLLMClient,
    SiliconFlowLLMClient,
    DeepSeekLLMClient,
)
from Agent.core.logging.api_logger import APILogger
from Agent.core.logging.fallback_tracker import record_fallback

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
        "moonshot": ProviderConfig(
            client_class=MoonshotLLMClient,
            api_key_env="MOONSHOT_API_KEY",
            base_url="https://api.moonshot.cn/v1",
            label="月之暗面 (Moonshot)"
        ),
        "openrouter": ProviderConfig(
            client_class=OpenRouterLLMClient,
            api_key_env="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            label="OpenRouter"
        ),
        "siliconflow": ProviderConfig(
            client_class=SiliconFlowLLMClient,
            api_key_env="SILICONFLOW_API_KEY",
            base_url="https://api.siliconflow.cn/v1",
            label="硅基流动 (SiliconFlow)"
        ),
        "deepseek": ProviderConfig(
            client_class=DeepSeekLLMClient,
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            label="DeepSeek"
        ),
    }

    # 默认模型列表 (当配置文件不存在时使用此列表创建新的模型列表)
    DEFAULT_MODELS = {
        "glm": ["glm-4.5-flash", "glm-4.5", "glm-4.5-air", "glm-4.6",],
        "bailian": ["qwen-max", "qwen-plus", "qwen-flash", "qwen-coder-plus"],
        "moonshot": ["kimi-k2-thinking", "kimi-k2-thinking-turbo", "kimi-k2-turbo-preview", "kimi-k2-0905-preview"],
        "modelscope": ["ZhipuAI/GLM-4.6", "ZhipuAI/GLM-4.5", "deepseek-ai/DeepSeek-R1", "deepseek-ai/DeepSeek-V3.2-Exp"],
        "openrouter": ["x-ai/grok-4.1-fast:free", "z-ai/glm-4.5-air:free", "moonshotai/kimi-k2:free", "tngtech/tng-r1t-chimera:free"],
        "siliconflow": ["Pro/moonshotai/Kimi-K2-Thinking","deepseek-ai/DeepSeek-R1","Pro/deepseek-ai/DeepSeek-V3.2","zai-org/GLM-4.6"],
        "deepseek": ["deepseek-reasoner", "deepseek-chat"],
    }

    # 运行时模型列表
    _MODELS: Dict[str, List[str]] = {}
    _CONFIG_PATH = Path(__file__).parent / "models_config.json"

    @staticmethod
    def _ensure_models_loaded():
        """确保模型列表已加载。"""
        if LLMFactory._MODELS:
            return

        if LLMFactory._CONFIG_PATH.exists():
            try:
                with open(LLMFactory._CONFIG_PATH, "r", encoding="utf-8") as f:
                    LLMFactory._MODELS = json.load(f)
            except Exception as e:
                LLMFactory._MODELS = LLMFactory.DEFAULT_MODELS.copy()
            for pname, models in LLMFactory.DEFAULT_MODELS.items():
                if pname not in LLMFactory._MODELS:
                    LLMFactory._MODELS[pname] = models
            LLMFactory._save_models()
        else:
            LLMFactory._MODELS = LLMFactory.DEFAULT_MODELS.copy()
            LLMFactory._save_models()

    @staticmethod
    def _save_models():
        """保存模型列表到配置文件。"""
        try:
            with open(LLMFactory._CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(LLMFactory._MODELS, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save models config: {e}")

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
            provider_name, _, model_override = preference.partition(":")
            model_override = model_override or None
            
            if provider_name in LLMFactory.PROVIDERS:
                client = LLMFactory._create_client(provider_name, trace_id, model_override)
                if client:
                    return client, provider_name
            
            # 指定了但无法创建（通常是缺 Key）
            raise RuntimeError(f"无法创建指定的 LLM 客户端: '{preference}'。请检查环境变量中是否配置了对应的 API Key。")

        # 3. Auto 模式：按注册顺序尝试
        for name in LLMFactory.PROVIDERS:
            try:
                client = LLMFactory._create_client(name, trace_id)
                if client:
                    return client, name
            except Exception:
                # 自动模式下，单个厂商初始化失败（如配置错误）则跳过，尝试下一个
                continue

        # 4. 全部失败
        record_fallback("llm_client_fallback", "未找到可用 LLM 客户端，降级为 Mock", meta={"preference": preference})
        return MockMoonshotClient(), "mock"

    @staticmethod
    def _create_client(provider_name: str, trace_id: str | None, model_override: str | None = None) -> Optional[BaseLLMClient]:
        """通用客户端创建逻辑。"""
        config = LLMFactory.PROVIDERS.get(provider_name)
        if not config:
            return None

        # 检查 API Key (核心参数)
        api_key = os.getenv(config.api_key_env)
        if not api_key:
            return None

        # 确定模型
        # 优先级：Override > 列表第一个
        model = model_override
        if not model:
            # 必须从注册列表中选择一个
            models = LLMFactory._MODELS.get(provider_name)
            if models:
                model = models[0]
            else:
                # 理论上不应发生，除非配置错误或列表为空
                raise RuntimeError(f"Provider '{provider_name}' has no registered models.")

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

        # 直接实例化
        return config.client_class(**kwargs)

    @staticmethod
    def get_available_options(include_mock: bool = True) -> List[Dict[str, Any]]:
        """探测可用选项。"""
        LLMFactory._ensure_models_loaded()
        groups = []
        
        for name, config in LLMFactory.PROVIDERS.items():
            has_key = bool(os.getenv(config.api_key_env))
            
            group = {
                "provider": name,
                "label": config.label,
                "is_active": has_key,
                "models": []
            }
            
            # 获取模型列表 (仅使用硬编码的注册列表)
            known_models = list(LLMFactory._MODELS.get(name, []))
            
            for model_id in known_models:
                group["models"].append({
                    "name": f"{name}:{model_id}",
                    "label": model_id,
                    "available": has_key,
                    "reason": None if has_key else f"缺少 {config.api_key_env}"
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
