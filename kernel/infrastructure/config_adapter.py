"""Legacy 配置适配器

包装旧内核的 ``Agent.core.api.config`` 与 ``Agent.core.api.factory`` /
``Agent.core.api.tools``，实现新的 ConfigPort 接口。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlsplit

from kernel.ports.config import ConfigPort, ReviewPromptLimits

logger = logging.getLogger(__name__)


def _mask_secret(value: str) -> str:
    """脱敏展示：前 4 + ``****`` + 后 4；过短的值全部打星。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}****{text[-4:]}"


class LegacyConfigAdapter(ConfigPort):
    """包装旧配置 API 的适配器。"""

    def __init__(self, root: Optional[Union[str, Path]] = None) -> None:
        # 项目根目录；默认指向仓库根（kernel/infrastructure/config_adapter.py 上两级）。
        self._root = Path(root) if root is not None else Path(__file__).resolve().parents[2]

    @property
    def env_file(self) -> Path:
        """项目根 ``.env`` 路径。"""
        return self._root / ".env"

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

    def get_model_providers(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        """列出模型提供商及其可用模型。"""
        from Agent.core.api.factory import LLMFactory

        LLMFactory._ensure_models_loaded()
        items: List[Dict[str, Any]] = []
        for provider_id, config in LLMFactory.PROVIDERS.items():
            models = list(LLMFactory._MODELS.get(provider_id, []))
            configured = bool(os.getenv(config.api_key_env))
            base_url_env = f"{config.api_key_env.split('_API_KEY')[0]}_BASE_URL"
            provider_settings = LLMFactory._PROVIDER_SETTINGS.get(provider_id, {})
            disabled = provider_id in LLMFactory._DISABLED_PROVIDERS
            if disabled and not include_disabled:
                continue
            unavailable_reason = LLMFactory._provider_unavailable_reason(provider_id)
            items.append(
                {
                    "id": provider_id,
                    "label": config.label,
                    "available": unavailable_reason is None,
                    "configured": configured,
                    "model_count": len(models),
                    "models": models,
                    "model_details": [
                        {"id": model, **LLMFactory.get_model_metadata(provider_id, model)}
                        for model in models
                    ],
                    "api_key_env": config.api_key_env,
                    "base_url": os.getenv(base_url_env, config.base_url),
                    # 当前连接协议来自 models_config.json 的 provider 级配置。
                    "protocol": provider_settings.get("protocol", "chat_completions"),
                    "custom": bool(provider_settings.get("custom")),
                    "added": bool(provider_settings.get("added") or provider_settings.get("custom") or configured),
                    "disabled": disabled,
                    "error": unavailable_reason,
                }
            )
        return items

    def list_provider_keys(self) -> List[Dict[str, Any]]:
        """列出各 Provider 的 API Key 配置状态（脱敏）。

        读取顺序：项目根 ``.env`` → 进程环境变量，与 legacy 一致。
        """
        from Agent.core.api.factory import LLMFactory
        from dotenv import dotenv_values

        LLMFactory._ensure_models_loaded()
        env_values = dotenv_values(self.env_file) if self.env_file.exists() else {}
        items: List[Dict[str, Any]] = []
        for provider, config in LLMFactory.PROVIDERS.items():
            raw = env_values.get(config.api_key_env)
            if not raw:
                raw = os.environ.get(config.api_key_env) or ""
            raw = str(raw).strip()
            items.append(
                {
                    "provider": provider,
                    "label": config.label,
                    "configured": bool(raw),
                    "masked": _mask_secret(raw),
                }
            )
        return items

    def set_provider_key(self, provider: str, value: Optional[str] = None) -> Dict[str, Any]:
        """写入 / 删除 Provider 的 API Key，并同步进程环境变量。"""
        from Agent.core.api.factory import LLMFactory
        from dotenv import set_key, unset_key

        LLMFactory._ensure_models_loaded()
        provider = str(provider or "").strip()
        config = LLMFactory.PROVIDERS.get(provider)
        if config is None:
            raise ValueError("Unknown provider")

        raw_value = str(value or "")
        if "\n" in raw_value or "\r" in raw_value:
            raise ValueError("Invalid value")
        new_value = raw_value.strip()

        if new_value:
            set_key(str(self.env_file), config.api_key_env, new_value)
            os.environ[config.api_key_env] = new_value
        else:
            unset_key(str(self.env_file), config.api_key_env)
            os.environ.pop(config.api_key_env, None)

        return {"success": True, "provider": provider, "configured": bool(new_value)}

    def add_model(self, provider: str, model_name: str) -> None:
        """新增 Provider 模型；重复添加按幂等成功。"""
        from Agent.core.api.factory import LLMFactory

        LLMFactory._ensure_models_loaded()
        provider = str(provider or "").strip()
        model_name = str(model_name or "").strip()
        if provider not in LLMFactory.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        if not model_name:
            raise ValueError("model required")
        LLMFactory.add_model(provider, model_name)

    def remove_model(self, provider: str, model_name: str) -> None:
        """删除 Provider 模型；不存在时按幂等成功。"""
        from Agent.core.api.factory import LLMFactory

        LLMFactory._ensure_models_loaded()
        provider = str(provider or "").strip()
        model_name = str(model_name or "").strip()
        if provider not in LLMFactory.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        if not model_name:
            raise ValueError("model required")
        LLMFactory.remove_model(provider, model_name)

    def _model_metadata_snapshot(self, provider: str, model_name: str):
        """Locate a saved model in a disk snapshot, without changing factory caches."""
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider required")
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("model_name required")
        config = self._read_models_config()
        providers = config.get("providers", config)
        if provider not in providers:
            raise ValueError(f"Unknown provider: {provider}")
        entry = providers[provider]
        settings = {"models": entry} if isinstance(entry, list) else entry
        if not isinstance(settings, dict):
            raise ValueError(f"Provider 配置不可用: {provider}")
        models = settings.get("models", [])
        for index, model in enumerate(models):
            if (model if isinstance(model, str) else model.get("id")) == model_name:
                return config, settings, models, index, ({"id": model} if isinstance(model, str) else model)
        raise ValueError(f"Model '{provider}:{model_name}' is not registered in models_config.json.")

    def get_model_metadata(self, provider: str, model_name: str) -> Dict[str, Any]:
        """Return effective values and the separate manual override layer, locally."""
        from Agent.core.api.factory import LLMFactory

        _, settings, _, _, model = self._model_metadata_snapshot(provider, model_name)
        return {"id": model_name, **LLMFactory._merge_model_metadata(provider, model_name, settings, model)}

    def update_model_metadata(
        self,
        provider: str,
        model_name: str,
        limits: Dict[str, Any],
        capabilities: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Replace manual overrides only; validate before writing and then reload."""
        from Agent.core.api.factory import LLMFactory

        allowed_limits = {"context_window", "max_input_tokens", "max_output_tokens"}
        allowed_capabilities = {"reasoning", "tool_calling", "vision", "json_schema", "json_object"}
        if not isinstance(limits, dict) or set(limits) - allowed_limits:
            raise ValueError("limits 仅支持 context_window、max_input_tokens、max_output_tokens")
        if not isinstance(capabilities, dict) or set(capabilities) - allowed_capabilities:
            raise ValueError("capabilities 仅支持 reasoning、tool_calling、vision、json_schema、json_object")
        for name, value in limits.items():
            if type(value) is not int or not 0 < value <= 9007199254740991:
                raise ValueError(f"{name} 必须是 JS 安全整数范围内的正整数")
        for name, value in capabilities.items():
            if type(value) is not bool:
                raise ValueError(f"{name} 必须是布尔值")

        config, settings, models, index, model = self._model_metadata_snapshot(provider, model_name)
        updated = dict(model)
        if limits or capabilities:
            updated["metadata_overrides"] = {"limits": dict(limits), "capabilities": dict(capabilities)}
        else:
            updated.pop("metadata_overrides", None)
        metadata = LLMFactory._merge_model_metadata(provider, model_name, settings, updated)
        effective_limits = metadata["limits"]
        context_window = effective_limits.get("context_window")
        for name in ("max_input_tokens", "max_output_tokens"):
            value = effective_limits.get(name)
            if context_window is not None and value is not None and value > context_window:
                raise ValueError(f"{name} 不能超过 context_window")

        if updated != model:
            models[index] = updated
            self._write_models_config(config)
            LLMFactory.reload()
        return {"id": model_name, **metadata}

    # ── 服务商管理：自定义服务 / 软删除 / 上游模型发现 ──────────

    def _models_config_path(self) -> Path:
        from Agent.core.api.factory import LLMFactory

        return Path(LLMFactory._CONFIG_PATH)

    def _read_models_config(self) -> Dict[str, Any]:
        with open(self._models_config_path(), encoding="utf-8") as handle:
            return json.load(handle)

    def _write_models_config(self, config: Dict[str, Any]) -> None:
        path = self._models_config_path()
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _provider_entries(config: Dict[str, Any]) -> Dict[str, Any]:
        providers = config.get("providers")
        if not isinstance(providers, dict):
            raise ValueError("models_config.json 格式不受支持")
        return providers

    def _provider_key(self, api_key_env: str) -> str:
        from dotenv import dotenv_values

        values = dotenv_values(self.env_file) if self.env_file.exists() else {}
        return str(values.get(api_key_env) or os.environ.get(api_key_env) or "").strip()

    def _active_provider_ids(self) -> List[str]:
        from Agent.core.api.factory import LLMFactory

        return [item for item in LLMFactory.PROVIDERS if item not in LLMFactory._DISABLED_PROVIDERS]

    def add_provider(
        self,
        label: str,
        base_url: str,
        protocol: str = "chat_completions",
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """新增一个 OpenAI 兼容的自定义服务。"""
        from Agent.core.api.factory import LLMFactory

        LLMFactory._ensure_models_loaded()

        label = str(label or "").strip()
        base_url = str(base_url or "").strip().rstrip("/")
        protocol = str(protocol or "chat_completions").strip()
        if not label:
            raise ValueError("服务名称不能为空")
        if len(label) > 80:
            raise ValueError("服务名称过长")
        if not re.match(r"^https?://", base_url, flags=re.IGNORECASE):
            raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
        if protocol not in {"chat_completions", "responses"}:
            raise ValueError("协议仅支持 chat_completions 或 responses")

        config = self._read_models_config()
        providers = self._provider_entries(config)

        index = 1
        while f"custom_{index}" in providers:
            index += 1
        provider_id = f"custom_{index}"
        api_key_env = f"CUSTOM_{provider_id.upper()}_API_KEY"

        providers[provider_id] = {
            "label": label,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "protocol": protocol,
            "models": [],
            "custom": True,
            "added": True,
        }
        self._write_models_config(config)
        LLMFactory.reload()

        key = str(api_key or "").strip()
        if key:
            self.set_provider_key(provider_id, key)

        items = self.get_model_providers(include_disabled=True)
        return next((item for item in items if item["id"] == provider_id), {"id": provider_id, "label": label})

    def update_provider(
        self,
        provider: str,
        *,
        disabled: Optional[bool] = None,
        protocol: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """持久化服务局部更新，保留模型及其它设置并刷新工厂。"""
        from Agent.core.api.factory import LLMFactory

        LLMFactory._ensure_models_loaded()
        provider = str(provider or "").strip()
        provider_config = LLMFactory.PROVIDERS.get(provider)
        if provider_config is None:
            raise ValueError(f"Unknown provider: {provider}")

        # 所有检查先完成，避免混合更新因某一字段非法而部分落盘。
        if protocol is not None:
            protocol = str(protocol).strip()
            if protocol not in {"chat_completions", "responses"}:
                raise ValueError("协议仅支持 chat_completions 或 responses")
        if base_url is not None:
            base_url = str(base_url).strip().rstrip("/")
            try:
                parsed = urlsplit(base_url)
                valid_url = (
                    parsed.scheme.lower() in {"http", "https"}
                    and bool(parsed.hostname)
                    and not parsed.query
                    and not parsed.fragment
                    and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in base_url)
                )
                parsed.port  # 同时校验端口是否合法。
            except ValueError:
                valid_url = False
            if not valid_url:
                raise ValueError("Base URL 必须是有效的 http:// 或 https:// 地址，且不能包含查询参数或片段")
            base_url_env = f"{provider_config.api_key_env.split('_API_KEY')[0]}_BASE_URL"
            override = os.getenv(base_url_env)
            if override is not None and override.strip().rstrip("/") != base_url:
                raise ValueError(
                    f"Base URL 被环境变量 {base_url_env} 覆盖，请先修改或移除该环境变量后再保存"
                )
        if disabled is not None and not isinstance(disabled, bool):
            raise ValueError("disabled 必须是布尔值")
        if disabled and provider not in LLMFactory._DISABLED_PROVIDERS:
            if len(self._active_provider_ids()) <= 1:
                raise ValueError("至少保留一个服务")

        config = self._read_models_config()
        providers = self._provider_entries(config)
        entry = providers.get(provider)
        if isinstance(entry, list):
            # 兼容旧的纯模型数组；转换时保留模型顺序和内容。
            entry = {"models": entry}
        if not isinstance(entry, dict):
            raise ValueError(f"Provider 配置不可用: {provider}")

        if protocol is not None:
            entry["protocol"] = protocol
        if base_url is not None:
            entry["base_url"] = base_url
        if disabled is True:
            entry["disabled"] = True
        elif disabled is False:
            entry.pop("disabled", None)
            entry["added"] = True

        if disabled is not None or protocol is not None or base_url is not None:
            providers[provider] = entry
            self._write_models_config(config)
            LLMFactory.reload()

        result = {"success": True, "provider": provider, "disabled": entry.get("disabled") is True}
        if protocol is not None:
            result["protocol"] = protocol
        if base_url is not None:
            result["base_url"] = base_url
        return result

    def set_provider_disabled(self, provider: str, disabled: bool = True) -> Dict[str, Any]:
        """兼容原有软删除 / 恢复调用。"""
        return self.update_provider(provider, disabled=disabled)

    def delete_provider(self, provider: str) -> Dict[str, Any]:
        """删除自定义服务；内置服务改为软删除以支持恢复。"""
        from Agent.core.api.factory import LLMFactory
        from dotenv import unset_key

        LLMFactory._ensure_models_loaded()
        provider = str(provider or "").strip()
        if provider not in LLMFactory.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        if len(self._active_provider_ids()) <= 1 and provider not in LLMFactory._DISABLED_PROVIDERS:
            raise ValueError("至少保留一个服务")

        config = self._read_models_config()
        providers = self._provider_entries(config)
        entry = providers.get(provider)
        if not isinstance(entry, dict):
            raise ValueError(f"Provider 配置不可用: {provider}")

        if not entry.get("custom"):
            result = self.set_provider_disabled(provider, True)
            return {**result, "deleted": False}

        api_key_env = str(entry.get("api_key_env") or "")
        providers.pop(provider, None)
        self._write_models_config(config)
        if api_key_env:
            if self.env_file.exists():
                unset_key(str(self.env_file), api_key_env)
            os.environ.pop(api_key_env, None)
        LLMFactory.reload()
        return {"success": True, "provider": provider, "deleted": True, "disabled": False}

    def discover_models(self, provider: str) -> Dict[str, Any]:
        """请求服务商 /models，返回可用于「获取模型」的上游模型 ID。"""
        from Agent.core.api.factory import LLMFactory
        from Agent.core.llm.client import default_httpx_verify

        LLMFactory._ensure_models_loaded()
        provider = str(provider or "").strip()
        config = LLMFactory.PROVIDERS.get(provider)
        if config is None:
            raise ValueError(f"Unknown provider: {provider}")
        if provider in LLMFactory._DISABLED_PROVIDERS:
            raise ValueError("该服务已被移除，请先恢复")

        api_key = self._provider_key(config.api_key_env)
        if not api_key:
            raise ValueError("请先配置 API Key")

        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise ValueError("httpx 未安装，无法获取模型列表") from exc

        base_url_env = f"{config.api_key_env.split('_API_KEY')[0]}_BASE_URL"
        base_url = str(os.getenv(base_url_env, config.base_url) or "").strip().rstrip("/")
        for suffix in ("/chat/completions", "/responses"):
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]
        if not base_url:
            raise ValueError("Base URL 未配置")

        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0, connect=10.0),
                verify=default_httpx_verify(),
                follow_redirects=True,
            ) as client:
                response = client.get(f"{base_url}/models", headers=headers)
        except httpx.TimeoutException as exc:
            raise ValueError("获取模型超时，请检查网络或 Base URL") from exc
        except httpx.HTTPError as exc:
            raise ValueError(f"获取模型失败: {exc}") from exc

        if response.status_code in (401, 403):
            raise ValueError("鉴权失败，请检查 API Key")
        if response.status_code >= 400:
            raise ValueError(f"服务商返回 HTTP {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("服务商返回内容不是合法 JSON") from exc

        models = self._extract_model_ids(payload)
        return {"provider": provider, "models": models, "base_url": base_url}

    @staticmethod
    def _extract_model_ids(payload: Any) -> List[str]:
        items: Any = payload
        if isinstance(payload, dict):
            items = payload.get("data")
            if items is None:
                items = payload.get("models")
        if not isinstance(items, list):
            raise ValueError("服务商未返回模型列表")

        found: set[str] = set()
        for item in items:
            if isinstance(item, str):
                model_id = item
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name") or item.get("model")
            else:
                continue
            if isinstance(model_id, str) and model_id.strip():
                found.add(model_id.strip())
        if not found:
            raise ValueError("服务商未返回任何模型")
        return sorted(found, key=str.lower)

    def get_tools(self) -> List[Dict[str, Any]]:
        """列出可用工具定义。"""
        from Agent.core.api.tools import ToolAPI

        return ToolAPI.list_tools()


__all__ = ["LegacyConfigAdapter"]
