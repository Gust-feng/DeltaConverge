from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from Agent.core.api.factory import LLMFactory, ProviderConfig
from kernel.infrastructure.config_adapter import LegacyConfigAdapter


@pytest.fixture()
def saved_models(tmp_path, monkeypatch):
    """Use only temporary settings, fake credentials, and a client with no transport."""
    constructor = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    entries = {
        "disabled": {"disabled": True, "models": ["shared", "disabled-only"]},
        "empty": {"models": []},
        "missing": {"models": ["shared", "missing-only"]},
        "enabled": {"models": ["shared", {"id": "saved", "protocol": "responses"}, "vendor:model:v1"]},
    }
    providers = {}
    for name in entries:
        env = f"LLM_FACTORY_TEST_{name.upper()}_API_KEY"
        providers[name] = ProviderConfig(constructor, env, "https://example.invalid/v1", name)
        if name == "missing":
            monkeypatch.delenv(env, raising=False)
        else:
            monkeypatch.setenv(env, "offline-test-key")
        monkeypatch.delenv(env.replace("_API_KEY", "_BASE_URL"), raising=False)
    path = tmp_path / "models_config.json"
    path.write_text(json.dumps({"providers": entries}), encoding="utf-8")
    monkeypatch.setattr(LLMFactory, "_CONFIG_PATH", path)
    monkeypatch.setattr(LLMFactory, "_BASE_PROVIDERS", providers)
    monkeypatch.setattr(LLMFactory, "PROVIDERS", {})
    monkeypatch.setattr(LLMFactory, "_MODELS", {})
    monkeypatch.setattr(LLMFactory, "_MODEL_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "_PROVIDER_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "_DISABLED_PROVIDERS", set())
    LLMFactory.reload()
    return SimpleNamespace(path=path, constructor=constructor)


@pytest.mark.parametrize(
    ("preference", "model"),
    [
        ("enabled:saved", "saved"),
        ("saved", "saved"),
        ("enabled:vendor:model:v1", "vendor:model:v1"),
        ("vendor:model:v1", "vendor:model:v1"),
        ("enabled", "shared"),
        ("shared", "shared"),
        ("auto", "shared"),
    ],
)
def test_create_selects_only_saved_models_from_enabled_provider(saved_models, preference, model):
    client, provider = LLMFactory.create(preference)
    assert provider == "enabled"
    assert client.model == model
    assert client.provider_name == "enabled"
    saved_models.constructor.assert_called_once()


@pytest.mark.parametrize("preference", ["enabled:unsaved", "enabled:vendor:model:missing", "empty:unsaved", "missing:unsaved"])
def test_explicit_unsaved_model_is_rejected_before_client_construction(saved_models, preference):
    with pytest.raises(RuntimeError, match="not registered in models_config.json"):
        LLMFactory.create(preference)
    saved_models.constructor.assert_not_called()


@pytest.mark.parametrize("reload", [False, True])
def test_deleted_model_is_rejected_and_removed_from_public_lists(saved_models, reload):
    client, _ = LLMFactory.create("enabled:saved")
    assert client.protocol == "responses"
    saved_models.constructor.reset_mock()
    LLMFactory.remove_model("enabled", "saved")
    persisted = json.loads(saved_models.path.read_text(encoding="utf-8"))
    assert "saved" not in [m if isinstance(m, str) else m["id"] for m in persisted["providers"]["enabled"]["models"]]
    if reload:
        LLMFactory.reload()
    # Stale metadata must not authorize a deleted route, including before reload.
    with pytest.raises(RuntimeError, match="not registered"):
        LLMFactory.create("enabled:saved")
    with pytest.raises(RuntimeError, match="无法创建指定"):
        LLMFactory.create("saved")
    saved_models.constructor.assert_not_called()
    group = next(g for g in LLMFactory.get_available_options(False) if g["provider"] == "enabled")
    assert all(m["name"] != "enabled:saved" for m in group["models"])
    provider = next(p for p in LegacyConfigAdapter().get_model_providers() if p["id"] == "enabled")
    assert "saved" not in provider["models"]


@pytest.mark.parametrize("preference", ["disabled:shared", "disabled", "disabled-only"])
def test_disabled_provider_cannot_be_selected(saved_models, preference):
    with pytest.raises(RuntimeError):
        LLMFactory.create(preference)
    saved_models.constructor.assert_not_called()


def test_direct_client_creation_cannot_bypass_registry_or_disabled_state(saved_models):
    assert LLMFactory._create_client("disabled", None, "shared") is None
    assert LLMFactory._create_client("empty", None) is None
    with pytest.raises(RuntimeError, match="not registered"):
        LLMFactory._create_client("enabled", None, "unsaved")
    saved_models.constructor.assert_not_called()


@pytest.mark.parametrize("preference", ["empty", "missing", "missing-only"])
def test_provider_without_key_or_saved_models_cannot_be_selected(saved_models, preference):
    with pytest.raises(RuntimeError, match="无法创建指定"):
        LLMFactory.create(preference)
    saved_models.constructor.assert_not_called()


@pytest.mark.parametrize("empty_config", [False, True])
def test_auto_fails_without_usable_saved_models_and_never_falls_back_to_mock(saved_models, empty_config):
    config = {} if empty_config else {
        "disabled": {"disabled": True, "models": ["shared"]},
        "empty": {"models": []},
        "missing": {"models": ["shared"]},
        "enabled": {"models": []},
    }
    saved_models.path.write_text(json.dumps({"providers": config}), encoding="utf-8")
    LLMFactory.reload()
    with patch("Agent.core.api.factory.MockMoonshotClient") as mock_client:
        with pytest.raises(RuntimeError, match="未找到可用 LLM 客户端"):
            LLMFactory.create("auto")
        mock_client.assert_not_called()
    saved_models.constructor.assert_not_called()


def test_auto_continues_after_provider_initialization_failure(saved_models):
    # Make the first usable service fail, then use the next saved route.
    LLMFactory._DISABLED_PROVIDERS.clear()
    saved_models.constructor.side_effect = [RuntimeError("invalid local client settings"), SimpleNamespace()]
    client, provider = LLMFactory.create("auto")
    assert provider == "enabled"
    assert client.provider_name == "enabled"
    assert saved_models.constructor.call_count == 2


def test_public_provider_lists_share_local_availability_rules(saved_models):
    providers = {p["id"]: p for p in LegacyConfigAdapter().get_model_providers(include_disabled=True)}
    assert {name: (p["configured"], p["available"]) for name, p in providers.items()} == {
        "disabled": (True, False),
        "empty": (True, False),
        "missing": (False, False),
        "enabled": (True, True),
    }
    assert "disabled" in providers["disabled"]["error"]
    assert "no registered models" in providers["empty"]["error"]
    assert "LLM_FACTORY_TEST_MISSING_API_KEY" in providers["missing"]["error"]
    assert providers["enabled"]["error"] is None
    active = {p["id"] for p in LegacyConfigAdapter().get_model_providers()}
    groups = {g["provider"]: g for g in LLMFactory.get_available_options(False)}
    assert set(groups) == active == {"empty", "missing", "enabled"}
    for name, group in groups.items():
        provider = providers[name]
        assert group["is_active"] is provider["available"]
        assert [m["name"] for m in group["models"]] == [f"{name}:{m}" for m in provider["models"]]
        assert all(m["available"] is provider["available"] and m["reason"] == provider["error"] for m in group["models"])
    saved_models.constructor.assert_not_called()


def test_explicit_mock_remains_available_without_any_provider_key(saved_models, monkeypatch):
    for config in LLMFactory.PROVIDERS.values():
        monkeypatch.delenv(config.api_key_env, raising=False)
    with patch("Agent.core.api.factory.MockMoonshotClient", return_value=object()) as mock_client:
        client, provider = LLMFactory.create("mock")
    assert provider == "mock"
    assert client is mock_client.return_value
    mock_client.assert_called_once_with()
    assert LLMFactory.get_available_options()[-1]["provider"] == "mock"
    assert all(g["provider"] != "mock" for g in LLMFactory.get_available_options(False))
    saved_models.constructor.assert_not_called()
