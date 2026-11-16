"""配置、工具和提供商服务。

通过 ConfigPort 访问配置，不直接依赖旧 Agent/ 代码。
未注入端口时回退到 Legacy 适配器，保证可独立运行与向后兼容。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from kernel.ports.config import ConfigPort


class ConfigService:
    def __init__(self, *, config_port: ConfigPort | None = None) -> None:
        if config_port is None:
            from kernel.infrastructure import LegacyConfigAdapter

            config_port = LegacyConfigAdapter()
        self.config_port = config_port

    def get_config(self) -> Dict[str, object]:
        return self.config_port.get_config()

    def update_config(self, updates: Dict[str, object], persist: bool = True) -> Dict[str, object]:
        return self.config_port.update_config(updates, persist=persist)

    def get_config_doctor(self) -> Dict[str, object]:
        return self.config_port.get_config_doctor()

    def get_model_providers(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        # 旧的 ConfigPort 测试替身只实现无参版本，默认列表保持向后兼容。
        if include_disabled:
            return self.config_port.get_model_providers(include_disabled=True)
        return self.config_port.get_model_providers()

    def get_model_metadata(self, provider: str, model_name: str) -> Dict[str, Any]:
        return self.config_port.get_model_metadata(provider, model_name)

    def update_model_metadata(
        self,
        provider: str,
        model_name: str,
        limits: Dict[str, Any],
        capabilities: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.config_port.update_model_metadata(provider, model_name, limits, capabilities)

    def add_provider(
        self,
        label: str,
        base_url: str,
        protocol: str = "chat_completions",
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新增自定义（OpenAI 兼容）服务。"""
        return self.config_port.add_provider(label, base_url, protocol, api_key)

    def update_provider(
        self,
        provider: str,
        *,
        disabled: Optional[bool] = None,
        protocol: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """局部更新服务连接配置和启用状态。"""
        return self.config_port.update_provider(
            provider, disabled=disabled, protocol=protocol, base_url=base_url
        )

    def set_provider_disabled(self, provider: str, disabled: bool = True) -> Dict[str, Any]:
        """软删除 / 恢复内置服务。"""
        return self.config_port.set_provider_disabled(provider, disabled)

    def delete_provider(self, provider: str) -> Dict[str, Any]:
        """删除服务；内置服务软删除，自定义服务彻底移除。"""
        return self.config_port.delete_provider(provider)

    def discover_models(self, provider: str) -> Dict[str, Any]:
        """拉取服务商上游模型列表。"""
        return self.config_port.discover_models(provider)

    def get_tools(self) -> List[Dict[str, Any]]:
        return self.config_port.get_tools()

    def list_provider_keys(self) -> List[Dict[str, Any]]:
        """列出 Provider API Key 状态（脱敏）。"""
        return self.config_port.list_provider_keys()

    def set_provider_key(self, provider: str, value: Optional[str] = None) -> Dict[str, Any]:
        """写入 / 删除 Provider API Key。"""
        return self.config_port.set_provider_key(provider, value)

    def add_model(self, provider: str, model_name: str) -> None:
        """为 Provider 新增模型（幂等）。"""
        self.config_port.add_model(provider, model_name)

    def remove_model(self, provider: str, model_name: str) -> None:
        """从 Provider 删除模型（幂等）。"""
        self.config_port.remove_model(provider, model_name)
