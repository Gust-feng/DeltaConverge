"""配置、工具和提供商服务。

通过 ConfigPort 访问配置，不直接依赖旧 Agent/ 代码。
未注入端口时回退到 Legacy 适配器，保证可独立运行与向后兼容。
"""

from __future__ import annotations

from typing import Any, Dict, List

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

    def get_model_providers(self) -> List[Dict[str, Any]]:
        return self.config_port.get_model_providers()

    def get_tools(self) -> List[Dict[str, Any]]:
        return self.config_port.get_tools()
