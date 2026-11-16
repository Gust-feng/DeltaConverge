from __future__ import annotations

import asyncio
import copy
import functools
import json
from contextlib import asynccontextmanager

import httpx
import openai
import pytest

from Agent.core.adapter.llm_adapter import OpenAIAdapter
from Agent.core.llm.client import OpenAIClientBase
from Agent.core.stream.stream_processor import StreamProcessor


def async_test(function):
    # Match test_llm_transport_contract without requiring pytest-asyncio.
    @functools.wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


class _SilentLogger:
    """Exercise the real client without creating API log files."""

    def start(self, label, payload):
        return None

    def append(self, path, section, payload):
        pass


@pytest.fixture(autouse=True)
def enable_output_parameters(monkeypatch):
    monkeypatch.setattr("Agent.core.api.config.get_structured_output_enabled", lambda: True)


@pytest.fixture
def client_factory():
    @asynccontextmanager
    async def make(protocol, handler, capabilities=None):
        client = OpenAIClientBase(
            "compat-regression-model",
            api_key="test-only",
            base_url="https://example.invalid/v1",
            logger=_SilentLogger(),
        )
        await client._client.aclose()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client.protocol = protocol
        if capabilities is not None:
            client.capabilities = copy.deepcopy(capabilities)
        try:
            yield client
        finally:
            await client.aclose()

    return make


@pytest.fixture
def response_format():
    return {
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


@pytest.fixture
def tools():
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up a source before answering.",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                    "additionalProperties": False,
                },
            },
        }
    ]


@pytest.fixture
def history():
    return [
        {"role": "system", "content": "Return a JSON object with an answer."},
        {"role": "user", "content": "Look up the previous answer."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_prior",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"q":"prior"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_prior", "content": "source found"},
        {"role": "user", "content": "Now answer in JSON."},
    ]


@pytest.fixture
def wire_history(history):
    # Explicit expected protocol histories, rather than calling production converters.
    return {
        "chat_completions": copy.deepcopy(history),
        "responses": [
            {"role": "system", "content": "Return a JSON object with an answer."},
            {"role": "user", "content": "Look up the previous answer."},
            {
                "type": "function_call",
                "call_id": "call_prior",
                "name": "lookup",
                "arguments": '{"q":"prior"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_prior",
                "output": "source found",
            },
            {"role": "user", "content": "Now answer in JSON."},
        ],
    }


def _sse(*events, done=False):
    body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    return body + ("data: [DONE]\n\n" if done else "")


def _chat_chunk(delta, finish_reason=None):
    return {
        "id": "chatcmpl_test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "compat-regression-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _response_body(text):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "model": "compat-regression-model",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
    }


def _text_event(text):
    return {
        "type": "response.output_text.delta",
        "sequence_number": 0,
        "item_id": "msg_test",
        "output_index": 0,
        "content_index": 0,
        "delta": text,
    }


@pytest.fixture
def success_response():
    def make(protocol, stream, text='{"answer":"ok"}'):
        if protocol == "chat_completions":
            if stream:
                usage_tail = {
                    "id": "chatcmpl_test",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "compat-regression-model",
                    "choices": [],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                }
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    text=_sse(
                        _chat_chunk({"role": "assistant", "content": text}),
                        _chat_chunk({}, "stop"),
                        usage_tail,
                        done=True,
                    ),
                )
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl_test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "compat-regression-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": text},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                },
            )
        response = _response_body(text)
        if stream:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=_sse(
                    _text_event(text),
                    {"type": "response.completed", "sequence_number": 1, "response": response},
                ),
            )
        return httpx.Response(200, json=response)

    return make


def _rejection(param, message, status=400, code="unsupported_parameter"):
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": "invalid_request_error", "param": param, "code": code}},
    )


def _wire_format(payload, protocol):
    if protocol == "responses":
        return payload.get("text", {}).get("format")
    return payload.get("response_format")


def _without_format(payload, protocol):
    result = copy.deepcopy(payload)
    if protocol == "responses":
        text = result.get("text", {})
        text.pop("format", None)
        if not text:
            result.pop("text", None)
    else:
        result.pop("response_format", None)
    return result


def _assert_result(result):
    assert result["content"] == '{"answer":"ok"}'
    assert result["content_json"] == {"answer": "ok"}
    assert result["finish_reason"] == "stop"
    assert result["usage"]["total_tokens"] == 10


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@async_test
async def test_format_fallback_preserves_request_and_is_cached_on_client(
    client_factory, success_response, response_format, tools, history, wire_history, protocol, stream
):
    requests = []

    async def handler(request):
        assert request.url.path == ("/v1/responses" if protocol == "responses" else "/v1/chat/completions")
        payload = json.loads(request.content)
        requests.append(payload)
        fmt = _wire_format(payload, protocol)
        if fmt:
            param = "text.format" if protocol == "responses" else "response_format"
            return _rejection(param, f"{fmt['type']} is not supported for {param}.")
        return success_response(protocol, stream)

    options = {
        "response_format": response_format,
        "tools": tools,
        "max_tokens": 321,
        "temperature": 0.2,
        "extra_body": {"vendor_kept": {"mode": "test"}},
    }
    original = copy.deepcopy((history, options))
    async with client_factory(protocol, handler, {"json_schema": True, "json_object": True}) as client:
        # Recreate adapters deliberately: compatibility memory must belong to the client.
        _assert_result(await OpenAIAdapter(client, StreamProcessor()).complete(history, stream=stream, **options))
        assert len(requests) == 3
        formats = [_wire_format(item, protocol) for item in requests]
        expected_schema = (
            {"type": "json_schema", **response_format["json_schema"]}
            if protocol == "responses" else response_format
        )
        assert formats == [expected_schema, {"type": "json_object"}, None]
        assert all(_without_format(item, protocol) == _without_format(requests[0], protocol) for item in requests)

        next_history = history + [{"role": "user", "content": "A different JSON answer, please."}]
        for requested_format in (response_format, {"type": "json_object"}):
            next_options = {**options, "response_format": requested_format}
            _assert_result(await OpenAIAdapter(client, StreamProcessor()).complete(next_history, stream=stream, **next_options))
        assert len(requests) == 5
        assert all(_wire_format(item, protocol) is None for item in requests[3:])

    input_key = "input" if protocol == "responses" else "messages"
    budget_key = "max_output_tokens" if protocol == "responses" else "max_tokens"
    expected_tools = (
        [{"type": "function", "strict": False, **tools[0]["function"]}]
        if protocol == "responses" else tools
    )
    for index, payload in enumerate(requests):
        expected_history = wire_history[protocol] + (next_history[-1:] if index >= 3 else [])
        assert payload[input_key] == expected_history
        assert payload["tools"] == expected_tools
        assert payload[budget_key] == 321
        assert payload["vendor_kept"] == {"mode": "test"}
        assert payload.get("stream", False) is stream
        assert payload["model"] == "compat-regression-model"
        if protocol == "responses":
            assert payload["store"] is False
    assert (history, options) == original


@pytest.mark.parametrize(
    "protocol,parameter,value,status",
    [
        pytest.param("chat_completions", "temperature", 0.3, 400, id="chat-temperature"),
        pytest.param("responses", "temperature", 0.3, 400, id="responses-temperature"),
        pytest.param("chat_completions", "stream_options", {"include_usage": True}, 422, id="chat-stream-options"),
        pytest.param("chat_completions", "vendor_toggle", True, 400, id="chat-vendor-extension"),
        pytest.param("responses", "vendor_toggle", True, 400, id="responses-vendor-extension"),
    ],
)
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@async_test
async def test_explicitly_unsupported_optional_parameter_only_is_removed_and_cached(
    client_factory, success_response, tools, history, protocol, parameter, value, status, stream
):
    requests = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if parameter in payload:
            return _rejection(parameter, f"Unsupported parameter: '{parameter}'.", status=status)
        return success_response(protocol, stream)

    options = {"tools": tools, "max_tokens": 257, "extra_body": {"vendor_kept": {"x": 1}}}
    if parameter == "vendor_toggle":
        options["extra_body"][parameter] = value
    else:
        options[parameter] = value
    original = copy.deepcopy(options)
    async with client_factory(protocol, handler) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        _assert_result(await adapter.complete(history, stream=stream, **options))
        assert len(requests) == 2
        assert requests[0][parameter] == value
        expected = {key: item for key, item in requests[0].items() if key != parameter}
        assert requests[1] == expected
        _assert_result(await adapter.complete(history, stream=stream, **options))
        assert requests[2:] == [expected]
    assert options == original


@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@async_test
async def test_responses_unknown_sdk_extensions_reach_wire_without_type_error(
    client_factory, success_response, stream
):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return success_response("responses", stream)

    options = {
        "vendor_route": "fast",
        "extra_body": {"vendor_policy": {"cache": "off"}},
        "reasoning": {"effort": "low"},
        "stream_options": {"include_usage": True},
        "max_completion_tokens": 233,
    }
    async with client_factory("responses", handler) as client:
        result = await OpenAIAdapter(client, StreamProcessor()).complete(
            [{"role": "user", "content": "Return JSON."}], stream=stream, **options
        )
        _assert_result(result)
    assert len(requests) == 1
    payload = requests[0]
    assert payload["vendor_route"] == "fast"
    assert payload["vendor_policy"] == {"cache": "off"}
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["max_output_tokens"] == 233
    assert payload["store"] is False
    assert "extra_body" not in payload
    assert "stream_options" not in payload
    assert "max_completion_tokens" not in payload
    assert options["extra_body"] == {"vendor_policy": {"cache": "off"}}


@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@async_test
async def test_chat_max_tokens_renamed_without_losing_each_calls_budget(
    client_factory, success_response, tools, history, stream
):
    requests = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "max_tokens" in payload:
            return _rejection(
                "max_tokens",
                "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead.",
            )
        return success_response("chat_completions", stream)

    async with client_factory("chat_completions", handler) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        for budget in (127, 255):
            _assert_result(await adapter.complete(history, tools=tools, max_tokens=budget, stream=stream))
    assert len(requests) == 3
    assert requests[0]["max_tokens"] == 127
    expected = {key: value for key, value in requests[0].items() if key != "max_tokens"}
    assert requests[1] == {**expected, "max_completion_tokens": 127}
    assert requests[2] == {**expected, "max_completion_tokens": 255}


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@pytest.mark.parametrize(
    "status,message,param,code",
    [
        pytest.param(500, "json_schema response_format is not supported.", "response_format", "unsupported_parameter", id="server-error"),
        pytest.param(401, "json_schema response_format is not supported.", "response_format", "unsupported_parameter", id="unauthorized"),
        pytest.param(429, "json_schema response_format is not supported.", "response_format", "unsupported_parameter", id="rate-limit"),
        pytest.param(400, "Bad request.", None, None, id="generic-bad-request"),
        pytest.param(400, "This operation is not supported.", None, None, id="unspecified-unsupported-operation"),
        pytest.param(400, "temperature must be between 0 and 2.", "temperature", "invalid_value", id="invalid-temperature-value"),
    ],
)
@async_test
async def test_errors_without_explicit_optional_support_rejection_are_not_retried(
    client_factory, response_format, protocol, stream, status, message, param, code
):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return _rejection(param, message, status=status, code=code)

    async with client_factory(protocol, handler, {"json_schema": True}) as client:
        with pytest.raises(openai.APIStatusError) as caught:
            await OpenAIAdapter(client, StreamProcessor()).complete(
                [{"role": "user", "content": "Return JSON."}],
                stream=stream,
                response_format=response_format,
                temperature=9 if param == "temperature" else 0.2,
                max_tokens=111,
            )
        assert caught.value.status_code == status
        assert caught.value.body["message"] == message
    assert len(requests) == 1


class _BrokenStream(httpx.AsyncByteStream):
    def __init__(self, protocol, fault):
        self.protocol = protocol
        self.fault = fault
        self.closed = False

    async def __aiter__(self):
        first = _text_event("partial") if self.protocol == "responses" else _chat_chunk({"content": "partial"})
        yield _sse(first).encode("utf-8")
        if self.fault == "transport":
            raise httpx.ReadError("Connection interrupted after the first token")
        if self.fault == "malformed-json":
            yield b"data: {invalid-json}\n\n"
        elif self.fault == "error-event":
            if self.protocol == "responses":
                event = {
                    "type": "response.failed",
                    "sequence_number": 1,
                    "response": {
                        **_response_body("partial"),
                        "status": "failed",
                        "error": {"code": "unsupported_parameter", "message": "temperature is not supported"},
                    },
                }
            else:
                event = {"error": {"message": "temperature is not supported", "param": "temperature", "code": "unsupported_parameter"}}
            yield _sse(event).encode("utf-8")
        # A truncated stream intentionally has no terminal finish/completed event.

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("fault", ["transport", "malformed-json", "error-event", "truncated"])
@async_test
async def test_started_stream_failure_reaches_user_without_replaying(
    client_factory, protocol, fault
):
    requests = []
    bodies = []
    observed = []

    async def handler(request):
        requests.append(json.loads(request.content))
        body = _BrokenStream(protocol, fault)
        bodies.append(body)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

    async with client_factory(protocol, handler) as client:
        with pytest.raises((RuntimeError, ValueError, httpx.ReadError, openai.APIError)):
            await OpenAIAdapter(client, StreamProcessor()).complete(
                [{"role": "user", "content": "Return JSON."}],
                temperature=0.2,
                observer=observed.append,
            )
    assert "".join(event["content_delta"] for event in observed) == "partial"
    assert len(requests) == 1
    assert len(bodies) == 1 and bodies[0].closed


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@async_test
async def test_explicitly_unsupported_tools_can_degrade_without_dropping_other_fields(
    client_factory, success_response, response_format, tools, history, protocol, stream
):
    requests = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "tools" in payload:
            return _rejection("tools", "This model does not support tools.")
        return success_response(protocol, stream)

    options = {
        "tools": tools,
        "tool_choice": {"type": "function", "function": {"name": "lookup"}},
        "parallel_tool_calls": False,
        "response_format": response_format,
        "max_tokens": 211,
    }
    original = copy.deepcopy(options)
    async with client_factory(protocol, handler, {"json_schema": True}) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        _assert_result(await adapter.complete(history, stream=stream, **options))
        assert len(requests) == 2
        expected = {key: value for key, value in requests[0].items() if key not in {"tools", "tool_choice", "parallel_tool_calls"}}
        assert requests[1] == expected
        _assert_result(await adapter.complete(history, stream=stream, **options))
        assert requests[2:] == [expected]
    assert options == original


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@pytest.mark.parametrize("with_format", [False, True], ids=["plain-output", "schema-output"])
@async_test
async def test_invalid_tool_schema_is_reported_without_removing_tools_or_retrying_format(
    client_factory, response_format, tools, protocol, stream, with_format
):
    requests = []
    message = "Invalid schema for function 'lookup': parameters.properties.q must have a valid type."

    async def handler(request):
        requests.append(json.loads(request.content))
        return _rejection("tools[0].function.parameters", message, code="invalid_function_parameters")

    options = {"response_format": response_format} if with_format else {}
    async with client_factory(protocol, handler, {"json_schema": True}) as client:
        with pytest.raises(openai.BadRequestError) as caught:
            await OpenAIAdapter(client, StreamProcessor()).complete(
                [{"role": "user", "content": "Look it up; return JSON."}],
                tools=tools,
                stream=stream,
                max_tokens=223,
                **options,
            )
        assert caught.value.body["message"] == message
    assert len(requests) == 1
    assert requests[0]["tools"]


@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@async_test
async def test_responses_storage_opt_out_is_not_dropped_for_compatibility(
    client_factory, stream
):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return _rejection("store", "Unsupported parameter: 'store'.")

    async with client_factory("responses", handler) as client:
        with pytest.raises(openai.BadRequestError):
            await OpenAIAdapter(client, StreamProcessor()).complete(
                [{"role": "user", "content": "Return JSON."}], stream=stream, store=False
            )
    assert len(requests) == 1
    assert requests[0]["store"] is False


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("stream", [True, False], ids=["stream", "nonstream"])
@pytest.mark.parametrize("requested", ["json_schema", "json_object"])
@pytest.mark.parametrize(
    "capabilities,schema_expected,object_expected",
    [
        pytest.param(None, "json_schema", "json_object", id="unknown-no-capabilities-attribute"),
        pytest.param({}, "json_schema", "json_object", id="unknown-empty-capabilities"),
        pytest.param({"json_schema": False, "json_object": False}, None, None, id="explicitly-no-formats"),
        pytest.param({"json_schema": False, "json_object": True}, "json_object", "json_object", id="json-mode-only"),
        pytest.param({"json_schema": True, "json_object": False}, "json_schema", None, id="strict-only"),
        pytest.param({"json_schema": True, "json_object": True}, "json_schema", "json_object", id="both-formats"),
        pytest.param({"structured_output": True}, "json_schema", "json_object", id="legacy-strict-alias"),
        pytest.param({"structured_output": True, "json_schema": False, "json_object": True}, "json_object", "json_object", id="explicit-schema-flag-overrides-alias"),
    ],
)
@async_test
async def test_adapter_uses_known_format_capabilities_consistently_for_all_paths(
    client_factory, success_response, response_format, protocol, stream, requested,
    capabilities, schema_expected, object_expected
):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return success_response(protocol, stream)

    requested_format = response_format if requested == "json_schema" else {"type": "json_object"}
    original = copy.deepcopy(requested_format)
    async with client_factory(protocol, handler, capabilities) as client:
        _assert_result(await OpenAIAdapter(client, StreamProcessor()).complete(
            [{"role": "user", "content": "Return a JSON object with an answer."}],
            response_format=requested_format,
            stream=stream,
        ))
    assert len(requests) == 1
    expected = schema_expected if requested == "json_schema" else object_expected
    fmt = _wire_format(requests[0], protocol)
    if expected is None:
        assert fmt is None
    elif expected == "json_object":
        assert fmt == {"type": "json_object"}
    else:
        expected_schema = (
            {"type": "json_schema", **response_format["json_schema"]}
            if protocol == "responses" else response_format
        )
        assert fmt == expected_schema
    assert requested_format == original
    assert requests[0].get("stream", False) is stream


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@async_test
async def test_stream_format_rejection_does_not_affect_nonstream_cache(
    client_factory, success_response, response_format, protocol
):
    requests = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        streaming = payload.get("stream", False)
        if streaming and _wire_format(payload, protocol)["type"] == "json_schema":
            param = "text.format" if protocol == "responses" else "response_format"
            return _rejection(param, "json_schema is not supported for streaming.")
        return success_response(protocol, streaming)

    async with client_factory(protocol, handler, {"json_schema": True, "json_object": True}) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        for streaming in (True, False, True, False):
            _assert_result(await adapter.complete(
                [{"role": "user", "content": "Return JSON."}],
                response_format=response_format,
                stream=streaming,
            ))
    assert [item.get("stream", False) for item in requests] == [True, True, False, True, False]
    assert [_wire_format(item, protocol)["type"] for item in requests] == [
        "json_schema", "json_object", "json_schema", "json_object", "json_schema"
    ]


@pytest.mark.parametrize(
    "protocol,stream",
    [("chat_completions", True), ("responses", False)],
)
@async_test
async def test_unsuccessful_format_negotiation_does_not_cache_rejection(
    client_factory, success_response, response_format, protocol, stream
):
    requests = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            param = "text.format" if protocol == "responses" else "response_format"
            return _rejection(param, "json_schema is not supported.")
        if len(requests) == 2:
            return _rejection(None, "Temporary server failure.", status=500, code=None)
        return success_response(protocol, stream)

    async with client_factory(protocol, handler, {"json_schema": True, "json_object": True}) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        options = {"response_format": response_format, "stream": stream, "max_tokens": 147}
        messages = [{"role": "user", "content": "Return JSON."}]
        with pytest.raises(openai.InternalServerError):
            await adapter.complete(messages, **options)
        assert len(requests) == 2
        _assert_result(await adapter.complete(messages, **options))
    assert len(requests) == 3
    assert [_wire_format(item, protocol)["type"] for item in requests] == [
        "json_schema", "json_object", "json_schema"
    ]
    assert requests[2] == requests[0]


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@pytest.mark.parametrize("via_adapter", [False, True], ids=["direct-client", "adapter"])
@async_test
async def test_normalization_preserves_request_identity_and_removes_duplicate_temperature(
    client_factory, success_response, response_format, protocol, via_adapter
):
    requests = []
    messages = [{"role": "user", "content": "Return the real JSON answer."}]
    options = {
        "temperature": 0.2,
        "max_tokens": 137,
        "extra_body": {
            "model": "wrong-model",
            "messages": [{"role": "user", "content": "Wrong chat input."}],
            "input": [{"role": "user", "content": "Wrong responses input."}],
            "stream": True,
            "store": True,
            "temperature": 0.9,
            "max_tokens": 999,
            "top_p": 0.7,
            "response_format": response_format,
            "vendor_kept": {"mode": "unchanged"},
        },
    }
    original = copy.deepcopy(options)

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "temperature" in payload:
            return _rejection("temperature", "Unsupported parameter: temperature.")
        return success_response(protocol, False)

    async with client_factory(protocol, handler, {"json_schema": True}) as client:
        if via_adapter:
            _assert_result(await OpenAIAdapter(client, StreamProcessor()).complete(
                messages, stream=False, **options
            ))
        else:
            result = await client.create_chat_completion(messages, **options)
            assert result["choices"][0]["message"]["content"] == '{"answer":"ok"}'
            assert result["choices"][0]["finish_reason"] == "stop"
    assert len(requests) == 2
    first, retried = requests
    assert first["temperature"] == 0.2
    assert retried == {key: value for key, value in first.items() if key != "temperature"}
    assert first["model"] == "compat-regression-model"
    assert first.get("stream", False) is False
    assert first["top_p"] == 0.7
    assert first["vendor_kept"] == {"mode": "unchanged"}
    assert "extra_body" not in first
    assert _wire_format(first, protocol)["type"] == "json_schema"
    if protocol == "responses":
        assert first["input"] == messages
        assert first["store"] is False
        assert first["max_output_tokens"] == 137
        assert "messages" not in first
        assert "max_tokens" not in first
    else:
        assert first["messages"] == messages
        assert first["max_tokens"] == 137
        assert "input" not in first
        assert "store" not in first
    assert options == original


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@async_test
async def test_extra_body_token_budget_is_checked_and_clamped_before_transport(
    client_factory, success_response, protocol
):
    requests = []
    budget_key = "max_output_tokens" if protocol == "responses" else "max_tokens"
    messages = [{"role": "user", "content": "Return JSON."}]

    async def handler(request):
        requests.append(json.loads(request.content))
        return success_response(protocol, False)

    async with client_factory(protocol, handler) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        client.limits = {"context_window": 512}
        _assert_result(await adapter.complete(
            messages, stream=False, extra_body={"max_tokens": 64}
        ))
        assert requests[0][budget_key] == 64
        with pytest.raises(ValueError, match="context window"):
            await adapter.complete(messages, stream=False, extra_body={"max_tokens": 1024})
        with pytest.raises(ValueError, match="only one output token limit"):
            await adapter.complete(
                messages, stream=False, max_tokens=64, extra_body={"max_completion_tokens": 65}
            )
        assert len(requests) == 1
        client.limits = {"context_window": 512, "max_output_tokens": 128}
        _assert_result(await adapter.complete(
            messages, stream=False, extra_body={"max_tokens": 1024}
        ))
    assert len(requests) == 2
    assert requests[1][budget_key] == 128
    assert requests[1] == {**requests[0], budget_key: 128}


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@async_test
async def test_unsupported_token_budget_from_extra_body_is_not_silently_deleted(
    client_factory, protocol
):
    requests = []
    budget_key = "max_output_tokens" if protocol == "responses" else "max_tokens"
    options = {"extra_body": {"max_tokens": 256, "vendor_kept": "yes"}}
    original = copy.deepcopy(options)

    async def handler(request):
        requests.append(json.loads(request.content))
        return _rejection(budget_key, f"Unsupported parameter: '{budget_key}'.")

    async with client_factory(protocol, handler) as client:
        with pytest.raises(openai.BadRequestError):
            await client.create_chat_completion(
                [{"role": "user", "content": "Return JSON."}], **options
            )
    assert len(requests) == 1
    assert requests[0][budget_key] == 256
    assert requests[0]["vendor_kept"] == "yes"
    assert options == original


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@async_test
async def test_required_tool_choice_rejection_only_removes_choice_when_message_mentions_tools(
    client_factory, success_response, tools, protocol
):
    requests = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "tool_choice" in payload:
            return _rejection(
                "tool_choice",
                "The required tool_choice is not supported with these tools.",
                code="unsupported_value",
            )
        return success_response(protocol, False)

    async with client_factory(protocol, handler) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        for _ in range(2):
            _assert_result(await adapter.complete(
                [{"role": "user", "content": "Look up the answer in JSON."}],
                stream=False,
                tools=tools,
                tool_choice="required",
                parallel_tool_calls=True,
                max_tokens=153,
            ))
    assert len(requests) == 4
    assert requests[0]["tool_choice"] == "required"
    expected = {key: value for key, value in requests[0].items() if key != "tool_choice"}
    # A rejected choice value does not establish that all choices are unsupported.
    assert requests == [requests[0], expected, requests[0], expected]
    assert expected["tools"]
    assert expected["parallel_tool_calls"] is True


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@async_test
async def test_explicit_token_upper_bound_reduces_budget_without_dropping_it(
    client_factory, success_response, tools, protocol
):
    requests = []
    budget_key = "max_output_tokens" if protocol == "responses" else "max_tokens"

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload[budget_key] > 128:
            return _rejection(
                budget_key, f"{budget_key} must be <=128", code="invalid_value"
            )
        return success_response(protocol, False)

    async with client_factory(protocol, handler) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        for budget in (512, 64):
            _assert_result(await adapter.complete(
                [{"role": "user", "content": "Look up a JSON answer."}],
                tools=tools,
                stream=False,
                extra_body={"max_tokens": budget, "vendor_kept": True},
            ))
    assert len(requests) == 3
    assert [item[budget_key] for item in requests] == [512, 128, 64]
    unchanged = {key: value for key, value in requests[0].items() if key != budget_key}
    assert all({key: value for key, value in item.items() if key != budget_key} == unchanged for item in requests)


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
@async_test
async def test_adapter_explicit_tools_take_priority_over_extra_body_tools(
    client_factory, success_response, tools, protocol
):
    requests = []
    options = {
        "extra_body": {
            "tools": [{"type": "function", "function": {"name": "wrong_tool", "parameters": {"type": "object"}}}],
        },
    }
    original = copy.deepcopy(options)

    async def handler(request):
        requests.append(json.loads(request.content))
        return success_response(protocol, False)

    async with client_factory(protocol, handler) as client:
        result = await OpenAIAdapter(client, StreamProcessor()).complete(
            [{"role": "user", "content": "Use lookup and return JSON."}],
            tools=tools,
            stream=False,
            **options,
        )
        _assert_result(result)
        assert result["tool_schemas"] == tools
    assert len(requests) == 1
    assert requests[0]["tools"] == (
        [{"type": "function", "strict": False, **tools[0]["function"]}]
        if protocol == "responses" else tools
    )
    assert options == original


@async_test
async def test_unsupported_schema_keyword_fallback_does_not_cache_format_rejection(
    client_factory, success_response, response_format
):
    requests = []
    keyword_format = copy.deepcopy(response_format)
    keyword_format["json_schema"]["schema"]["properties"]["answer"] = {
        "oneOf": [{"type": "string"}, {"type": "integer"}]
    }
    original = copy.deepcopy(keyword_format)

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        fmt = payload.get("response_format", {})
        answer_schema = fmt.get("json_schema", {}).get("schema", {}).get("properties", {}).get("answer", {})
        if "oneOf" in answer_schema:
            return _rejection(
                "response_format",
                "Unsupported keyword 'oneOf' in response_format schema.",
            )
        return success_response("chat_completions", False)

    async with client_factory("chat_completions", handler, {"json_schema": True}) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        for requested_format in (keyword_format, response_format):
            _assert_result(await adapter.complete(
                [{"role": "user", "content": "Return JSON."}],
                response_format=requested_format,
                max_tokens=167,
                stream=False,
            ))
    assert len(requests) == 3
    assert [item["response_format"] for item in requests] == [
        keyword_format, {"type": "json_object"}, response_format
    ]
    unchanged = _without_format(requests[0], "chat_completions")
    assert all(_without_format(item, "chat_completions") == unchanged for item in requests)
    assert keyword_format == original


@async_test
async def test_rejected_required_tool_choice_does_not_remove_later_none_choice(
    client_factory, success_response, tools
):
    requests = []

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload.get("tool_choice") == "required":
            return _rejection(
                "tool_choice", "tool_choice value 'required' is not supported with these tools.",
                code="unsupported_value",
            )
        return success_response("chat_completions", False)

    async with client_factory("chat_completions", handler) as client:
        adapter = OpenAIAdapter(client, StreamProcessor())
        for choice in ("required", "none"):
            _assert_result(await adapter.complete(
                [{"role": "user", "content": "Return JSON."}],
                tools=tools,
                tool_choice=choice,
                stream=False,
            ))
    assert len(requests) == 3
    assert requests[0]["tool_choice"] == "required"
    expected = {key: value for key, value in requests[0].items() if key != "tool_choice"}
    assert requests[1] == expected
    assert requests[2] == {**expected, "tool_choice": "none"}
    assert all(item["tools"] == tools for item in requests)


@async_test
async def test_responses_top_level_instructions_metadata_truncation_override_extra_body(
    client_factory, success_response
):
    requests = []
    options = {
        "instructions": "Return the requested JSON answer.",
        "metadata": {"request_tag": "real"},
        "truncation": "disabled",
        "extra_body": {
            "instructions": "Incorrect instructions.",
            "metadata": {"request_tag": "wrong", "extra_only": "must not merge"},
            "truncation": "auto",
            "vendor_kept": {"mode": "test"},
        },
    }
    original = copy.deepcopy(options)

    async def handler(request):
        requests.append(json.loads(request.content))
        return success_response("responses", False)

    async with client_factory("responses", handler) as client:
        _assert_result(await OpenAIAdapter(client, StreamProcessor()).complete(
            [{"role": "user", "content": "Return JSON."}], stream=False, **options
        ))
    assert len(requests) == 1
    payload = requests[0]
    assert payload["instructions"] == options["instructions"]
    assert payload["metadata"] == {"request_tag": "real"}
    assert payload["truncation"] == "disabled"
    assert payload["vendor_kept"] == {"mode": "test"}
    assert "extra_body" not in payload
    assert options == original


@async_test
async def test_responses_unsupported_text_verbosity_keeps_schema_format(
    client_factory, success_response, response_format
):
    requests = []
    options = {"response_format": response_format, "text": {"verbosity": "low"}, "max_tokens": 179}
    original = copy.deepcopy(options)

    async def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "verbosity" in payload.get("text", {}):
            return _rejection("text.verbosity", "Unsupported parameter: 'text.verbosity'.")
        return success_response("responses", False)

    async with client_factory("responses", handler, {"json_schema": True}) as client:
        _assert_result(await OpenAIAdapter(client, StreamProcessor()).complete(
            [{"role": "user", "content": "Return JSON."}], stream=False, **options
        ))
    assert len(requests) == 2
    expected_schema = {"type": "json_schema", **response_format["json_schema"]}
    assert requests[0]["text"] == {"verbosity": "low", "format": expected_schema}
    assert requests[1] == {**requests[0], "text": {"format": expected_schema}}
    assert options == original
