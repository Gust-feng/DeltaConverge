"""模型管理 API 模块。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pathlib import Path

from Agent.core.api.factory import LLMFactory


class ModelAPI:
    """模型管理 API（静态方法接口）。"""
    
    @staticmethod
    def list_models() -> Dict[str, List[str]]:
        """获取所有厂商的模型列表。"""
        # 确保 LLMFactory 加载了配置
        LLMFactory._ensure_models_loaded()
        return LLMFactory._MODELS
    
    @staticmethod
    def add_model(provider: str, model_name: str) -> Dict[str, Any]:
        """添加模型到指定厂商。"""
        LLMFactory._ensure_models_loaded()
        
        if provider not in LLMFactory.PROVIDERS:
            return {"success": False, "error": f"Unknown provider: {provider}"}
        
        if provider not in LLMFactory._MODELS:
            LLMFactory._MODELS[provider] = []
            
        if model_name in LLMFactory._MODELS[provider]:
            return {"success": False, "error": f"Model '{model_name}' already exists for {provider}"}
            
        LLMFactory._MODELS[provider].append(model_name)
        ModelAPI._save_config()
        
        return {"success": True, "models": LLMFactory._MODELS[provider]}
    
    @staticmethod
    def delete_model(provider: str, model_name: str) -> Dict[str, Any]:
        """从指定厂商删除模型。"""
        LLMFactory._ensure_models_loaded()
        
        if provider not in LLMFactory._MODELS:
            return {"success": False, "error": f"No models found for provider: {provider}"}
            
        if model_name not in LLMFactory._MODELS[provider]:
            return {"success": False, "error": f"Model '{model_name}' not found for {provider}"}
            
        LLMFactory._MODELS[provider].remove(model_name)
        ModelAPI._save_config()
        
        return {"success": True, "models": LLMFactory._MODELS[provider]}

    @staticmethod
    def get_providers() -> List[Dict[str, str]]:
        """获取支持的厂商列表。"""
        return [
            {"id": pid, "label": cfg.label}
            for pid, cfg in LLMFactory.PROVIDERS.items()
        ]

    @staticmethod
    def _save_config():
        """保存配置到文件。"""
        try:
            with open(LLMFactory._CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(LLMFactory._MODELS, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving models config: {e}")
            raise RuntimeError(f"Failed to save models config: {e}")
