"""Model metadata editing uses isolated local configuration and no upstream I/O."""
from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from Agent.core.api.factory import LLMFactory, ProviderConfig
from Agent.core.llm import model_metadata as mm
from adapters.web.app import create_app
from adapters.web.dependencies import get_facade
from kernel.application.facade import KernelFacade
from kernel.application.services.config_service import ConfigService
from kernel.infrastructure.config_adapter import LegacyConfigAdapter


MODEL = "vendor/model:revision/with:colon"
UNKNOWN = "opaque/unknown:rev"
URL = "/api/v2/models/metadata"


def request(transport, method, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, URL, **kwargs)

    return asyncio.run(run())


def patch(env, limits=None, capabilities=None, **identity):
    return request(env.transport, "PATCH", json={
        "provider": "gateway", "model_name": MODEL,
        "limits": {} if limits is None else limits,
        "capabilities": {} if capabilities is None else capabilities,
        **identity,
    })


@pytest.fixture
def env(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "deepseek/known": {
            "litellm_provider": "deepseek", "mode": "chat",
            "context_window": 12000, "max_input_tokens": 10000, "max_output_tokens": 1000,
            "supports_reasoning": True, "supports_function_calling": True,
            "supports_vision": False, "supports_response_schema": True,
        },
    }), encoding="utf-8")
    monkeypatch.setenv(mm.CATALOG_PATH_ENV, str(catalog))
    mm._read_catalog.cache_clear()
    original = {
        "config_extra": {"keep": True},
        "providers": {
            "gateway": {
                "label": "Local test", "api_key_env": "METADATA_SETTINGS_TEST_API_KEY",
                "base_url": "https://example.invalid/v1", "protocol": "responses",
                "limits": {"context_window": 10000, "max_input_tokens": 9000, "max_output_tokens": 2000},
                "capabilities": {"reasoning": True, "tool_calling": True, "json_schema": False},
                "protocol_capabilities": {"responses": {"vision": True, "json_schema": False}},
                "provider_extra": {"keep": [1, 2]},
                "models": [
                    {
                        "id": MODEL, "protocol": "chat_completions", "metadata_key": "deepseek/known",
                        "limits": {"max_input_tokens": 7000},
                        "capabilities": {"reasoning": False, "tool_calling": True},
                        "protocol_capabilities": {"chat_completions": {"json_schema": True, "json_object": False}},
                        "model_extra": {"keep": [3, 4]},
                    },
                    UNKNOWN,
                ],
            },
            "deepseek": ["known"],
            "legacy": ["legacy/model:rev"],
            "disabled": {"disabled": True, "models": ["offline/model:rev"]},
            "empty": {"models": []},
        },
    }
    path = tmp_path / "models_config.json"
    path.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fake = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setattr(LLMFactory, "_CONFIG_PATH", path)
    monkeypatch.setattr(LLMFactory, "_BASE_PROVIDERS", {
        "gateway": ProviderConfig(fake, "METADATA_SETTINGS_TEST_API_KEY", "https://example.invalid/v1", "Local test"),
    })
    for name, value in {
        "PROVIDERS": {}, "_MODELS": {}, "_MODEL_SETTINGS": {},
        "_PROVIDER_SETTINGS": {}, "_DISABLED_PROVIDERS": set(),
    }.items():
        monkeypatch.setattr(LLMFactory, name, value)
    monkeypatch.setenv("METADATA_SETTINGS_TEST_API_KEY", "offline-test-placeholder")
    LLMFactory.reload()
    adapter = LegacyConfigAdapter(root=tmp_path)
    service = ConfigService(config_port=adapter)
    # Only the config service is needed; use the actual facade delegation methods.
    facade = object.__new__(KernelFacade)
    facade.config_service = service
    app = create_app()
    app.dependency_overrides[get_facade] = lambda: facade
    result = SimpleNamespace(
        path=path, original=original, adapter=adapter, service=service,
        transport=httpx.ASGITransport(app=app), monkeypatch=monkeypatch,
    )
    yield result
    mm._read_catalog.cache_clear()


def snapshot():
    return copy.deepcopy({
        name: getattr(LLMFactory, name)
        for name in ("_MODELS", "_MODEL_SETTINGS", "_PROVIDER_SETTINGS", "_DISABLED_PROVIDERS", "PROVIDERS")
    })


def assert_unchanged(env, before_file, before_cache):
    assert env.path.read_bytes() == before_file
    assert snapshot() == before_cache


def test_get_returns_effective_defaults_and_empty_overrides(env):
    response = request(env.transport, "GET", params={"provider": "gateway", "model_name": MODEL})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == MODEL
    assert data["limits"] == {"context_window": 10000, "max_input_tokens": 7000, "max_output_tokens": 2000}
    assert data["capabilities"]["reasoning"] is False
    assert data["capabilities"]["json_schema"] is True
    assert data["capabilities"]["structured_output"] is True
    assert data["capabilities"]["vision"] is False
    assert data["defaults"] == {"limits": data["limits"], "capabilities": data["capabilities"]}
    assert data["overrides"] == {"limits": {}, "capabilities": {}}
    assert data["source"] == "litellm"
    assert data["catalog"] == "user"


def test_patch_persists_separate_layer_reloads_factory_and_client(env):
    limits = {"context_window": 8000, "max_input_tokens": 6000, "max_output_tokens": 500}
    capabilities = {"reasoning": False, "tool_calling": False, "vision": False, "json_schema": False, "json_object": False}
    defaults = env.adapter.get_model_metadata("gateway", MODEL)["defaults"]
    response = patch(env, limits, capabilities)
    assert response.status_code == 200
    data = response.json()
    assert data["limits"] == limits
    assert data["overrides"] == {"limits": limits, "capabilities": capabilities}
    assert data["defaults"] == defaults
    assert data["capabilities"] == {**capabilities, "structured_output": False}
    saved = json.loads(env.path.read_text(encoding="utf-8"))
    expected = copy.deepcopy(env.original)
    expected["providers"]["gateway"]["models"][0]["metadata_overrides"] = data["overrides"]
    assert saved == expected
    # Immediate creation proves PATCH refreshed the loaded factory, not just disk.
    client, provider = LLMFactory.create(f"gateway:{MODEL}")
    assert provider == "gateway"
    assert client.model == MODEL
    assert client.protocol == "chat_completions"
    assert client.limits == limits
    assert client.capabilities == data["capabilities"]
    LLMFactory.reload()
    assert LLMFactory.get_model_metadata("gateway", MODEL) == {key: value for key, value in data.items() if key != "id"}
    assert env.adapter.get_model_providers()[0]["model_details"][0] == data


def test_reset_preserves_all_existing_fields_and_protocol(env):
    defaults = env.adapter.get_model_metadata("gateway", MODEL)["defaults"]
    assert patch(env, {"max_output_tokens": 500}, {"json_schema": False}).status_code == 200
    response = patch(env)
    assert response.status_code == 200
    data = response.json()
    assert data["overrides"] == {"limits": {}, "capabilities": {}}
    assert data["defaults"] == defaults
    assert data["limits"] == defaults["limits"]
    assert data["capabilities"] == defaults["capabilities"]
    assert json.loads(env.path.read_text(encoding="utf-8")) == env.original
    assert LLMFactory._MODEL_SETTINGS["gateway"][MODEL] == env.original["providers"]["gateway"]["models"][0]
    client, _ = LLMFactory.create(f"gateway:{MODEL}")
    assert client.protocol == "chat_completions"
    assert client.capabilities["structured_output"] is True


def test_replacement_drops_previous_manual_fields_and_retains_baseline(env):
    assert patch(env, {"max_output_tokens": 500}, {"reasoning": True, "vision": True}).status_code == 200
    response = patch(env, {"max_input_tokens": 6000}, {"json_object": True})
    assert response.status_code == 200
    data = response.json()
    assert data["overrides"] == {"limits": {"max_input_tokens": 6000}, "capabilities": {"json_object": True}}
    assert data["limits"]["max_output_tokens"] == 2000
    assert data["capabilities"]["reasoning"] is False
    assert data["capabilities"]["vision"] is False
    assert data["capabilities"]["json_object"] is True


@pytest.mark.parametrize("provider,model_name", [
    ("gateway", MODEL), ("gateway", UNKNOWN), ("legacy", "legacy/model:rev"),
])
def test_empty_reset_without_override_does_not_write_or_reload(env, monkeypatch, provider, model_name):
    before_file, before_cache = env.path.read_bytes(), snapshot()
    monkeypatch.setattr(env.adapter, "_write_models_config", lambda *_: pytest.fail("unexpected write"))
    monkeypatch.setattr(LLMFactory, "reload", lambda: pytest.fail("unexpected reload"))
    result = env.adapter.update_model_metadata(provider, model_name, {}, {})
    assert result["overrides"] == {"limits": {}, "capabilities": {}}
    assert_unchanged(env, before_file, before_cache)


def test_catalog_unknown_model_can_be_overridden_and_string_converts_only_on_save(env):
    before = env.adapter.get_model_metadata("gateway", UNKNOWN)
    assert "source" not in before
    assert before["overrides"] == {"limits": {}, "capabilities": {}}
    response = patch(env, {"max_input_tokens": 8000}, {"vision": True, "reasoning": False}, model_name=UNKNOWN)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == UNKNOWN
    assert data["defaults"] == before["defaults"]
    assert data["capabilities"]["vision"] is True
    saved = json.loads(env.path.read_text(encoding="utf-8"))
    assert saved["providers"]["gateway"]["models"][0] == env.original["providers"]["gateway"]["models"][0]
    assert saved["providers"]["gateway"]["models"][1] == {"id": UNKNOWN, "metadata_overrides": data["overrides"]}
    assert LLMFactory.create(f"gateway:{UNKNOWN}")[0].limits["max_input_tokens"] == 8000
    assert patch(env, model_name=UNKNOWN).status_code == 200
    assert json.loads(env.path.read_text(encoding="utf-8"))["providers"]["gateway"]["models"][1] == {"id": UNKNOWN}


@pytest.mark.parametrize("wrapped", [True, False])
def test_legacy_provider_list_and_root_mapping_persist_and_reload(env, wrapped):
    if not wrapped:
        env.path.write_text(json.dumps(env.original["providers"]), encoding="utf-8")
        LLMFactory.reload()
    response = patch(env, {"context_window": 1000, "max_input_tokens": 800, "max_output_tokens": 200},
                     {"tool_calling": False}, provider="legacy", model_name="legacy/model:rev")
    assert response.status_code == 200
    saved = json.loads(env.path.read_text(encoding="utf-8"))
    providers = saved["providers"] if wrapped else saved
    assert isinstance(providers["legacy"], list)
    assert providers["legacy"] == [{"id": "legacy/model:rev", "metadata_overrides": response.json()["overrides"]}]
    assert LLMFactory._MODELS["legacy"] == ["legacy/model:rev"]
    assert LLMFactory.get_model_metadata("legacy", "legacy/model:rev")["limits"]["context_window"] == 1000
    # Existing add/remove operations must preserve the newly supported object entries.
    LLMFactory.add_model("legacy", "another/model:rev")
    LLMFactory.reload()
    assert LLMFactory.get_model_metadata("legacy", "legacy/model:rev")["capabilities"]["tool_calling"] is False
    LLMFactory.remove_model("legacy", "another/model:rev")
    LLMFactory.reload()
    assert LLMFactory._MODELS["legacy"] == ["legacy/model:rev"]
    assert patch(env, provider="legacy", model_name="legacy/model:rev").status_code == 200
    saved = json.loads(env.path.read_text(encoding="utf-8"))
    providers = saved["providers"] if wrapped else saved
    assert providers["legacy"] == [{"id": "legacy/model:rev"}]


def test_disabled_provider_edits_locally_without_key_or_client(env, monkeypatch):
    monkeypatch.setattr(LLMFactory, "_create_client", lambda *_: pytest.fail("metadata editing created a client"))
    monkeypatch.setattr(env.adapter, "_provider_key", lambda *_: pytest.fail("metadata editing read credentials"))
    response = request(env.transport, "GET", params={"provider": "disabled", "model_name": "offline/model:rev"})
    assert response.status_code == 200
    assert response.json()["defaults"] == {"limits": {}, "capabilities": {}}
    response = patch(env, {"context_window": 4096}, {"reasoning": False},
                     provider="disabled", model_name="offline/model:rev")
    assert response.status_code == 200
    assert response.json()["capabilities"] == {"reasoning": False}
    assert "disabled" in LLMFactory._DISABLED_PROVIDERS
    assert json.loads(env.path.read_text(encoding="utf-8"))["providers"]["disabled"]["disabled"] is True


@pytest.mark.parametrize("limits,capabilities", [
    ({"context_window": True}, {}), ({"context_window": False}, {}),
    ({"max_input_tokens": 0}, {}), ({"max_output_tokens": -1}, {}),
    ({"context_window": 12.5}, {}), ({"context_window": 10000.0}, {}),
    ({"context_window": "10000"}, {}), ({"context_window": None}, {}),
    ({"context_window": 9007199254740992}, {}), ({"max_tokens": 100}, {}),
    ({"context_window": []}, {}), ({"context_window": {}}, {}),
    ({}, {"reasoning": 0}), ({}, {"reasoning": 1}), ({}, {"vision": "false"}),
    ({}, {"json_schema": None}), ({}, {"tool_calling": []}),
    ({}, {"json_object": {}}), ({}, {"vision": 1.0}),
    ({}, {"structured_output": True}), ({}, {"other": False}),
    ([], {}), ({}, []), (None, {}), ({}, None),
])
def test_invalid_values_reject_without_changing_file_or_factory(env, limits, capabilities):
    assert patch(env, {"max_output_tokens": 500}, {"json_schema": False}).status_code == 200
    before_file, before_cache = env.path.read_bytes(), snapshot()
    response = request(env.transport, "PATCH", json={
        "provider": "gateway", "model_name": MODEL, "limits": limits, "capabilities": capabilities,
    })
    assert response.status_code in (400, 422)
    assert_unchanged(env, before_file, before_cache)


@pytest.mark.parametrize("limits,capabilities", [
    ({"context_window": True}, {}), ({"max_tokens": 1}, {}),
    ({"max_output_tokens": -2}, {}), ({"context_window": 1.0}, {}),
    ({"context_window": 9007199254740992}, {}), ({}, {"vision": 1}),
    ({}, {"structured_output": False}), ([], {}), ({}, None),
])
def test_adapter_also_enforces_strict_validation(env, limits, capabilities):
    before_file, before_cache = env.path.read_bytes(), snapshot()
    with pytest.raises(ValueError):
        env.adapter.update_model_metadata("gateway", MODEL, limits, capabilities)
    assert_unchanged(env, before_file, before_cache)


@pytest.mark.parametrize("limits", [
    {"context_window": 6000}, {"max_input_tokens": 10001}, {"max_output_tokens": 10001},
    {"context_window": 1500, "max_input_tokens": 1000},
    {"context_window": 8000, "max_input_tokens": 8001, "max_output_tokens": 100},
    {"context_window": 8000, "max_input_tokens": 100, "max_output_tokens": 8001},
])
def test_cross_field_validation_uses_merged_defaults_and_rejects_atomically(env, limits):
    assert patch(env, {"max_input_tokens": 5000}, {"vision": True}).status_code == 200
    before_file, before_cache = env.path.read_bytes(), snapshot()
    response = patch(env, limits, {"vision": False})
    assert response.status_code == 400
    assert "context_window" in response.json()["detail"]
    assert_unchanged(env, before_file, before_cache)


def test_boundary_safe_integer_and_independent_input_output_checks(env):
    response = patch(env, {"context_window": 10000, "max_input_tokens": 9000, "max_output_tokens": 9000})
    assert response.status_code == 200  # The two limits are individually bounded, not summed.
    maximum = 9007199254740991
    response = patch(env, {"context_window": maximum, "max_input_tokens": maximum, "max_output_tokens": 1})
    assert response.status_code == 200
    assert response.json()["overrides"]["limits"]["context_window"] == maximum


@pytest.mark.parametrize("provider,model_name", [
    ("missing", MODEL), ("gateway", "missing/model:rev"),
    ("empty", MODEL), ("gateway", ""), ("", MODEL),
    ("deepseek", "deepseek-chat"),  # Even catalog-known models must first be registered.
])
@pytest.mark.parametrize("method", ["GET", "PATCH"])
def test_missing_or_unregistered_identity_rejects_without_mutation(env, provider, model_name, method):
    before_file, before_cache = env.path.read_bytes(), snapshot()
    identity = {"provider": provider, "model_name": model_name}
    response = (request(env.transport, "GET", params=identity) if method == "GET"
                else request(env.transport, "PATCH", json={**identity, "limits": {}, "capabilities": {}}))
    assert response.status_code == 400
    assert_unchanged(env, before_file, before_cache)


@pytest.mark.parametrize("changes", [
    {"provider": None}, {"provider": 7}, {"model_name": None}, {"model_name": False},
    {"protocol": "responses"}, {"id": MODEL}, {"metadata_overrides": {}},
])
def test_invalid_identity_types_and_unknown_body_fields(env, changes):
    before_file, before_cache = env.path.read_bytes(), snapshot()
    response = request(env.transport, "PATCH", json={
        "provider": "gateway", "model_name": MODEL, "limits": {}, "capabilities": {}, **changes,
    })
    assert response.status_code == 422
    assert_unchanged(env, before_file, before_cache)


@pytest.mark.parametrize("missing", ["provider", "model_name", "limits", "capabilities"])
def test_missing_patch_fields_reject(env, missing):
    payload = {"provider": "gateway", "model_name": MODEL, "limits": {}, "capabilities": {}}
    payload.pop(missing)
    before_file, before_cache = env.path.read_bytes(), snapshot()
    assert request(env.transport, "PATCH", json=payload).status_code == 422
    assert_unchanged(env, before_file, before_cache)


@pytest.mark.parametrize("params", [{}, {"provider": "gateway"}, {"model_name": MODEL}])
def test_missing_get_identity_rejects(env, params):
    before_file, before_cache = env.path.read_bytes(), snapshot()
    assert request(env.transport, "GET", params=params).status_code == 422
    assert_unchanged(env, before_file, before_cache)


def test_validation_reads_current_disk_defaults_without_mutating_loaded_factory(env):
    changed = copy.deepcopy(env.original)
    changed["providers"]["gateway"]["models"][0]["limits"]["max_input_tokens"] = 9500
    env.path.write_text(json.dumps(changed), encoding="utf-8")
    before_file, before_cache = env.path.read_bytes(), snapshot()
    assert patch(env, {"context_window": 8000}).status_code == 400
    assert_unchanged(env, before_file, before_cache)


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("path", ["direct", "adapter"])
def test_persisted_false_tool_capability_reaches_wire_without_losing_history_or_budget(env, monkeypatch, protocol, path):
    from Agent.core.adapter.llm_adapter import OpenAIAdapter
    from Agent.core.llm.client import OpenAIClientBase
    from Agent.core.stream.stream_processor import StreamProcessor

    class SilentLogger:
        def start(self, *_):
            return None

        def append(self, *_):
            pass

    config = copy.deepcopy(env.original)
    config["providers"]["gateway"]["models"][0]["protocol"] = protocol
    env.path.write_text(json.dumps(config), encoding="utf-8")
    assert patch(env, {"max_output_tokens": 256}, {"tool_calling": False}).status_code == 200
    monkeypatch.setattr("Agent.core.api.config.get_structured_output_enabled", lambda: True)
    monkeypatch.setattr("Agent.core.llm.client.APILogger", SilentLogger)
    LLMFactory.PROVIDERS["gateway"].client_class = OpenAIClientBase
    captured = []
    history = [
        {"role": "system", "content": "Use the previous lookup result."},
        {"role": "user", "content": "Find it."},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_prior", "type": "function", "function": {"name": "lookup", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_prior", "content": "saved result"},
        {"role": "user", "content": "Answer."},
    ]
    expected_history = history if protocol == "chat_completions" else [
        history[0], history[1],
        {"type": "function_call", "call_id": "call_prior", "name": "lookup", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_prior", "output": "saved result"},
        history[4],
    ]

    async def handler(req):
        captured.append(json.loads(req.content))
        if protocol == "chat_completions":
            return httpx.Response(200, json={
                "id": "chat_test", "object": "chat.completion", "created": 1, "model": MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            })
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 1, "status": "completed", "model": MODEL,
            "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "ok", "annotations": []}]}],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })

    async def run():
        client, _ = LLMFactory.create(f"gateway:{MODEL}")
        assert client.capabilities["tool_calling"] is False
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        options = {
            "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
            "tool_choice": "required", "parallel_tool_calls": True, "max_tokens": 500,
        }
        try:
            if path == "adapter":
                result = await OpenAIAdapter(client, StreamProcessor()).complete(history, stream=False, **options)
                assert result["content"] == "ok"
            else:
                await client.create_chat_completion(history, **options)
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(captured) == 1
    payload = captured[0]
    assert payload["model"] == MODEL
    assert payload["messages" if protocol == "chat_completions" else "input"] == expected_history
    # The adapter enforces model budgets; direct calls retain the caller's budget.
    assert payload["max_tokens" if protocol == "chat_completions" else "max_output_tokens"] == (256 if path == "adapter" else 500)
    assert not {"tools", "tool_choice", "parallel_tool_calls", "response_format"} & payload.keys()
    assert not payload.get("text", {}).get("format")
    if protocol == "responses":
        assert payload["store"] is False


def test_write_failure_does_not_change_factory_cache(env, monkeypatch):
    before_file, before_cache = env.path.read_bytes(), snapshot()

    def fail(_):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(env.adapter, "_write_models_config", fail)
    with pytest.raises(OSError, match="simulated disk failure"):
        env.adapter.update_model_metadata("gateway", MODEL, {"max_output_tokens": 500}, {"vision": True})
    assert_unchanged(env, before_file, before_cache)
