from __future__ import annotations

import asyncio
import copy
import functools
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from Agent.core.api import config as config_module
from Agent.core.adapter.llm_adapter import OpenAIAdapter
from Agent.core.llm.client import OpenAIClientBase
from Agent.core.llm.request_compat import select_response_format
from Agent.core.stream.stream_processor import StreamProcessor
from adapters.web.dependencies import get_facade
from adapters.web.routers.config import router as config_router
from kernel.application.services.config_service import ConfigService
from kernel.infrastructure.config_adapter import LegacyConfigAdapter


_MODEL = "structured-output-test-model"
_ANSWER = {"answer": "ok"}
_TEXT = json.dumps(_ANSWER, separators=(",", ":"))
_MESSAGES = [
    {"role": "system", "content": "Return a JSON object with an answer string."},
    {"role": "user", "content": "Answer in JSON, even without an API format constraint."},
]
_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    },
}


def async_test(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


class _SilentLogger:
    def start(self, label, payload):
        return None

    def append(self, path, section, payload):
        pass


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    # Redirect the constructor BEFORE its first load, including after rebuilding
    # both singleton references. No production config file is read or written.
    monkeypatch.setattr(config_module, "__file__", str(tmp_path / "config.py"))
    monkeypatch.setattr(config_module.ConfigManager, "_instance", None)
    monkeypatch.setattr(config_module, "_config_manager", None)

    def rebuild():
        monkeypatch.setattr(config_module.ConfigManager, "_instance", None)
        monkeypatch.setattr(config_module, "_config_manager", None)
        manager = config_module.get_config_manager()
        assert manager._config_path == tmp_path / "kernel_config.json"
        assert config_module.ConfigManager() is manager
        return manager

    return SimpleNamespace(
        manager=rebuild(), rebuild=rebuild, path=tmp_path / "kernel_config.json"
    )


@pytest.fixture
def config_api(isolated_config, tmp_path):
    service = ConfigService(config_port=LegacyConfigAdapter(root=tmp_path))
    facade = SimpleNamespace(
        config_service=service,
        get_config=service.get_config,
        update_config=service.update_config,
    )
    app = FastAPI()
    app.include_router(config_router)
    app.dependency_overrides[get_facade] = lambda: facade
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client_factory(isolated_config):
    @asynccontextmanager
    async def make(protocol, handler, capabilities=None):
        client = OpenAIClientBase(
            _MODEL,
            api_key="test-only-not-a-credential",
            base_url="https://example.invalid/v1",
            logger=_SilentLogger(),
        )
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client.protocol = protocol
        client.capabilities = copy.deepcopy(capabilities or {})
        try:
            yield client
        finally:
            await client.aclose()

    return make


def _set_enabled(enabled, persist=False):
    config_module.get_config_manager().update_config(
        {"llm": {"enable_structured_output": enabled}}, persist=persist
    )
    assert config_module.get_structured_output_enabled() is enabled


def _sse(*events, done=False):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events) + (
        "data: [DONE]\n\n" if done else ""
    )


def _success_response(protocol, stream):
    if protocol == "chat_completions":
        common = {"id": "chatcmpl_setting", "created": 1, "model": _MODEL}
        if stream:
            def chunk(delta, finish_reason=None):
                return {
                    **common,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                }

            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse(
                    chunk({"role": "assistant", "content": _TEXT[:10]}),
                    chunk({"content": _TEXT[10:]}),
                    chunk({}, "stop"),
                    done=True,
                ),
            )
        return httpx.Response(200, json={
            **common,
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": _TEXT},
                "finish_reason": "stop",
            }],
        })
    response = {
        "id": "resp_setting",
        "object": "response",
        "created_at": 1,
        "model": _MODEL,
        "status": "completed",
        "output": [{
            "id": "msg_setting",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": _TEXT, "annotations": []}],
        }],
    }
    if not stream:
        return httpx.Response(200, json=response)
    events = [
        {
            "type": "response.output_text.delta",
            "sequence_number": index,
            "item_id": "msg_setting",
            "output_index": 0,
            "content_index": 0,
            "delta": part,
        }
        for index, part in enumerate((_TEXT[:10], _TEXT[10:]))
    ]
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=_sse(*events, {
            "type": "response.completed", "sequence_number": 2, "response": response
        }),
    )


async def _complete(client, via_adapter, stream, messages, options):
    if via_adapter:
        result = await OpenAIAdapter(client, StreamProcessor()).complete(
            messages, stream=stream, **options
        )
    elif stream:
        result = await StreamProcessor().collect(client.stream_chat(messages, **options))
    else:
        response = await client.create_chat_completion(messages, **options)
        # Direct completion returns the normalized protocol envelope, not the
        # adapter's NormalizedMessage. Check and parse its actual JSON content.
        choice = response["choices"][0]
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["content"] == _TEXT
        assert json.loads(choice["message"]["content"]) == _ANSWER
        return
    assert result["content"] == _TEXT
    assert result["content_json"] == _ANSWER
    assert result["finish_reason"] == "stop"


def _assert_wire(payload, protocol, stream, expected_format):
    assert payload["model"] == _MODEL
    # Responses omits stream for a nonstream request; the SDK defaults it to false.
    assert payload.get("stream", False) is stream
    assert payload["input" if protocol == "responses" else "messages"] == _MESSAGES
    if expected_format is None:
        assert "response_format" not in payload
        assert "format" not in payload.get("text", {})
    elif protocol == "responses":
        assert "response_format" not in payload
        expected = (
            {"type": "json_schema", **expected_format["json_schema"]}
            if expected_format["type"] == "json_schema" else expected_format
        )
        assert payload["text"]["format"] == expected
    else:
        assert payload["response_format"] == expected_format
    if protocol == "responses":
        assert payload["store"] is False


@pytest.mark.parametrize("legacy", [False, True], ids=["missing-file", "legacy-file"])
def test_config_defaults_and_legacy_field_are_false(isolated_config, config_api, legacy):
    assert config_module.LLMConfig().enable_structured_output is False
    assert not isolated_config.path.exists()
    if legacy:
        isolated_config.path.write_text(
            json.dumps({"llm": {"call_timeout": 187}}), encoding="utf-8"
        )
        isolated_config.rebuild()
    assert config_module.get_structured_output_enabled() is False
    response = config_api.get("/api/v2/config")
    assert response.status_code == 200
    assert response.json()["llm"]["enable_structured_output"] is False
    if legacy:
        assert response.json()["llm"]["call_timeout"] == 187
        assert "enable_structured_output" not in json.loads(
            isolated_config.path.read_text(encoding="utf-8")
        )["llm"]
    else:
        assert not isolated_config.path.exists()


def test_v2_config_persists_both_values_and_reloads_singleton(isolated_config, config_api):
    previous = isolated_config.manager
    for enabled in (True, False):
        response = config_api.patch("/api/v2/config", json={
            "updates": {"llm": {"enable_structured_output": enabled, "call_timeout": 187}},
            "persist": True,
        })
        assert response.status_code == 200
        assert response.json()["llm"]["enable_structured_output"] is enabled
        assert config_module.get_structured_output_enabled() is enabled
        assert json.loads(isolated_config.path.read_text(encoding="utf-8"))["llm"][
            "enable_structured_output"
        ] is enabled
        rebuilt = isolated_config.rebuild()
        assert rebuilt is not previous
        assert rebuilt.get_config().llm.enable_structured_output is enabled
        assert config_module.get_structured_output_enabled() is enabled
        loaded = config_api.get("/api/v2/config")
        assert loaded.status_code == 200
        assert loaded.json()["llm"]["enable_structured_output"] is enabled
        assert loaded.json()["llm"]["call_timeout"] == 187
        previous = rebuilt


@pytest.mark.parametrize("value", [None, 0, 1, 0.0, 1.0, "true", "false", "", [], {}])
def test_non_bool_updates_are_rejected_without_mutation(isolated_config, config_api, value):
    _set_enabled(True, persist=True)
    original_file = isolated_config.path.read_bytes()
    original_config = isolated_config.manager.get_config().to_dict()
    with pytest.raises(ValueError, match=r"llm\.enable_structured_output"):
        isolated_config.manager.update_config(
            {"llm": {"enable_structured_output": value}}, persist=True
        )
    response = config_api.patch("/api/v2/config", json={
        "updates": {"llm": {"enable_structured_output": value}}, "persist": True
    })
    assert response.status_code == 400
    assert "llm.enable_structured_output" in response.json()["detail"]
    assert isolated_config.manager.get_config().to_dict() == original_config
    assert config_module.get_structured_output_enabled() is True
    assert isolated_config.path.read_bytes() == original_file


@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
@pytest.mark.parametrize("capabilities, expected_kind", [
    pytest.param({}, "json_schema", id="unknown-explicit-opt-in"),
    pytest.param({"json_schema": True}, "json_schema", id="schema"),
    pytest.param({"structured_output": True}, "json_schema", id="legacy-schema-capability"),
    pytest.param({"json_schema": False, "json_object": True}, "json_object", id="json-only"),
    pytest.param({"structured_output": False, "json_object": True}, "json_object", id="legacy-json-only"),
    pytest.param({"json_schema": False, "json_object": False}, None, id="unsupported"),
])
def test_select_schema_respects_setting_and_capabilities(
    isolated_config, enabled, capabilities, expected_kind
):
    _set_enabled(enabled)
    requested = copy.deepcopy(_SCHEMA)
    original = copy.deepcopy(requested)
    result = select_response_format(SimpleNamespace(capabilities=capabilities), requested)
    if not enabled or expected_kind is None:
        assert result is None
    else:
        assert result == (_SCHEMA if expected_kind == "json_schema" else {"type": "json_object"})
    assert requested == original


@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
@pytest.mark.parametrize("json_supported", [False, True])
def test_select_json_object_respects_setting_and_capability(
    isolated_config, enabled, json_supported
):
    _set_enabled(enabled)
    result = select_response_format(
        SimpleNamespace(capabilities={"json_object": json_supported}), {"type": "json_object"}
    )
    assert result == ({"type": "json_object"} if enabled and json_supported else None)


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
@pytest.mark.parametrize("via_adapter", [True, False], ids=["adapter", "direct"])
@pytest.mark.parametrize("source", ["keyword", "extra_body"])
@pytest.mark.parametrize("capability", ["schema", "json", "unknown"])
@async_test
async def test_real_sdk_wire_setting_matrix(
    isolated_config, client_factory, protocol, stream, enabled, via_adapter, source, capability
):
    _set_enabled(enabled)
    capabilities = {
        "schema": {"json_schema": True, "json_object": True},
        "json": {"json_schema": False, "json_object": True},
        "unknown": {},
    }[capability]
    expected_format = {"type": "json_object"} if capability == "json" else _SCHEMA
    # The adapter chooses from capabilities; a direct caller supplies its format.
    requested = _SCHEMA if via_adapter else expected_format
    options = {"max_tokens": 113, "extra_body": {"vendor_trace": "setting-test"}}
    if source == "extra_body":
        options["extra_body"]["response_format"] = copy.deepcopy(requested)
    else:
        options["response_format"] = copy.deepcopy(requested)
    original = copy.deepcopy(options)
    messages = copy.deepcopy(_MESSAGES)
    requests = []

    def handler(request):
        assert request.url.path == (
            "/v1/responses" if protocol == "responses" else "/v1/chat/completions"
        )
        requests.append(json.loads(request.content))
        return _success_response(protocol, stream)

    async with client_factory(protocol, handler, capabilities) as client:
        await _complete(client, via_adapter, stream, messages, options)
    assert len(requests) == 1
    _assert_wire(requests[0], protocol, stream, expected_format if enabled else None)
    assert requests[0]["vendor_trace"] == "setting-test"
    assert requests[0]["max_output_tokens" if protocol == "responses" else "max_tokens"] == 113
    assert options == original
    assert messages == _MESSAGES


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@pytest.mark.parametrize("via_adapter", [True, False], ids=["adapter", "direct"])
@async_test
async def test_same_client_observes_off_on_off_without_rebuilding(
    isolated_config, config_api, client_factory, protocol, stream, via_adapter
):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return _success_response(protocol, stream)

    async with client_factory(protocol, handler) as client:
        transport_client = client._client
        adapter = OpenAIAdapter(client, StreamProcessor())
        for enabled in (False, True, False):
            response = config_api.patch("/api/v2/config", json={
                "updates": {"llm": {"enable_structured_output": enabled}}, "persist": False
            })
            assert response.status_code == 200
            assert config_module.get_structured_output_enabled() is enabled
            options = {"extra_body": {"response_format": copy.deepcopy(_SCHEMA)}}
            if via_adapter:
                result = await adapter.complete(copy.deepcopy(_MESSAGES), stream=stream, **options)
                assert result["content_json"] == _ANSWER
            else:
                await _complete(client, False, stream, copy.deepcopy(_MESSAGES), options)
            assert client._client is transport_client
            _assert_wire(requests[-1], protocol, stream, _SCHEMA if enabled else None)
    assert len(requests) == 3
    assert not isolated_config.path.exists()


@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@pytest.mark.parametrize("via_adapter", [True, False], ids=["adapter", "direct"])
@pytest.mark.parametrize("source", ["response_format", "text", "extra_body"])
@async_test
async def test_disabled_responses_format_keeps_text_verbosity(
    isolated_config, client_factory, stream, via_adapter, source
):
    _set_enabled(False)
    text = {"verbosity": "low"}
    if source == "response_format":
        options = {"response_format": copy.deepcopy(_SCHEMA), "text": text}
    else:
        text["format"] = {"type": "json_schema", **copy.deepcopy(_SCHEMA["json_schema"])}
        options = {"text": text} if source == "text" else {"extra_body": {"text": text}}
    original = copy.deepcopy(options)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return _success_response("responses", stream)

    async with client_factory("responses", handler) as client:
        await _complete(client, via_adapter, stream, copy.deepcopy(_MESSAGES), options)
    assert len(requests) == 1
    _assert_wire(requests[0], "responses", stream, None)
    assert requests[0]["text"] == {"verbosity": "low"}
    assert options == original
