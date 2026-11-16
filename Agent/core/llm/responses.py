"""Responses protocol translation; histories remain local to the application."""

from __future__ import annotations
from openai import AsyncOpenAI

from Agent.core.llm.request_compat import create_with_compat, normalize_options


def _input(messages):
    result = []
    for message in messages:
        if message.get("_response_items") is not None:
            result.extend(message["_response_items"])
        elif message["role"] == "tool":
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": str(message.get("error") or message.get("content") or ""),
                }
            )
        else:
            content = message.get("content") or ""
            if content or not message.get("tool_calls"):
                result.append({"role": message["role"], "content": content})
            for call in message.get("tool_calls", []):
                fn = call["function"]
                result.append(
                    {
                        "type": "function_call",
                        "call_id": call["id"],
                        "name": fn["name"],
                        "arguments": fn.get("arguments", "{}"),
                    }
                )
    return result


def _params(messages, kwargs):
    kwargs = normalize_options({"store": False, **kwargs})
    tools = kwargs.pop("tools", None)
    kwargs.pop("enable_reasoning", None)
    kwargs.pop("include_reasoning_content", None)
    kwargs.pop("thinking", None)
    kwargs.pop("reasoning_split", None)
    kwargs.pop("stream_options", None)
    kwargs.setdefault("store", False)
    kwargs.setdefault("include", ["reasoning.encrypted_content"])
    response_format = kwargs.pop("response_format", None)
    if response_format:
        if response_format.get("type") == "json_schema":
            response_format = {"type": "json_schema", **response_format["json_schema"]}
        kwargs["text"] = {**kwargs.get("text", {}), "format": response_format}
    if "max_tokens" in kwargs:
        kwargs["max_output_tokens"] = kwargs.pop("max_tokens")
    if "max_completion_tokens" in kwargs:
        kwargs["max_output_tokens"] = kwargs.pop("max_completion_tokens")
    if tools:
        kwargs["tools"] = [
            {"type": "function", "strict": False, **tool["function"]} for tool in tools
        ]
    if (
        isinstance(kwargs.get("tool_choice"), dict)
        and "function" in kwargs["tool_choice"]
    ):
        kwargs["tool_choice"] = {
            "type": "function",
            "name": kwargs["tool_choice"]["function"]["name"],
        }
    if not tools:
        kwargs.pop("tool_choice", None)
        kwargs.pop("parallel_tool_calls", None)
    # Vendor extensions belong in extra_body, not in the SDK's Python arguments.
    standard = {
        "include", "instructions", "max_output_tokens", "metadata", "parallel_tool_calls",
        "previous_response_id", "reasoning", "service_tier", "store", "temperature",
        "text", "tool_choice", "tools", "top_p", "truncation", "user", "timeout",
        "extra_headers", "extra_query", "prompt_cache_key", "safety_identifier",
    }
    extra = dict(kwargs.pop("extra_body", {}) or {})
    extra.update({key: kwargs.pop(key) for key in list(kwargs) if key not in standard})
    if extra:
        kwargs["extra_body"] = extra
    return {"input": _input(messages), **kwargs}


def _dump(obj):
    return obj.model_dump(exclude_none=True) if hasattr(obj, "model_dump") else obj


async def stream(client, messages, kwargs):
    sdk = AsyncOpenAI(
        api_key=client.api_key,
        base_url=client.base_url,
        http_client=client._client,
        max_retries=0,
    )
    params = _params(messages, kwargs)
    log_path = client._logger.start(
        "responses_stream", {"model": client.model, "params": params}
    )
    try:
        stream = await create_with_compat(client, sdk.responses.create, {
            "model": client.model, "stream": True, **params,
        }, log_path)
    except Exception as exc:
        client._logger.append(
            log_path, "ERROR", {"type": type(exc).__name__, "error": str(exc)}
        )
        raise
    finished = False
    streamed_calls = set()
    try:
        async for event in stream:
            data = _dump(event)
            client._logger.append(log_path, "RESPONSE_CHUNK", data)
            event_type = data.get("type")
            if event_type == "response.output_text.delta":
                yield {"delta": {"content": data.get("delta", "")}}
            elif event_type in (
                "response.reasoning_summary_text.delta",
                "response.reasoning_text.delta",
            ):
                yield {"delta": {}, "reasoning_content": data.get("delta", "")}
            elif (
                event_type == "response.output_item.added"
                and data.get("item", {}).get("type") == "function_call"
            ):
                item = data["item"]
                index = data.get("output_index", 0)
                streamed_calls.add(index)
                yield {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": index,
                                "id": item.get("call_id"),
                                "function": {"name": item.get("name")},
                            }
                        ]
                    }
                }
            elif event_type == "response.function_call_arguments.delta":
                index = data.get("output_index", 0)
                streamed_calls.add(index)
                yield {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": index,
                                "function": {"arguments": data.get("delta", "")},
                            }
                        ]
                    }
                }
            elif event_type == "response.completed":
                response = data["response"]
                items = response.get("output", [])
                calls = [
                    {
                        "index": i,
                        "id": item.get("call_id"),
                        "type": "function",
                        "function": {
                            "name": item.get("name"),
                            "arguments": item.get("arguments", ""),
                        },
                    }
                    for i, item in enumerate(items)
                    if item.get("type") == "function_call" and i not in streamed_calls
                ]
                has_calls = any(item.get("type") == "function_call" for item in items)
                finished = True
                yield {
                    "delta": {"tool_calls": calls},
                    "finish_reason": "tool_calls" if has_calls else "stop",
                    "usage": response.get("usage"),
                    "response_items": items,
                }
            elif event_type in ("response.failed", "response.incomplete", "error"):
                raise RuntimeError(f"Responses stream failed: {data}")
        if not finished:
            raise RuntimeError("Responses stream ended without a completed event")
        client._logger.append(log_path, "RESPONSE_SUMMARY", {"finished": True})
    except Exception as exc:
        client._logger.append(
            log_path, "ERROR", {"type": type(exc).__name__, "error": str(exc)}
        )
        raise
    finally:
        await stream.close()


async def complete(client, messages, kwargs):
    sdk = AsyncOpenAI(
        api_key=client.api_key,
        base_url=client.base_url,
        http_client=client._client,
        max_retries=0,
    )
    params = _params(messages, kwargs)
    log_path = client._logger.start(
        "responses_completion", {"model": client.model, "params": params}
    )
    try:
        result = _dump(await create_with_compat(client, sdk.responses.create, {
            "model": client.model, **params,
        }, log_path))
        client._logger.append(log_path, "RESPONSE", result)
    except Exception as exc:
        client._logger.append(
            log_path, "ERROR", {"type": type(exc).__name__, "error": str(exc)}
        )
        raise
    if result.get("status") != "completed":
        raise RuntimeError(
            f"Responses request did not complete: {result.get('status')}"
        )
    items = result.get("output", [])
    calls = [
        {
            "id": item.get("call_id"),
            "type": "function",
            "function": {
                "name": item.get("name"),
                "arguments": item.get("arguments", ""),
            },
        }
        for item in items
        if item.get("type") == "function_call"
    ]
    text = "".join(
        part.get("text", "")
        for item in items
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    )
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text, "tool_calls": calls},
                "finish_reason": "tool_calls" if calls else "stop",
            }
        ],
        "usage": result.get("usage"),
        "response_items": items,
    }
