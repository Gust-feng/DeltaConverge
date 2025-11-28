"""LLM 客户端工厂模块。"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from Agent.core.llm.client import (
    BaseLLMClient,
    BailianLLMClient,
    GLMLLMClient,
    MockMoonshotClient,
    MoonshotLLMClient,
    ModelScopeLLMClient,
    OpenRouterLLMClient,
)
from Agent.core.logging.api_logger import APILogger
from Agent.core.logging.fallback_tracker import record_fallback
from Agent.core.api.models import LLMOption


class LLMFactory:
    """LLM 客户端工厂，负责管理多厂商客户端的创建与回退策略。"""

    @staticmethod
    def create(preference: str = "auto", trace_id: str | None = None) -> Tuple[BaseLLMClient, str]:
        """根据偏好创建 LLM 客户端。"""
        creators = [
            LLMFactory._try_create_glm,# 应该是智谱，但是一开始没做好
            LLMFactory._try_create_bailian,
            LLMFactory._try_create_modelscope,
            LLMFactory._try_create_moonshot,
            LLMFactory._try_create_openrouter,
        ]
        
        # 1. 尝试指定偏好
        if preference != "auto":
            client = LLMFactory._create_specific(preference, trace_id)
            if client:
                return client, preference
            # 指定的失败了，根据逻辑可能需要抛错或降级
            # 这里保持原有逻辑：如果指定了但失败/不可用，抛出 RuntimeError
            # 但原逻辑中有 fallback 记录，我们统一在 _create_specific 处理
        
        # 2. Auto 模式：按优先级尝试
        for creator in creators:
            try:
                client, name = creator(trace_id)
                if client:
                    return client, name
            except Exception:
                continue

        # 3. 全部失败，降级为 Mock
        record_fallback(
            "llm_client_fallback",
            "未找到可用 LLM 客户端，降级为 Mock",
            meta={"preference": preference},
        )
        return MockMoonshotClient(), "mock"

    @staticmethod
    def _create_specific(preference: str, trace_id: str | None) -> Optional[BaseLLMClient]:
        try:
            if preference == "glm":
                client, _ = LLMFactory._try_create_glm(trace_id)
                return client
            if preference == "bailian":
                client, _ = LLMFactory._try_create_bailian(trace_id)
                return client
            if preference == "modelscope":
                client, _ = LLMFactory._try_create_modelscope(trace_id)
                return client
            if preference == "moonshot":
                client, _ = LLMFactory._try_create_moonshot(trace_id)
                return client
        except Exception as e:
             # 特定 provider 失败，由上层决定是否抛出
             pass
        
        # 原有逻辑：如果显式指定但 key 不存在，记录 fallback 并抛错
        # 为保持兼容，这里简单检查 key，如果 key 确实缺失，抛出 RuntimeError
        if preference == "glm" and not os.getenv("GLM_API_KEY"):
             raise RuntimeError("GLM 模式被选择，但 GLM 客户端不可用。")
        if preference == "bailian" and not os.getenv("BAILIAN_API_KEY"):
             raise RuntimeError("Bailian 模式被选择，但 Bailian 客户端不可用。")
        if preference == "modelscope" and not os.getenv("MODELSCOPE_API_KEY"):
             raise RuntimeError("ModelScope 模式被选择，但 ModelScope 客户端不可用。")
        if preference == "moonshot" and not os.getenv("MOONSHOT_API_KEY"):
             raise RuntimeError("Moonshot 模式被选择，但 Moonshot 客户端不可用。")
        if preference == "openrouter" and not os.getenv("OPENROUTER_API_KEY"):
             raise RuntimeError("OpenRouter 模式被选择，但 OpenRouter 客户端不可用。")
        
        return None

    @staticmethod
    def _try_create_glm(trace_id: str | None) -> Tuple[Optional[BaseLLMClient], str]:
        key = os.getenv("GLM_API_KEY")
        if not key:
            return None, "glm"
        try:
            return GLMLLMClient(
                model=os.getenv("GLM_MODEL", "GLM-4.6"),
                api_key=key,
                logger=APILogger(trace_id=trace_id) if trace_id else None,
            ), "glm"
        except Exception as exc:
            record_fallback("llm_client_fallback", "GLM 初始化失败", meta={"error": str(exc)})
            return None, "glm"

    @staticmethod
    def _try_create_bailian(trace_id: str | None) -> Tuple[Optional[BaseLLMClient], str]:
        key = os.getenv("BAILIAN_API_KEY")
        if not key:
            return None, "bailian"
        try:
            return BailianLLMClient(
                model=os.getenv("BAILIAN_MODEL", "qwen-max"),
                api_key=key,
                base_url=os.getenv("BAILIAN_BASE_URL"),
                logger=APILogger(trace_id=trace_id) if trace_id else None,
            ), "bailian"
        except Exception as exc:
            record_fallback("llm_client_fallback", "Bailian 初始化失败", meta={"error": str(exc)})
            return None, "bailian"

    @staticmethod
    def _try_create_modelscope(trace_id: str | None) -> Tuple[Optional[BaseLLMClient], str]:
        key = os.getenv("MODELSCOPE_API_KEY")
        if not key:
            return None, "modelscope"
        try:
            return ModelScopeLLMClient(
                model=os.getenv("MODELSCOPE_MODEL", "qwen-plus"),
                api_key=key,
                logger=APILogger(trace_id=trace_id) if trace_id else None,
            ), "modelscope"
        except Exception as exc:
            record_fallback("llm_client_fallback", "ModelScope 初始化失败", meta={"error": str(exc)})
            return None, "modelscope"

    @staticmethod
    def _try_create_moonshot(trace_id: str | None) -> Tuple[Optional[BaseLLMClient], str]:
        # Moonshot 允许尝试初始化（部分客户端可能不需要 Key，或者 Key 在内部处理）
        # 但按照惯例还是检查环境变量
        try:
            return MoonshotLLMClient(
                model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
                logger=APILogger(trace_id=trace_id) if trace_id else None,
            ), "moonshot"
        except Exception as exc:
            record_fallback("llm_client_fallback", "Moonshot 初始化失败", meta={"error": str(exc)})
            return None, "moonshot"

    @staticmethod
    def _try_create_openrouter(trace_id: str | None) -> Tuple[Optional[BaseLLMClient], str]:
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            return None, "openrouter"
        try:
            return OpenRouterLLMClient(
                model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
                api_key=key,
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                logger=APILogger(trace_id=trace_id) if trace_id else None,
            ), "openrouter"
        except Exception as exc:
            record_fallback("llm_client_fallback", "OpenRouter 初始化失败", meta={"error": str(exc)})
            return None, "openrouter"

    @staticmethod
    def get_available_options(include_mock: bool = True) -> List[LLMOption]:
        """探测可用选项。"""
        opts: List[LLMOption] = [{"name": "auto", "available": True, "reason": None}]
        
        providers = [
            ("glm", "GLM_API_KEY"),
            ("bailian", "BAILIAN_API_KEY"),
            ("modelscope", "MODELSCOPE_API_KEY"),
            ("moonshot", "MOONSHOT_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
        ]
        
        for name, env_var in providers:
            has_key = bool(os.getenv(env_var))
            opts.append({
                "name": name,
                "available": has_key,
                "reason": None if has_key else f"缺少 {env_var}"
            })
            
        if include_mock:
            opts.append({"name": "mock", "available": True, "reason": None})
            
        return [opt for opt in opts if opt["available"]]
