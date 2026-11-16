from __future__ import annotations

import hashlib
import json
import asyncio
from types import SimpleNamespace

import pytest

from Agent.core.llm import model_metadata as mm
from Agent.core.api.factory import LLMFactory


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    data = {
        "deepseek/m": {
            "litellm_provider": "deepseek", "mode": "chat",
            "max_input_tokens": 12000, "max_output_tokens": 1000,
            "max_tokens": 77, "supports_reasoning": False,
            "supports_response_schema": True,
        },
        "zai/glm-test": {"litellm_provider": "zai", "mode": "chat", "max_input_tokens": 200000},
        "dashscope/qwen-test": {"litellm_provider": "dashscope", "mode": "chat", "max_input_tokens": 100000},
        "same-name": {"litellm_provider": "other", "max_input_tokens": 99999},
    }
    path = tmp_path / "models.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(mm.CATALOG_PATH_ENV, str(path))
    mm._read_catalog.cache_clear()
    yield path, data
    mm._read_catalog.cache_clear()


def test_bundled_snapshot_integrity_and_known_model(monkeypatch):
    monkeypatch.delenv(mm.CATALOG_PATH_ENV, raising=False)
    payload = mm.CATALOG_PATH.read_bytes()
    manifest = json.loads(mm.CATALOG_PATH.with_name("snapshot.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(payload).hexdigest() == manifest["sha256"]
    assert len(json.loads(payload)) == manifest["entries"]
    metadata = mm.get_model_metadata("deepseek", "deepseek-chat")
    assert metadata["catalog"] == "bundled"
    assert metadata["limits"]["max_input_tokens"] == 131072
    assert metadata["limits"]["max_output_tokens"] == 8192


def test_limits_keep_meaning_and_unknown_capabilities(catalog):
    metadata = mm.get_model_metadata("deepseek", "m")
    assert metadata["limits"] == {"max_input_tokens": 12000, "max_output_tokens": 1000}
    assert metadata["capabilities"] == {"reasoning": False, "structured_output": True, "json_schema": True}
    assert metadata["catalog"] == "user"


@pytest.mark.parametrize("provider,model,expected", [
    ("glm", "glm-test", "zai/glm-test"),
    ("bailian", "qwen-test", "dashscope/qwen-test"),
])
def test_channel_provider_mapping(catalog, provider, model, expected):
    assert mm.get_model_metadata(provider, model)["key"] == expected


def test_unknown_provider_and_ambiguous_model_stay_unknown(catalog):
    assert mm.get_model_metadata("gateway", "m") == {}
    assert mm.get_model_metadata("deepseek", "same-name") == {}
    assert mm.get_model_metadata("deepseek", "m:version") == {}


def test_explicit_alias_mapping(catalog):
    metadata = mm.get_model_metadata("gateway", "vendor:model:version", metadata_key="deepseek/m")
    assert metadata["key"] == "deepseek/m"


@pytest.mark.parametrize("contents", ["[]", "not json"])
def test_invalid_user_file_uses_bundle(tmp_path, monkeypatch, contents):
    path = tmp_path / "bad.json"
    path.write_text(contents, encoding="utf-8")
    monkeypatch.setenv(mm.CATALOG_PATH_ENV, str(path))
    assert mm.get_model_metadata("deepseek", "deepseek-chat")["catalog"] == "bundled"


def test_missing_user_file_uses_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv(mm.CATALOG_PATH_ENV, str(tmp_path / "missing.json"))
    assert mm.get_model_metadata("deepseek", "deepseek-chat")["catalog"] == "bundled"


def test_model_and_provider_overrides_take_precedence(catalog, monkeypatch):
    monkeypatch.setattr(LLMFactory, "_PROVIDER_SETTINGS", {
        "deepseek": {"limits": {"max_input_tokens": 9000}, "capabilities": {"reasoning": True}},
    })
    monkeypatch.setattr(LLMFactory, "_MODEL_SETTINGS", {
        "deepseek": {"m": {"limits": {"max_output_tokens": 500}, "capabilities": {"reasoning": False}}},
    })
    metadata = LLMFactory.get_model_metadata("deepseek", "m")
    assert metadata["limits"] == {"max_input_tokens": 9000, "max_output_tokens": 500}
    assert metadata["capabilities"] == {"reasoning": False, "structured_output": True, "json_schema": True}


@pytest.mark.parametrize("protocol,expected", [("chat_completions", False), ("responses", True)])
def test_output_capabilities_follow_protocol_and_model_override(catalog, monkeypatch, protocol, expected):
    monkeypatch.setattr(LLMFactory, "_PROVIDER_SETTINGS", {
        "deepseek": {
            "protocol": "chat_completions",
            "capabilities": {"json_object": True},
            "protocol_capabilities": {
                "chat_completions": {"json_schema": False},
                "responses": {"json_schema": True},
            },
        },
    })
    monkeypatch.setattr(LLMFactory, "_MODEL_SETTINGS", {
        "deepseek": {"m": {"protocol": protocol}},
    })
    capabilities = LLMFactory.get_model_metadata("deepseek", "m")["capabilities"]
    assert capabilities["json_schema"] is expected
    assert capabilities["structured_output"] is expected
    assert capabilities["json_object"] is True
    LLMFactory._MODEL_SETTINGS["deepseek"]["m"]["capabilities"] = {"structured_output": not expected}
    assert LLMFactory.get_model_metadata("deepseek", "m")["capabilities"]["json_schema"] is not expected


def test_factory_applies_metadata_without_rewriting_route(catalog, monkeypatch):
    monkeypatch.setattr(LLMFactory, "_ensure_models_loaded", lambda: None)
    monkeypatch.setattr(LLMFactory, "_MODELS", {"gateway": ["vendor:model:version"]})
    monkeypatch.setattr(LLMFactory, "_DISABLED_PROVIDERS", set())
    monkeypatch.setattr(LLMFactory, "_PROVIDER_SETTINGS", {"gateway": {"protocol": "responses"}})
    monkeypatch.setattr(LLMFactory, "_MODEL_SETTINGS", {
        "gateway": {"vendor:model:version": {"metadata_key": "deepseek/m"}},
    })
    monkeypatch.setattr(LLMFactory, "PROVIDERS", {"gateway": SimpleNamespace(
        api_key_env="METADATA_TEST_API_KEY", base_url="https://example.invalid/v1", client_class=lambda **kw: SimpleNamespace(**kw),
    )})
    monkeypatch.setenv("METADATA_TEST_API_KEY", "offline-placeholder")
    client = LLMFactory._create_client("gateway", None, "vendor:model:version")
    assert client.model == "vendor:model:version"
    assert client.base_url == "https://example.invalid/v1"
    assert client.protocol == "responses"
    assert client.model == "vendor:model:version"
    assert client.base_url == "https://example.invalid/v1"
    assert client.limits["max_input_tokens"] == 12000
    assert client.capabilities["structured_output"] is True
    assert client.capabilities["reasoning"] is False


def test_catalog_input_limit_reaches_existing_budget_check(catalog):
    from Agent.core.adapter.llm_adapter import OpenAIAdapter
    from Agent.core.stream.stream_processor import StreamProcessor

    client = SimpleNamespace(limits=mm.get_model_metadata("deepseek", "m")["limits"])
    adapter = OpenAIAdapter(client, StreamProcessor())
    with pytest.raises(ValueError, match="model input limit"):
        asyncio.run(adapter.complete([{"role": "user", "content": "x" * 13000}]))
    assert client.limits["max_input_tokens"] == 12000


def test_metadata_reaches_settings_endpoint_contract(catalog, monkeypatch):
    from kernel.infrastructure.config_adapter import LegacyConfigAdapter
    monkeypatch.setattr(LLMFactory, "_ensure_models_loaded", lambda: None)
    monkeypatch.setattr(LLMFactory, "_MODEL_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "_PROVIDER_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "_MODELS", {"deepseek": ["m"]})
    monkeypatch.setattr(LLMFactory, "PROVIDERS", {"deepseek": SimpleNamespace(
        api_key_env="METADATA_TEST_API_KEY", label="DeepSeek", base_url="https://example.invalid/v1",
    )})
    provider = LegacyConfigAdapter().get_model_providers()[0]
    assert provider["models"] == ["m"]
    assert provider["model_details"][0]["limits"]["max_input_tokens"] == 12000
