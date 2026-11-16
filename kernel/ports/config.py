"""配置访问接口定义

定义内核读取/更新运行配置的抽象接口。

设计原则：只暴露 application 层真正需要的输入输出，
不把 legacy 的 dataclass（KernelConfig / ReviewConfig 等）泄漏到端口签名里，
因此这里统一使用普通的 ``Dict[str, Any]`` 与显式的 ``PromptLimits`` 值对象。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@dataclass
class ReviewPromptLimits:
    """审查提示词构建的字符/数量上限。

    对应旧实现 ``Agent.core.api.config.get_review_prompt_limits()`` 返回的字典，
    这里给出显式字段与默认值，避免调用方各自散落 magic number。
    """

    review_index_max_chars: int = 18_000
    intent_max_chars: int = 6_000
    context_bundle_max_items: int = 10
    context_bundle_max_chars: int = 45_000
    context_field_max_chars: int = 1_800
    caller_max_chars: int = 500
    tags_max_count: int = 6

    def to_dict(self) -> Dict[str, int]:
        """转换为字典形态，便于兼容既有按 key 取值的代码。"""
        return {
            "review_index_max_chars": self.review_index_max_chars,
            "intent_max_chars": self.intent_max_chars,
            "context_bundle_max_items": self.context_bundle_max_items,
            "context_bundle_max_chars": self.context_bundle_max_chars,
            "context_field_max_chars": self.context_field_max_chars,
            "caller_max_chars": self.caller_max_chars,
            "tags_max_count": self.tags_max_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewPromptLimits":
        """从字典构建，缺失或非法字段回退到默认值。"""
        defaults = cls()
        kwargs: Dict[str, int] = {}
        for field_name, default_value in defaults.to_dict().items():
            raw = data.get(field_name, default_value)
            try:
                kwargs[field_name] = max(1, int(raw))
            except (TypeError, ValueError):
                kwargs[field_name] = default_value
        return cls(**kwargs)


@runtime_checkable
class ConfigPort(Protocol):
    """配置访问接口。

    负责内核配置的读取与更新，以及模型提供商 / 工具清单等派生信息。
    """

    def get_config(self) -> Dict[str, Any]:
        """获取当前完整配置。"""
        ...

    def update_config(
        self,
        updates: Dict[str, Any],
        *,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """更新配置。

        Args:
            updates: 待更新的配置项
            persist: 是否落盘持久化

        Returns:
            更新后的配置
        """
        ...

    def get_config_doctor(self) -> Dict[str, Any]:
        """获取配置体检结果（缺失的 API Key、异常项等）。"""
        ...

    def get_review_prompt_limits(self) -> ReviewPromptLimits:
        """获取审查提示词构建的限制。"""
        ...

    def get_model_providers(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        """列出模型提供商及其可用模型。"""
        ...

    def get_model_metadata(self, provider: str, model_name: str) -> Dict[str, Any]:
        """读取已注册模型的有效元数据、基础值与手动覆盖。"""
        ...

    def update_model_metadata(
        self,
        provider: str,
        model_name: str,
        limits: Dict[str, Any],
        capabilities: Dict[str, Any],
    ) -> Dict[str, Any]:
        """整体替换两个手动覆盖对象；空对象恢复基础值。"""
        ...

    def add_provider(
        self,
        label: str,
        base_url: str,
        protocol: str = "chat_completions",
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新增 OpenAI 兼容的自定义服务。"""
        ...

    def update_provider(
        self,
        provider: str,
        *,
        disabled: Optional[bool] = None,
        protocol: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """局部更新服务连接配置和启用状态；None 保持原值。"""
        ...

    def set_provider_disabled(self, provider: str, disabled: bool = True) -> Dict[str, Any]:
        """软删除 / 恢复内置服务。"""
        ...

    def delete_provider(self, provider: str) -> Dict[str, Any]:
        """删除自定义服务；内置服务转为软删除。"""
        ...

    def discover_models(self, provider: str) -> Dict[str, Any]:
        """拉取服务商上游模型列表。"""
        ...

    def get_tools(self) -> List[Dict[str, Any]]:
        """列出可用工具定义。"""
        ...


__all__ = ["ConfigPort", "ReviewPromptLimits"]
