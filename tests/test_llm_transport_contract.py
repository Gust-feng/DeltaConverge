from __future__ import annotations
import json
import asyncio
import functools
import httpx
import pytest
from Agent.core.llm.client import OpenAIClientBase
from Agent.core.adapter.llm_adapter import OpenAIAdapter
from Agent.core.stream.stream_processor import StreamProcessor
from kernel.infrastructure.llm_adapter import LegacyLLMClient
from kernel.ports.llm import Message, MessageRole


@pytest.fixture(autouse=True)
def enable_output_parameters(monkeypatch):
    monkeypatch.setattr("Agent.core.api.config.get_structured_output_enabled", lambda: True)


def async_test(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def sse(*events):
    return (
        "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        + "data: [DONE]\n\n"
    )


@async_test
async def test_usage_tail_and_incomplete_stream():
    body = sse(
        {"choices": [{"delta": {"content": "hello"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"total_tokens": 4}},
    )

    async def handler(request):
        return httpx.Response(200, text=body)

    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAIAdapter(client, StreamProcessor())
    result = await adapter.complete([{"role": "user", "content": "hi"}])
    assert result["content"] == "hello"
    assert result["usage"] == {"total_tokens": 4}
    body = sse({"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]})
    with pytest.raises(RuntimeError, match="without a finish reason"):
        await adapter.complete([{"role": "user", "content": "hi"}])
    await client.aclose()
    assert client._client.is_closed


@async_test
async def test_legacy_port_uses_adapter_async():
    class Adapter:
        async def complete(self, messages, **kwargs):
            assert messages == [{"role": "user", "content": "hi"}]
            assert kwargs["stream"] is False
            return {
                "content": "ok",
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            }

    port = LegacyLLMClient(Adapter(), "test")
    result = await port.send_async([Message(MessageRole.USER, "hi")])
    assert result.content == "ok"
    assert result.usage == {"input_tokens": 2, "output_tokens": 1}


@async_test
async def test_responses_tool_history_and_budget():
    from Agent.core.state.conversation import ConversationState

    requests = []
    output = [
        {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [],
            "encrypted_content": "cipher",
        },
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"q":"x"}',
            "status": "completed",
        },
    ]

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        items = (
            output
            if len(requests) == 1
            else [
                {
                    "type": "message",
                    "id": "m1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "report", "annotations": []}
                    ],
                }
            ]
        )
        events = (
            []
            if len(requests) == 1
            else [
                {
                    "type": "response.output_text.delta",
                    "delta": "report",
                    "item_id": "m1",
                    "output_index": 0,
                    "content_index": 0,
                }
            ]
        )
        events.append(
            {
                "type": "response.completed",
                "response": {
                    "id": "r1",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "test",
                    "output": items,
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                    "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                },
            }
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=sse(*events)
        )

    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid/v1"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.protocol = "responses"
    client.limits = {"context_window": 10000, "max_output_tokens": 100}
    adapter = OpenAIAdapter(client, StreamProcessor())
    state = ConversationState()
    state.add_user_message("find")
    first = await adapter.complete(
        state.messages,
        tools=[
            {
                "type": "function",
                "function": {"name": "lookup", "parameters": {"type": "object"}},
            }
        ],
    )
    assert first["tool_calls"][0]["arguments"] == {"q": "x"}
    assert first["usage"]["total_tokens"] == 5
    state.add_assistant_message(
        "", first["tool_calls"], response_items=first["response_items"]
    )
    state.add_tool_result({"tool_call_id": "call_1", "error": "denied"})
    final = await adapter.complete(state.messages)
    assert final["content"] == "report"
    assert requests[0]["max_output_tokens"] == 100
    assert requests[1]["input"][1:3] == output
    assert requests[1]["input"][3] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "denied",
    }
    client.limits = {"context_window": 10, "max_output_tokens": 5}
    with pytest.raises(ValueError, match="context window"):
        await adapter.complete(state.messages)
    await client.aclose()


@async_test
async def test_legacy_port_closes_client_and_rejects_sync_in_loop():
    class Client:
        closed = False

        async def aclose(self):
            self.closed = True

    class Adapter:
        client = Client()

    port = LegacyLLMClient(Adapter(), "test")
    with pytest.raises(RuntimeError, match="async"):
        port.send([])
    await port.aclose()
    assert port._adapter.client.closed


def test_config_custom_provider_without_write(tmp_path, monkeypatch):
    from Agent.core.api.factory import LLMFactory

    config = {
        "providers": {
            "custom": {
                "label": "Custom",
                "api_key_env": "TEST_CUSTOM_KEY",
                "base_url": "https://example.invalid/v1",
                "protocol": "responses",
                "models": [
                    {
                        "id": "vendor:model:v1",
                        "capabilities": {"reasoning": True},
                        "limits": {"context_window": 4096, "max_output_tokens": 100},
                    }
                ],
            }
        }
    }
    path = tmp_path / "models.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    original = path.read_bytes()
    monkeypatch.setattr(LLMFactory, "_CONFIG_PATH", path)
    monkeypatch.setattr(LLMFactory, "_MODELS", {})
    monkeypatch.setattr(LLMFactory, "_MODEL_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "_PROVIDER_SETTINGS", {})
    monkeypatch.setattr(LLMFactory, "PROVIDERS", dict(LLMFactory.PROVIDERS))
    monkeypatch.setenv("TEST_CUSTOM_KEY", "test")
    client, provider = LLMFactory.create("custom:vendor:model:v1")
    assert provider == "custom" and client.model == "vendor:model:v1"
    assert client.protocol == "responses" and client.limits["context_window"] == 4096
    assert path.read_bytes() == original
    import asyncio

    asyncio.run(client.aclose())


def test_responses_input_and_schema_conversion():
    from Agent.core.llm.responses import _params

    params = _params(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c", "function": {"name": "f", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c", "error": "denied"},
        ],
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "answer",
                    "schema": {"type": "object"},
                    "strict": True,
                },
            },
            "thinking": {"type": "enabled"},
        },
    )
    assert params["input"][0]["type"] == "function_call"
    assert params["input"][1]["output"] == "denied"
    assert params["text"]["format"]["name"] == "answer"
    assert params["store"] is False and "thinking" not in params


@async_test
async def test_responses_stream_arguments_and_incomplete():
    output = [
        {
            "type": "function_call",
            "id": "fc",
            "call_id": "c",
            "name": "find",
            "arguments": '{"x":1}',
            "status": "completed",
        }
    ]
    events = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "id": "fc",
                "call_id": "c",
                "name": "find",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc",
            "output_index": 0,
            "delta": '{"x":',
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc",
            "output_index": 0,
            "delta": "1}",
        },
        {
            "type": "response.completed",
            "response": {
                "id": "r",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "test",
                "output": output,
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
        },
    ]

    async def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=sse(*events)
        )

    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid/v1"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.protocol = "responses"
    observed = []
    adapter = OpenAIAdapter(client, StreamProcessor())
    result = await adapter.complete(
        [{"role": "user", "content": "find"}], observer=observed.append
    )
    assert result["tool_calls"][0]["arguments"] == {"x": 1}
    assert sum(bool(event["tool_calls_delta"]) for event in observed) == 3
    events.pop()
    with pytest.raises(RuntimeError, match="without a completed event"):
        await adapter.complete([{"role": "user", "content": "find"}])
    await client.aclose()


def test_invalid_configuration_does_not_publish_partial_state(tmp_path, monkeypatch):
    from Agent.core.api.factory import LLMFactory

    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {"providers": {"good": {"models": ["m"]}, "bad": {"protocol": "other"}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(LLMFactory, "_CONFIG_PATH", path)
    monkeypatch.setattr(LLMFactory, "_MODELS", {})
    monkeypatch.setattr(LLMFactory, "PROVIDERS", dict(LLMFactory.PROVIDERS))
    with pytest.raises(ValueError, match="Invalid protocol"):
        LLMFactory._ensure_models_loaded()
    assert LLMFactory._MODELS == {}
    assert "good" not in LLMFactory.PROVIDERS


@async_test
async def test_responses_explicit_non_stream():
    async def handler(request):
        payload = json.loads(request.content)
        assert payload.get("stream") is not True
        return httpx.Response(
            200,
            json={
                "id": "r",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "test",
                "output": [
                    {
                        "type": "message",
                        "id": "m",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "done", "annotations": []}
                        ],
                    }
                ],
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid/v1"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.protocol = "responses"
    result = await OpenAIAdapter(client, StreamProcessor()).complete(
        [{"role": "user", "content": "x"}], stream=False
    )
    assert result["content"] == "done"
    assert result["response_items"][0]["id"] == "m"
    await client.aclose()


@async_test
async def test_sdk_does_not_retry_errors_and_closes():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": {"message": "failure"}})

    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid/v1"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(Exception):
        await OpenAIAdapter(client, StreamProcessor()).complete(
            [{"role": "user", "content": "x"}]
        )
    assert calls == 1
    await client.aclose()
    assert client._client.is_closed


@async_test
async def test_reviewer_responses_tool_round_trip():
    from Agent.agents.code_reviewer import CodeReviewAgent
    from Agent.core.tools.runtime import ToolRuntime

    requests = []
    items = [
        {"type": "reasoning", "id": "rs", "summary": [], "encrypted_content": "cipher"},
        {
            "type": "function_call",
            "id": "fc",
            "call_id": "call",
            "name": "lookup",
            "arguments": '{"q":"x"}',
            "status": "completed",
        },
    ]

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        output = (
            items
            if len(requests) == 1
            else [
                {
                    "type": "message",
                    "id": "m",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "final report",
                            "annotations": [],
                        }
                    ],
                }
            ]
        )
        events = (
            []
            if len(requests) == 1
            else [
                {
                    "type": "response.output_text.delta",
                    "delta": "final report",
                    "item_id": "m",
                    "output_index": 0,
                    "content_index": 0,
                }
            ]
        )
        events.append(
            {
                "type": "response.completed",
                "response": {
                    "id": "r",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "test",
                    "output": output,
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                },
            }
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=sse(*events)
        )

    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid/v1"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.protocol = "responses"
    runtime = ToolRuntime()
    runtime.register("lookup", lambda args: "found " + args["q"])
    agent = CodeReviewAgent(OpenAIAdapter(client, StreamProcessor()), runtime)
    report = await agent.run(
        "review",
        [],
        tools=[
            {
                "type": "function",
                "function": {"name": "lookup", "parameters": {"type": "object"}},
            }
        ],
        auto_approve_tools=["lookup"],
    )
    assert report == "final report"
    assert requests[1]["input"][-3:-1] == items
    assert requests[1]["input"][-1] == {
        "type": "function_call_output",
        "call_id": "call",
        "output": "found x",
    }
    await client.aclose()


@async_test
async def test_reviewer_chat_hints_are_not_sent_and_glm_thinking_is_preserved():
    from Agent.agents.code_reviewer import CodeReviewAgent
    from Agent.core.llm.client import GLMLLMClient
    from Agent.core.tools.runtime import ToolRuntime

    for client_class in (OpenAIClientBase, GLMLLMClient):
        requests = []

        async def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=sse(
                    {
                        "id": "x",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "test",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "report"},
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "x",
                        "object": "chat.completion.chunk",
                        "created": 1,
                        "model": "test",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ),
            )

        client = client_class(
            "test", api_key="test", base_url="https://example.invalid/v1"
        )
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        agent = CodeReviewAgent(OpenAIAdapter(client, StreamProcessor()), ToolRuntime())
        assert await agent.run("review", []) == "report"
        payload = requests[0]
        assert "enable_reasoning" not in payload
        assert "include_reasoning_content" not in payload
        if client_class is GLMLLMClient:
            assert payload["thinking"] == {"type": "enabled", "clear_thinking": False}
        else:
            assert "thinking" not in payload
        await client.aclose()


def test_save_mixed_config_preserves_provider_and_model_metadata(tmp_path, monkeypatch):
    from Agent.core.api.factory import LLMFactory

    config = {
        "legacy": ["old"],
        "custom": {
            "base_url": "https://example.invalid/v1",
            "api_key_env": "CUSTOM_KEY",
            "protocol": "responses",
            "models": [{"id": "model", "limits": {"context_window": 4096}}],
        },
    }
    path = tmp_path / "models.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(LLMFactory, "_CONFIG_PATH", path)
    monkeypatch.setattr(LLMFactory, "_MODELS", {})
    monkeypatch.setattr(LLMFactory, "PROVIDERS", dict(LLMFactory.PROVIDERS))
    LLMFactory._ensure_models_loaded()
    LLMFactory._MODELS["custom"].append("new")
    LLMFactory._save_models()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["legacy"] == ["old"]
    assert saved["custom"]["base_url"] == config["custom"]["base_url"]
    assert saved["custom"]["protocol"] == "responses"
    assert saved["custom"]["models"] == config["custom"]["models"] + ["new"]


@async_test
async def test_chat_endpoint_with_trailing_slash_is_normalized():
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse(
                {
                    "id": "x",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            ),
        )

    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid/v1/chat/completions/"
    )
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await OpenAIAdapter(client, StreamProcessor()).complete(
        [{"role": "user", "content": "x"}]
    )
    assert paths == ["/v1/chat/completions"]
    await client.aclose()


@async_test
async def test_responses_native_output_limit_counts_toward_budget():
    client = OpenAIClientBase(
        "test", api_key="test", base_url="https://example.invalid/v1"
    )
    client.protocol = "responses"
    client.limits = {"context_window": 100, "max_output_tokens": 80}
    adapter = OpenAIAdapter(client, StreamProcessor())
    with pytest.raises(ValueError, match="context window"):
        await adapter.complete([{"role": "user", "content": "x"}], max_output_tokens=80)
    with pytest.raises(ValueError, match="only one output token limit"):
        await adapter.complete(
            [{"role": "user", "content": "x"}], max_output_tokens=10, max_tokens=10
        )
    await client.aclose()
