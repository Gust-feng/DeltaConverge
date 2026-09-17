from __future__ import annotations

import unittest

import httpx

from Agent.core.adapter.llm_adapter import OpenAIAdapter
from Agent.core.stream.stream_processor import StreamProcessor


class _TransportErrorClient:
    def __init__(self) -> None:
        self.non_stream_calls = 0

    async def stream_chat(self, messages, **kwargs):
        if False:
            yield {}
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)"
        )

    async def create_chat_completion(self, messages, **kwargs):
        self.non_stream_calls += 1
        return {}


class _FatalClient:
    def __init__(self) -> None:
        self.non_stream_calls = 0

    async def stream_chat(self, messages, **kwargs):
        if False:
            yield {}
        raise RuntimeError("API Request Failed (401): bad key")

    async def create_chat_completion(self, messages, **kwargs):
        self.non_stream_calls += 1
        return {}


class _NonStreamClient:
    def __init__(self) -> None:
        self.stream_calls = 0
        self.non_stream_calls = 0

    async def stream_chat(self, messages, **kwargs):
        self.stream_calls += 1
        if False:
            yield {}

    async def create_chat_completion(self, messages, **kwargs):
        self.non_stream_calls += 1
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "non-stream content",
                    },
                    "finish_reason": "stop",
                }
            ]
        }


class StreamContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_adapter_surfaces_stream_transport_error_without_retry(self) -> None:
        client = _TransportErrorClient()
        adapter = OpenAIAdapter(client, StreamProcessor(), provider_name="deepseek")

        with self.assertRaises(httpx.RemoteProtocolError):
            await adapter.complete([{"role": "user", "content": "hello"}])

        self.assertEqual(client.non_stream_calls, 0)

    async def test_openai_adapter_does_not_hide_non_recoverable_errors(self) -> None:
        client = _FatalClient()
        adapter = OpenAIAdapter(client, StreamProcessor(), provider_name="deepseek")

        with self.assertRaisesRegex(RuntimeError, "401"):
            await adapter.complete([{"role": "user", "content": "hello"}])

        self.assertEqual(client.non_stream_calls, 0)

    async def test_openai_adapter_non_stream_path_stays_explicit(self) -> None:
        client = _NonStreamClient()
        adapter = OpenAIAdapter(client, StreamProcessor(), provider_name="deepseek")

        result = await adapter.complete(
            [{"role": "user", "content": "hello"}],
            stream=False,
        )

        self.assertEqual(client.stream_calls, 0)
        self.assertEqual(client.non_stream_calls, 1)
        self.assertEqual(result["content"], "non-stream content")
        self.assertEqual(result["raw"]["source"], "non_stream")

    async def test_openai_adapter_rejects_prefer_non_stream_mode(self) -> None:
        client = _NonStreamClient()
        adapter = OpenAIAdapter(client, StreamProcessor(), provider_name="deepseek")

        with self.assertRaisesRegex(RuntimeError, "strict kernel contract"):
            await adapter.complete(
                [{"role": "user", "content": "hello"}],
                prefer_non_stream=True,
            )


if __name__ == "__main__":
    unittest.main()
